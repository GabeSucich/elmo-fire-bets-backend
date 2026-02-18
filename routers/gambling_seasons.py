from enum import StrEnum
from fastapi import Depends, HTTPException, Query
from fastapi.routing import APIRouter
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from models import (
    User as UserModel, 
    GamblingSeasonState, 
    GamblingSeason as GamblingSeasonModel,
    Gambler as GamblerModel,
    PickVeto,
    Parlay,
    Pick,
    ParlayState,
    User
)
from database import get_db
from .auth import manager
from .common import GamblerResponseData, ParlayResponseData, add_selects_to_parlay_query

from services.season_performance_calculator import SeasonPerformanceCalculator, GamblerPerformance, get_season_score_corrector_class
from services.performance_time_series import TimeSeriesCalculator, TimeSeriesDatum
from services.metric_calculator import GamblerMetricsCalculator

router = APIRouter(
    prefix="/gambling_seasons",
    dependencies=[Depends(manager)],
    tags=["GamblingSeason"]
)

class ListGamblingSeasonEl(BaseModel):
    gambler_id: int
    id: int
    name: str
    year: int
    state: GamblingSeasonState


class GetUserGamblingSeasonsResponseData(BaseModel):
    seasons: list[ListGamblingSeasonEl]

@router.get("/", operation_id="get_user_gambling_seasons", response_model=GetUserGamblingSeasonsResponseData)
async def get_user_gambling_seasions(user: UserModel=Depends(manager)):

    user_gamblers = user.gamblers
    return GetUserGamblingSeasonsResponseData(
        seasons=[
            ListGamblingSeasonEl(
                gambler_id=g.id,
                id=g.gambling_season.id,
                name=g.gambling_season.name,
                year=g.gambling_season.year,
                state=g.gambling_season.state
            ) for g in user_gamblers
        ]
    )


class GetGamblingSeasonResponseData(BaseModel):
    id: int
    gambler_id: int
    name: str
    year: int
    state: GamblingSeasonState
    gamblers: dict[int, GamblerResponseData]

@router.get("/{season_id}", operation_id="get_gambling_season", response_model=GetGamblingSeasonResponseData)
async def get_gambling_season(season_id: int, db: AsyncSession=Depends(get_db), user: UserModel = Depends(manager)):
    result = await db.execute(
        select(GamblingSeasonModel)
        .where(GamblingSeasonModel.id == season_id)
        .options(
            selectinload(GamblingSeasonModel.gamblers)
            .selectinload(GamblerModel.user)
        )
    )
    season = result.scalar_one()
    all_gamblers = {g.id: GamblerResponseData(id=g.id, user_id=g.user_id, first_name=g.user.first_name, last_name=g.user.last_name) for g in season.gamblers}
    try:
        user_gambler = [g for g in all_gamblers.values() if g.user_id == user.id][0]
    except IndexError:
        return HTTPException(403, detail="User is not a gambler in gambling season")
    return GetGamblingSeasonResponseData(
        id=season.id,
        gambler_id=user_gambler.id,
        name=season.name,
        year=season.year,
        state=season.state,
        gamblers=all_gamblers
    )

class GetSeasonParlaysResponseData(BaseModel):
    parlays: list[ParlayResponseData]
    next_offset: int

class GetSeasonParlaysStatusParam(StrEnum):
    OPEN = "open"
    CLOSED = "closed"

class GetSeasonParlaysSortParam(StrEnum):
    ASC = "asc"
    DESC = "desc"

@router.get("/{season_id}/parlays", operation_id="get_season_parlays", response_model=GetSeasonParlaysResponseData)
async def get_season_parlays(
    season_id: int, 
    db: AsyncSession=Depends(get_db),
    limit: int = Query(20, description="The number of results to return"),
    offset: int = Query(0, description="Offset to start descending query"),
    state: ParlayState | None = Query(None, description="State of parlays to retrieve"),
    sort: GetSeasonParlaysSortParam = Query(GetSeasonParlaysSortParam.ASC, description="How to sort parlays in query")
):
    query = select(Parlay).where(Parlay.gambling_season_id==season_id)
    if state is not None:
        query = query.where(Parlay.state == state)
    query_sort = Parlay.order.desc() if sort == GetSeasonParlaysSortParam.DESC else Parlay.order.asc()
    result = await db.execute(
        query
        .order_by(query_sort)
        .limit(limit)
        .offset(offset)
        .options(
            selectinload(Parlay.picks)
            .selectinload(Pick.veto)
            .selectinload(PickVeto.votes)
        ).options(
            selectinload(Parlay.picks)
            .selectinload(Pick.prop_bet_target)
        )
    )
    parlays = result.scalars().all()
    next_offset = offset + len(parlays)

    return GetSeasonParlaysResponseData(
        next_offset=next_offset,
        parlays=[ParlayResponseData.from_model(p) for p in parlays]
    )

class GetSeasonGamblerPerformancesResponseData(BaseModel):
    performances: dict[int, GamblerPerformance]


@router.get("/{season_id}/gambler_performances", operation_id="get_season_gambler_performances", response_model=GetSeasonGamblerPerformancesResponseData)
async def get_season_gambler_performances(
    season_id: int,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db)
) -> GetSeasonGamblerPerformancesResponseData | HTTPException:
    gambling_season = (await db.execute(
        select(GamblingSeasonModel)
        .where(GamblingSeasonModel.id == season_id)
        .options(
            selectinload(GamblingSeasonModel.gamblers)
        )
    )).scalar_one()
    parlays = (
        await db.execute(
            add_selects_to_parlay_query(select(Parlay).where(Parlay.gambling_season_id == season_id))
        )
    ).scalars().all()

    gambler_ids = [g.id for g in gambling_season.gamblers]

    calculators = GamblerMetricsCalculator.calculator_dict_from_parlays(gambler_ids, list(parlays))
    score_corrector_class = get_season_score_corrector_class(gambling_season.year)
    season_calculator = SeasonPerformanceCalculator(calculators, score_corrector_class)
    return GetSeasonGamblerPerformancesResponseData(
        performances=season_calculator.performances
    )

class GetSeasonTimeSeriesResponseData(BaseModel):
    time_series: dict[int, list[TimeSeriesDatum]]

@router.get("{season_id}/time_series", operation_id="get_season_time_series", response_model=GetSeasonTimeSeriesResponseData)
async def get_season_time_series(
    season_id: int,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db)
) -> GetSeasonTimeSeriesResponseData | HTTPException:
    gambling_season = (await db.execute(
        select(GamblingSeasonModel)
        .where(GamblingSeasonModel.id == season_id)
        .options(
            selectinload(GamblingSeasonModel.gamblers)
        )
    )).scalar_one()
    parlays = (
        await db.execute(
            add_selects_to_parlay_query(select(Parlay).where(Parlay.gambling_season_id == season_id))
        )
    ).scalars().all()

    score_corrector_class = get_season_score_corrector_class(gambling_season.year)
    # parlays = list(parlays[:5])
    time_series = TimeSeriesCalculator([g.id for g in gambling_season.gamblers], list(parlays), score_corrector_class)
    return GetSeasonTimeSeriesResponseData(
        time_series=time_series.create_time_series()
    )