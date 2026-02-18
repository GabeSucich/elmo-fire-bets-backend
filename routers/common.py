from email.policy import default
from tkinter import UNDERLINE
from typing import *
from datetime import date
from pydantic import BaseModel

from sqlalchemy import Select, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from models import (
    VetoVote,
    VetoApprovalStatus,
    VetoResult,
    PickVeto,
    PropBetTarget,
    PropBetDirection,
    SauceFactor,
    PickResult,
    PropBetType,
    Pick,
    SlateType,
    Parlay,
    User,
    GamblingSeason,
    Gambler,
    ParlayState,
    ParlayResult
)

class GamblerResponseData(BaseModel):
    id: int
    user_id: int
    first_name: str
    last_name: str

class PropBetTargetRequestData(BaseModel):
    identifier: str
    team_name: str
    player_name: str | None

class VetoVoteResponseData(BaseModel):
    id: int
    veto_id: int
    gambler_id: int
    affirmative: bool
    
    @classmethod
    def from_model(cls, model: VetoVote):
        return cls(
            id=model.id,
            veto_id=model.veto_id,
            gambler_id=model.gambler_id,
            affirmative=model.affirmative
        )

class PickVetoResponseData(BaseModel):
    id: int
    pick_id: int
    gambler_id: int
    approval_status: VetoApprovalStatus
    result: Optional[VetoResult]
    votes: list[VetoVoteResponseData]

    @classmethod
    def from_model(cls, model: PickVeto):
        return cls(
            id=model.id,
            pick_id=model.pick_id,
            gambler_id=model.gambler_id,
            approval_status=model.approval_status,
            result=model.result,
            votes=[VetoVoteResponseData.from_model(m) for m in model.votes]
        )
    
class PropBetTargetResponseData(BaseModel):
    id: int
    player_name: str | None
    team_name: str
    identifier: str

    @classmethod
    def from_model(cls, model: PropBetTarget):
        return cls(
            id=model.id,
            player_name=model.player_name,
            team_name=model.team_name,
            identifier=model.identifier
        )

class PickResponseData(BaseModel):
    id: int
    gambler_id: int
    line: float
    corrected_line: float | None
    direction: PropBetDirection
    sauce_factor: Optional[SauceFactor]
    result: Optional[PickResult]
    veto: Optional[PickVetoResponseData]
    prop_bet_target: PropBetTargetResponseData
    prop_type: PropBetType

    @classmethod
    def from_model(cls, model: Pick):
        return cls(
            id=model.id,
            gambler_id=model.gambler_id,
            line=model.line,
            corrected_line=model.corrected_line,
            direction=model.direction,
            sauce_factor=model.sauce_factor,
            result=model.result,
            prop_type=model.prop_type,
            veto=PickVetoResponseData.from_model(model.veto) if (model.veto and model.veto.approval_status != VetoApprovalStatus.UNDECIDED) else None,
            prop_bet_target=PropBetTargetResponseData.from_model(model.prop_bet_target)
        )

class ParlayResponseData(BaseModel):
    id: int
    owner_id: int
    slate_type: SlateType
    wager_pp: float
    competition_date: date
    picks: list[PickResponseData]
    state: ParlayState
    result: ParlayResult | None
    order: int

    @classmethod
    def from_model(cls, model: Parlay):
        picks=[PickResponseData.from_model(pick) for pick in model.picks]
        return cls(
            id=model.id,
            owner_id=model.owner_id,
            slate_type=model.slate_type,
            wager_pp=model.wager_pp,
            competition_date=model.competition_date,
            picks=picks,
            state=model.state,
            result=model.result,
            order=model.order
        )
    
async def get_required_veto_vote_count(veto: PickVeto, db: AsyncSession):
    pick = (await db.execute(
        select(Pick).where(Pick.id == veto.pick_id)
            .options(
                selectinload(Pick.parlay)
                .selectinload(Parlay.gambling_season)
                .selectinload(GamblingSeason.gamblers)
            )
    )).scalar_one()
    return (len(pick.parlay.gambling_season.gamblers) // 2)

async def update_veto_approval_status(veto: PickVeto, db: AsyncSession, require_terminal_status=False) -> bool:
    if veto.approval_status in [VetoApprovalStatus.APPROVED, VetoApprovalStatus.REJECTED, VetoApprovalStatus.UNDECIDED]:
        return False

    affirmative_votes_cnt = len([vote for vote in veto.votes if vote.affirmative])
    negative_count = len([vote for vote in veto.votes if not vote.affirmative])

    required_count = await get_required_veto_vote_count(veto, db)
    veto_approved = False
    if affirmative_votes_cnt >= required_count:
        veto.approval_status = VetoApprovalStatus.APPROVED
        await db.commit()
        veto_approved = True
    elif negative_count >= required_count:
        veto.approval_status = VetoApprovalStatus.REJECTED
        await db.commit()
    elif require_terminal_status:
        veto.approval_status = VetoApprovalStatus.UNDECIDED
        await db.commit()
    return veto_approved
    
async def get_or_create_prop_bet_target(target_request_data: PropBetTargetRequestData, db: AsyncSession) -> PropBetTarget:
    existing_target_query = await db.execute(
        select(PropBetTarget).where(PropBetTarget.identifier == target_request_data.identifier)
    )
    target = existing_target_query.scalar_one_or_none()
    if target is None:
        target = PropBetTarget(
            identifier=target_request_data.identifier,
            team_name=target_request_data.team_name,
            player_name=target_request_data.player_name
        )
        db.add(target)
        await db.commit()
        await db.refresh(target)
    return target

async def check_user_access_to_parlay(user: User, parlay_or_id: int | Parlay, db: AsyncSession):
    if isinstance(parlay_or_id, int):
        parlay_query = await db.execute(
            select(Parlay).where(Parlay.id == parlay_or_id)
                .options(
                    selectinload(Parlay.gambling_season)
                    .selectinload(GamblingSeason.gamblers)
                    .selectinload(Gambler.user)
                )
        )
        parlay = parlay_query.scalar_one()
    else:
        parlay = parlay_or_id
    if not any([gambler.user_id == user.id for gambler in parlay.gambling_season.gamblers]):
        return HTTPException(status_code=403, detail="User does not have permission to create a pick for this parlay")

    return None

async def check_gambler_access_to_season(gambler_id: int, gambling_season_id: int, db: AsyncSession):
    gambling_season = (await db.execute(
        select(GamblingSeason).where(GamblingSeason.id == gambling_season_id)
        .options(selectinload(GamblingSeason.gamblers))
    )).scalar_one()

    if not any([g.id == gambler_id for g in gambling_season.gamblers]):
        return HTTPException(status_code=403, detail="Gambler does not have access to this season!")


async def check_user_is_gambler(user: User, gambler_id: int, db: AsyncSession):
    gamblers = (await db.execute(
        select(Gambler).filter(Gambler.user_id == user.id)
    )).scalars().all()

    if not any([g.id == gambler_id for g in gamblers]):
        return HTTPException(status_code=403, detail="User cannot make a request on behalf of that gambler!")

    return None

def add_selects_to_parlay_query(select: Select[Tuple[Parlay]]):
    return select.options(
            selectinload(Parlay.picks)
            .selectinload(Pick.veto)
            .selectinload(PickVeto.votes)
        ).options(
            selectinload(Parlay.picks)
            .selectinload(Pick.prop_bet_target)
        ).options(
            selectinload(Parlay.owner)
        ).options(
            selectinload(Parlay.gambling_season)
            .selectinload(GamblingSeason.gamblers)
            .selectinload(Gambler.user)
        )

async def query_parlay_with_selects(parlay_id: int, db: AsyncSession):
    return await db.execute(
        add_selects_to_parlay_query(
            select(Parlay)
            .where(Parlay.id == parlay_id)
        )
    )

async def query_veto_with_selects(veto_id: int, db: AsyncSession):
    return await db.execute(
        select(PickVeto).where(PickVeto.id == veto_id)
        .options(
            selectinload(PickVeto.pick)
            .selectinload(Pick.parlay)
            .selectinload(Parlay.gambling_season)
            .selectinload(GamblingSeason.gamblers)
        ).options(
            selectinload(PickVeto.votes)
        )
    )

async def query_pick_with_selects(pick_id: int, db: AsyncSession):
    return await db.execute(
        select(Pick).where(Pick.id == pick_id)
        .options(
            selectinload(Pick.veto)
            .selectinload(PickVeto.votes)
        ).options(
            selectinload(Pick.prop_bet_target)
        )
    )

def map_pick_result_to_veto_result(pick_result: PickResult, all_picks_right=False) -> VetoResult:
    match pick_result:
        case PickResult.WIN:
            if all_picks_right:
                return VetoResult.BOZO
            else:
                return VetoResult.BAD
        case PickResult.LOSS:
            return VetoResult.GOOD
        case PickResult.BOZO:
            return VetoResult.BOZO_SAVER
        case PickResult.VOID:
            return VetoResult.VOID
        case PickResult.PUSH:
            return VetoResult.PUSH
        case _:
            raise ValueError(f"Could not map pick result {pick_result} to any veto result!")
