from typing import *

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import (
    Gambler,
    GamblingSeason,
    GamblingSeasonState,
    PropBetDirection,
    PropBetType,
    SeasonPick,
    SeasonPickKind,
    SeasonPickWeek,
    User,
)
from services.season_pick_progress import SeasonPickProgress, build_progress
from services.season_rules import SeasonRules, get_season_rules, latest_open_week

from .auth import manager
from .common import PropBetTargetRequestData, PropBetTargetResponseData, get_or_create_prop_bet_target

router = APIRouter(
    prefix="/season_picks",
    dependencies=[Depends(manager)],
    tags=["SeasonPicks"],
)


async def load_season(season_id: int, db: AsyncSession) -> GamblingSeason:
    season = (await db.execute(
        select(GamblingSeason)
        .where(GamblingSeason.id == season_id)
        .options(selectinload(GamblingSeason.gamblers))
    )).scalar_one_or_none()
    if season is None:
        raise HTTPException(status_code=404, detail="Season not found")
    return season


def require_open_for_edits(season: GamblingSeason) -> SeasonRules:
    """Season picks can only be written to a season that runs them and is still live.

    Reads stay available for finished seasons; only writes are refused, and a finished
    season is a conflict rather than a permissions problem.
    """
    rules = get_season_rules(season.year)
    if not rules.season_long_picks:
        raise HTTPException(status_code=404, detail="This season does not have season-long picks")
    if season.state == GamblingSeasonState.COMPLETE:
        raise HTTPException(status_code=409, detail="This season is complete and can no longer be edited")
    return rules


def gambler_for_user(season: GamblingSeason, user: User) -> Gambler:
    for gambler in season.gamblers:
        if gambler.user_id == user.id:
            return gambler
    raise HTTPException(status_code=403, detail="You are not part of this season")


def require_admin(season: GamblingSeason, user: User) -> Gambler:
    gambler = gambler_for_user(season, user)
    if not gambler.is_admin:
        raise HTTPException(status_code=403, detail="Only the season admin can do this")
    return gambler


def require_can_manage_pick(season: GamblingSeason, user: User, gambler_id: int, is_finalized: bool) -> Gambler:
    """Everyone enters their own picks; the admin enters anyone's.

    Finalizing is what locks a pick — after that only the admin can change it, so a
    gambler cannot quietly rewrite a pick once the field is set.
    """
    viewer = gambler_for_user(season, user)
    if viewer.is_admin:
        return viewer
    if viewer.id != gambler_id:
        raise HTTPException(status_code=403, detail="You can only manage your own season picks")
    if is_finalized:
        raise HTTPException(status_code=403, detail="This pick has been finalized and only the admin can change it")
    return viewer


class SeasonPickResponseData(BaseModel):
    id: int
    gambler_id: int
    is_finalized: bool
    gambling_season_id: int
    kind: SeasonPickKind
    prop_bet_target_id: int
    target_name: str
    # The full target, so an edit form can repopulate the selection rather than only
    # being able to print its name.
    prop_bet_target: PropBetTargetResponseData
    prop_type: PropBetType | None
    line: float
    direction: PropBetDirection
    progress: SeasonPickProgress

    @classmethod
    def from_model(cls, pick: SeasonPick, rules: SeasonRules):
        target = pick.prop_bet_target
        return cls(
            id=pick.id,
            gambler_id=pick.gambler_id,
            is_finalized=pick.is_finalized,
            gambling_season_id=pick.gambling_season_id,
            kind=pick.kind,
            prop_bet_target_id=pick.prop_bet_target_id,
            target_name=target.player_name or target.team_name,
            prop_bet_target=PropBetTargetResponseData.from_model(target),
            prop_type=pick.prop_type,
            line=pick.line,
            direction=pick.direction,
            progress=build_progress(pick, rules),
        )


class ListSeasonPicksResponseData(BaseModel):
    season_picks: list[SeasonPickResponseData]
    season_long_picks_enabled: bool
    weeks: int
    pick_count: int
    latest_open_week: int
    viewer_is_admin: bool
    # Whether writes are accepted at all: season picks enabled and the season still live.
    # Saves the client re-deriving a rule the server already owns.
    editable: bool


class SeasonPickRequestData(BaseModel):
    gambler_id: int
    kind: SeasonPickKind
    target: PropBetTargetRequestData
    prop_type: PropBetType | None = None
    line: float
    direction: PropBetDirection


class SeasonPickResponse(BaseModel):
    season_pick: SeasonPickResponseData


class FinalizeRequestData(BaseModel):
    finalized: bool = True


class WeekProgressRequestData(BaseModel):
    played: bool = True
    value: float | None = None


class WeekEntry(WeekProgressRequestData):
    week: int


class WeeksProgressRequestData(BaseModel):
    """Several weeks at once, so catching up a whole season is one request rather than
    one per week — each of which would otherwise re-derive and re-send the progress."""
    weeks: list[WeekEntry]


def validate_pick_shape(body: SeasonPickRequestData) -> None:
    if body.kind == SeasonPickKind.TEAM_WINS:
        if body.prop_type is not None:
            raise HTTPException(status_code=400, detail="Team win totals do not take a prop type")
        if body.target.player_name is not None:
            raise HTTPException(status_code=400, detail="Team win totals must target a team")
    elif body.prop_type is None:
        raise HTTPException(status_code=400, detail="Player props need a prop type")


def validate_week(rules: SeasonRules, week: int, body: WeekProgressRequestData) -> None:
    if not 1 <= week <= rules.weeks:
        raise HTTPException(status_code=400, detail=f"Week must be between 1 and {rules.weeks}")
    if week > latest_open_week(rules):
        raise HTTPException(status_code=400, detail=f"Week {week} has not started yet")
    if body.played and body.value is None:
        raise HTTPException(status_code=400, detail=f"Week {week} was played, so it needs a value")


def apply_week(pick: SeasonPick, week: int, body: WeekProgressRequestData, db: AsyncSession) -> None:
    existing = next((w for w in pick.weeks if w.week == week), None)
    if existing is None:
        db.add(SeasonPickWeek(
            season_pick_id=pick.id,
            week=week,
            played=body.played,
            value=body.value if body.played else None,
        ))
    else:
        existing.played = body.played
        existing.value = body.value if body.played else None


async def query_season_picks(season_id: int, db: AsyncSession) -> list[SeasonPick]:
    return list((await db.execute(
        select(SeasonPick)
        .where(SeasonPick.gambling_season_id == season_id)
        .options(selectinload(SeasonPick.weeks), selectinload(SeasonPick.prop_bet_target))
        .order_by(SeasonPick.gambler_id, SeasonPick.id)
    )).scalars())


async def query_season_pick(pick_id: int, db: AsyncSession) -> SeasonPick:
    pick = (await db.execute(
        select(SeasonPick)
        .where(SeasonPick.id == pick_id)
        .options(selectinload(SeasonPick.weeks), selectinload(SeasonPick.prop_bet_target))
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if pick is None:
        raise HTTPException(status_code=404, detail="Season pick not found")
    return pick


@router.get("/season/{season_id}", operation_id="list_season_picks", response_model=ListSeasonPicksResponseData)
async def list_season_picks(
    season_id: int,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> ListSeasonPicksResponseData:
    season = await load_season(season_id, db)
    rules = get_season_rules(season.year)
    picks = await query_season_picks(season_id, db) if rules.season_long_picks else []

    viewer = next((g for g in season.gamblers if g.user_id == user.id), None)

    return ListSeasonPicksResponseData(
        season_picks=[SeasonPickResponseData.from_model(p, rules) for p in picks],
        season_long_picks_enabled=rules.season_long_picks,
        weeks=rules.weeks,
        pick_count=rules.pick_count,
        latest_open_week=latest_open_week(rules),
        viewer_is_admin=bool(viewer and viewer.is_admin),
        editable=rules.season_long_picks and season.state != GamblingSeasonState.COMPLETE,
    )


@router.post("/season/{season_id}", operation_id="create_season_pick", response_model=SeasonPickResponse)
async def create_season_pick(
    season_id: int,
    body: SeasonPickRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> SeasonPickResponse:
    season = await load_season(season_id, db)
    rules = require_open_for_edits(season)
    require_can_manage_pick(season, user, body.gambler_id, is_finalized=False)
    validate_pick_shape(body)

    owner = next((g for g in season.gamblers if g.id == body.gambler_id), None)
    if owner is None:
        raise HTTPException(status_code=400, detail="That gambler is not in this season")

    existing = [p for p in await query_season_picks(season_id, db) if p.gambler_id == body.gambler_id]
    if len(existing) >= rules.pick_count:
        # Deliberately no name: gambler.user is not eagerly loaded here, and touching it
        # lazily on an async session raises MissingGreenlet — turning a 400 into a 500.
        raise HTTPException(
            status_code=400,
            detail=f"That is already {rules.pick_count} season picks, which is the limit",
        )

    target = await get_or_create_prop_bet_target(body.target, db)
    pick = SeasonPick(
        gambling_season_id=season_id,
        gambler_id=body.gambler_id,
        kind=body.kind,
        prop_bet_target_id=target.id,
        prop_type=body.prop_type,
        line=body.line,
        direction=body.direction,
    )
    db.add(pick)
    await db.commit()

    return SeasonPickResponse(season_pick=SeasonPickResponseData.from_model(
        await query_season_pick(pick.id, db), rules
    ))


@router.put("/{pick_id}", operation_id="update_season_pick", response_model=SeasonPickResponse)
async def update_season_pick(
    pick_id: int,
    body: SeasonPickRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> SeasonPickResponse:
    pick = await query_season_pick(pick_id, db)
    season = await load_season(pick.gambling_season_id, db)
    rules = require_open_for_edits(season)
    require_can_manage_pick(season, user, pick.gambler_id, pick.is_finalized)
    validate_pick_shape(body)

    pick.kind = body.kind
    pick.prop_type = body.prop_type
    pick.line = body.line
    pick.direction = body.direction
    pick.prop_bet_target_id = (await get_or_create_prop_bet_target(body.target, db)).id
    await db.commit()

    return SeasonPickResponse(season_pick=SeasonPickResponseData.from_model(
        await query_season_pick(pick_id, db), rules
    ))


@router.delete("/{pick_id}", operation_id="delete_season_pick")
async def delete_season_pick(
    pick_id: int,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    pick = await query_season_pick(pick_id, db)
    season = await load_season(pick.gambling_season_id, db)
    require_open_for_edits(season)
    require_can_manage_pick(season, user, pick.gambler_id, pick.is_finalized)

    await db.delete(pick)
    await db.commit()
    return {"deleted": pick_id}


@router.put("/{pick_id}/finalize", operation_id="finalize_season_pick", response_model=SeasonPickResponse)
async def finalize_season_pick(
    pick_id: int,
    body: FinalizeRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> SeasonPickResponse:
    pick = await query_season_pick(pick_id, db)
    season = await load_season(pick.gambling_season_id, db)
    rules = require_open_for_edits(season)
    require_admin(season, user)

    pick.is_finalized = body.finalized
    await db.commit()

    return SeasonPickResponse(season_pick=SeasonPickResponseData.from_model(
        await query_season_pick(pick_id, db), rules
    ))


@router.put("/{pick_id}/weeks/{week}", operation_id="update_season_pick_week", response_model=SeasonPickResponse)
async def update_season_pick_week(
    pick_id: int,
    week: int,
    body: WeekProgressRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> SeasonPickResponse:
    pick = await query_season_pick(pick_id, db)
    season = await load_season(pick.gambling_season_id, db)
    rules = require_open_for_edits(season)

    # Anyone can keep their own picks current; the admin can do it for everybody.
    viewer = gambler_for_user(season, user)
    if not viewer.is_admin and viewer.id != pick.gambler_id:
        raise HTTPException(status_code=403, detail="You can only update progress for your own picks")

    validate_week(rules, week, body)

    apply_week(pick, week, body, db)
    await db.commit()

    return SeasonPickResponse(season_pick=SeasonPickResponseData.from_model(
        await query_season_pick(pick_id, db), rules
    ))


@router.put("/{pick_id}/weeks", operation_id="update_season_pick_weeks", response_model=SeasonPickResponse)
async def update_season_pick_weeks(
    pick_id: int,
    body: WeeksProgressRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> SeasonPickResponse:
    pick = await query_season_pick(pick_id, db)
    season = await load_season(pick.gambling_season_id, db)
    rules = require_open_for_edits(season)

    viewer = gambler_for_user(season, user)
    if not viewer.is_admin and viewer.id != pick.gambler_id:
        raise HTTPException(status_code=403, detail="You can only update progress for your own picks")

    seen: set[int] = set()
    for entry in body.weeks:
        if entry.week in seen:
            raise HTTPException(status_code=400, detail=f"Week {entry.week} was sent twice")
        seen.add(entry.week)
        validate_week(rules, entry.week, entry)

    # Validated in full before anything is written, so a bad week in the middle cannot
    # leave half the season saved.
    for entry in body.weeks:
        apply_week(pick, entry.week, entry, db)

    await db.commit()

    return SeasonPickResponse(season_pick=SeasonPickResponseData.from_model(
        await query_season_pick(pick_id, db), rules
    ))
