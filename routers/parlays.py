from curses.ascii import HT
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from database import get_db
from models.constants import ParlayResult, ParlayState, SlateType, PropBetDirection, SauceFactor
from models.db import Parlay, Pick, PickVeto, User, PropBetType

from .common import ParlayResponseData,PropBetTargetRequestData, get_or_create_prop_bet_target, check_user_access_to_parlay, check_gambler_access_to_season, check_user_is_gambler, query_parlay_with_selects, update_veto_approval_status, check_season_in_progress
from .auth import manager
from utils.parlays import finalize_parlay_results as finalize_parlay_results_helper

router = APIRouter(
    prefix="/parlays", 
    dependencies=[Depends(manager)],
    tags=["Parlays"]
)

class GetParlayResponseData(BaseModel):
    parlay: ParlayResponseData

@router.get("/{parlay_id}", operation_id="get_parlay", response_model=GetParlayResponseData)
async def get_parlay(parlay_id: int, db: AsyncSession=Depends(get_db), user: User = Depends(manager)):
    parlay = (await query_parlay_with_selects(parlay_id, db)).scalar_one()
    await check_user_access_to_parlay(user, parlay, db)

    return GetParlayResponseData(
        parlay=ParlayResponseData.from_model(parlay)
    )

class CreateParlayRequestData(BaseModel):
    gambling_season_id: int
    competition_date: date
    slate_type: SlateType
    wager_pp: float
    owner_id: int

class CreateParlayResponseData(BaseModel):
    parlay: ParlayResponseData

@router.post("/", operation_id="create_parlay", response_model=CreateParlayResponseData)
async def create_parlay(
    body: CreateParlayRequestData, 
    db: AsyncSession=Depends(get_db),
    user: User=Depends(manager)
) -> CreateParlayResponseData | HTTPException:
    await check_gambler_access_to_season(body.owner_id, body.gambling_season_id, db)
    await check_season_in_progress(body.gambling_season_id, db)

    max_order = (await db.execute(
        select(func.coalesce(func.max(Parlay.order), 0))
    )).scalar()

    if max_order is None:
        max_order = 0

    parlay = Parlay(
        gambling_season_id=body.gambling_season_id,
        competition_date=body.competition_date,
        slate_type=body.slate_type,
        owner_id=body.owner_id,
        wager_pp=body.wager_pp,
        state=ParlayState.BUILDING,
        order = max_order + 1
    )
    db.add(parlay)
    await db.commit()
    await db.refresh(parlay)
    response_parlay = (await query_parlay_with_selects(parlay.id, db)).scalar_one()
    return CreateParlayResponseData(
        parlay=ParlayResponseData.from_model(response_parlay)
    )

class UpdateParlayRequestData(BaseModel):
    parlay_id: int
    competition_date: date | None
    slate_type: SlateType | None
    owner_id: int | None
    wager_pp: float | None

class UpdateParlayResponseData(BaseModel):
    parlay: ParlayResponseData

@router.patch("/", operation_id="update_parlay", response_model=UpdateParlayResponseData)
async def update_parlay(body: UpdateParlayRequestData, db: AsyncSession = Depends(get_db)) -> UpdateParlayResponseData:
    parlay = (await query_parlay_with_selects(body.parlay_id, db)).scalar_one()
    await check_season_in_progress(parlay.gambling_season_id, db)
    updated = False
    if body.competition_date:
        parlay.competition_date = body.competition_date
        updated = True
    if body.slate_type:
        parlay.slate_type = body.slate_type
        updated = True
    if body.owner_id is not None:
        parlay.owner_id = body.owner_id
        updated = True
    if body.wager_pp is not None:
        parlay.wager_pp = body.wager_pp
        updated = True
    
    if updated:
        await db.commit()
        parlay = (await query_parlay_with_selects(body.parlay_id, db)).scalar_one()
    
    return UpdateParlayResponseData(
        parlay=ParlayResponseData.from_model(parlay)
    )

class ClaimParlayRequestData(BaseModel):
    gambler_id: int

class ClaimParlayResponseData(BaseModel): ...

@router.post("/{parlay_id}/claim", operation_id="claim_parlay", response_model=ClaimParlayResponseData)
async def claim_parlay(parlay_id: int, body: ClaimParlayRequestData, db: AsyncSession = Depends(get_db), user: User = Depends(manager)):
    await check_user_is_gambler(user, body.gambler_id, db)
    parlay = (await query_parlay_with_selects(parlay_id, db)).scalar_one()
    await check_season_in_progress(parlay.gambling_season_id, db)
    await check_user_access_to_parlay(user, parlay, db)

    parlay.owner_id = body.gambler_id
    await db.commit()
    return ClaimParlayResponseData()


class PickOverrideRequestData(BaseModel):
    pick_id: int
    prop_bet_target: PropBetTargetRequestData | None
    direction: PropBetDirection | None
    sauce_factor: SauceFactor | None
    corrected_line: float | None
    prop_type: PropBetType | None

class LockParlayRequestData(BaseModel):
    pick_overrides: dict[int, PickOverrideRequestData]

class LockParlayResponseData(BaseModel):
    parlay: ParlayResponseData

async def apply_pick_overrides(pick: Pick, override: PickOverrideRequestData, db: AsyncSession):
    change_applied = False
    if override.prop_bet_target is not None:
        target = await get_or_create_prop_bet_target(override.prop_bet_target, db)
        pick.prop_bet_target = target
        change_applied = True
    if override.direction is not None:
        pick.direction = override.direction
        change_applied = True
    if override.sauce_factor is not None:
        pick.sauce_factor = override.sauce_factor
        change_applied = True
    if override.corrected_line is not None:
        pick.corrected_line = override.corrected_line
        change_applied = True
    if override.prop_type is not None:
        pick.prop_type = override.prop_type
        change_applied = True
    
    if change_applied:
        await db.commit()
    return change_applied

class UnlockParlayRequestData(BaseModel): ...
class UnlockParlayResponseData(BaseModel):
    parlay: ParlayResponseData

@router.post("/{parlay_id}/unlock", operation_id="unlock_parlay", response_model=UnlockParlayResponseData)
async def unlock_parlay(
    parlay_id: int, 
    body: UnlockParlayRequestData,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager)
) -> UnlockParlayResponseData | HTTPException:
    parlay = (await query_parlay_with_selects(parlay_id, db)).scalar_one()
    await check_season_in_progress(parlay.gambling_season_id, db)
    if parlay.owner.user_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can unlock a parlay!")

    if parlay.state != ParlayState.OPEN:
        raise HTTPException(status_code=500, detail="Can only unlock a parlay that is OPEN!")
    
    for pick in parlay.picks:
        pick.corrected_line = None
        pick.result = None
        for veto in pick.vetoes:
            veto.result = None

    parlay.state = ParlayState.BUILDING
    await db.commit()
    db.expire_all()
    parlay = (await query_parlay_with_selects(parlay_id, db)).scalar_one()
    return UnlockParlayResponseData(
        parlay=ParlayResponseData.from_model(parlay)
    )

@router.post("/{parlay_id}/lock", operation_id="lock_parlay", response_model=LockParlayResponseData)
async def lock_parlay(
    parlay_id: int,
    body: LockParlayRequestData,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager)
) -> LockParlayResponseData | HTTPException:
    parlay = (await query_parlay_with_selects(parlay_id, db)).scalar_one()

    await check_season_in_progress(parlay.gambling_season_id, db)
    await check_user_access_to_parlay(user, parlay, db)

    if parlay.owner.user_id != user.id:
        raise HTTPException(status_code=500, detail="User cannot change parlay state if they are not the owner!")
    
    if parlay.state != ParlayState.BUILDING:
        raise HTTPException(status_code=500, detail="Cannot lock a parlay that is not in the BUILDING state!")
    
    for pick in parlay.picks:
        pick_override_data = body.pick_overrides.get(pick.id)
        if pick_override_data is not None and pick_override_data.pick_id == pick.id:
            await apply_pick_overrides(pick, pick_override_data, db)
        
        for veto in pick.vetoes:
            await update_veto_approval_status(veto, db, require_terminal_status=True)
        
    parlay.state = ParlayState.OPEN
    await db.commit()

    refreshed_parlay = (await query_parlay_with_selects(parlay_id, db)).scalar_one()
    return LockParlayResponseData(
        parlay=ParlayResponseData.from_model(refreshed_parlay)
    )

class FinalizeParlayResultsRequestData(BaseModel): ...
class FinalizeParlayResultsResponseData(BaseModel):
    parlay: ParlayResponseData
    possible_results: list[ParlayResult]
        
@router.post("/{parlay_id}/finalize_results", operation_id="finalize_parlay_result", response_model=FinalizeParlayResultsResponseData)
async def finalize_parlay_results(
    parlay_id: int,
    body: FinalizeParlayResultsRequestData,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager)
) -> FinalizeParlayResultsResponseData | HTTPException:
    parlay = (await query_parlay_with_selects(parlay_id, db)).scalar_one()

    await check_season_in_progress(parlay.gambling_season_id, db)
    await check_user_access_to_parlay(user, parlay, db)

    if parlay.state == ParlayState.BUILDING:
        raise HTTPException(status_code=500, detail="Cannot finalize the results of a parlay that is still being built!")

    if parlay.owner.user_id != user.id:
        raise HTTPException(status_code=403, detail="Only the parlay owner can finalize its results!")
    
    updated_parlay, possible_results = await finalize_parlay_results_helper(parlay, db)

    return FinalizeParlayResultsResponseData(
        parlay=ParlayResponseData.from_model(updated_parlay),
        possible_results=possible_results
    )


class CloseParlayRequestData(BaseModel):
    parlay_result: ParlayResult

class CloseParlayResponseData(BaseModel):
    parlay: ParlayResponseData

@router.post("/{parlay_id}/close", operation_id="close_parlay", response_model=CloseParlayResponseData)
async def close_parlay(
    parlay_id: int,
    body: CloseParlayRequestData,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager)
) -> CloseParlayResponseData | HTTPException:
    
    parlay = (await query_parlay_with_selects(parlay_id, db)).scalar_one()
    await check_season_in_progress(parlay.gambling_season_id, db)
    if parlay.owner.user_id != user.id:
        raise HTTPException(status_code=403, detail="Only a parlay owner can close a parlay!")

    if parlay.state != ParlayState.OPEN:
        raise HTTPException(status_code=500, detail="Can only close a parlay if it is currently OPEN!")
    
    updated_parlay, possible_results = await finalize_parlay_results_helper(parlay, db)
    if body.parlay_result not in possible_results:
        raise HTTPException(status_code=500, detail=f"Result {body.parlay_result} is not one of {[possible_results]}!")
    
    parlay.result = body.parlay_result
    parlay.state = ParlayState.CLOSED
    await db.commit()
    db.expire_all()

    parlay = (await query_parlay_with_selects(parlay_id, db)).scalar_one()
    return CloseParlayResponseData(
        parlay=ParlayResponseData.from_model(parlay)
    )

class ReopenParlayRequestData(BaseModel): ...

class ReopenParlayResponseData(BaseModel):
    parlay: ParlayResponseData

@router.post("/{parlay_id}/reopen", operation_id="reopen_parlay", response_model=ReopenParlayResponseData)
async def reopen_parlay(
    parlay_id: int,
    body: ReopenParlayRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db)
) -> ReopenParlayResponseData | HTTPException:
    parlay = (await query_parlay_with_selects(parlay_id, db)).scalar_one()
    await check_season_in_progress(parlay.gambling_season_id, db)
    if parlay.owner.user_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can reopen a parlay!")

    if parlay.state != ParlayState.CLOSED:
        raise HTTPException(status_code=500, detail="Can only reopen a parlay that is CLOSED!")
    
    parlay.result = None

    parlay.state = ParlayState.OPEN
    await db.commit()
    db.expire_all()
    parlay = (await query_parlay_with_selects(parlay_id, db)).scalar_one()
    return ReopenParlayResponseData(
        parlay=ParlayResponseData.from_model(parlay)
    )

class DeleteParlayResponseData(BaseModel):
    success: bool

@router.delete("/{parlay_id}", operation_id="delete_parlay", response_model=DeleteParlayResponseData)
async def delete_parlay(
    parlay_id: int,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db)
) -> DeleteParlayResponseData | HTTPException:
    parlay = (await query_parlay_with_selects(parlay_id, db)).scalar_one()

    await check_season_in_progress(parlay.gambling_season_id, db)
    await check_user_access_to_parlay(user, parlay, db)

    if parlay.state != ParlayState.BUILDING:
        raise HTTPException(status_code=500, detail="Cannot delete a parlay that is not BUILDING!")
    
    await db.delete(parlay)
    await db.commit()
    return DeleteParlayResponseData(
        success=True
    )

class SwapParlayOrderRequestData(BaseModel):
    parlay_id_1: int
    parlay_id_2: int

class SwapParlayOrderResponseData(BaseModel):
    success: bool

@router.post("/swap_order", operation_id="swap_parlay_order", response_model=SwapParlayOrderResponseData)
async def swap_parlay_order(
    body: SwapParlayOrderRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db)
) -> SwapParlayOrderResponseData | HTTPException:
    parlay_1 = (await query_parlay_with_selects(body.parlay_id_1, db)).scalar_one()
    parlay_2 = (await query_parlay_with_selects(body.parlay_id_2, db)).scalar_one()

    await check_season_in_progress(parlay_1.gambling_season_id, db)
    await check_user_access_to_parlay(user, parlay_1, db)
    await check_user_access_to_parlay(user, parlay_2, db)
    
    if parlay_1.gambling_season_id != parlay_2.gambling_season_id:
        raise HTTPException(status_code=500, detail="Cannot swap order of parlays from different gambling seasons")
    
    parlay_1.order, parlay_2.order = parlay_2.order, parlay_1.order
    await db.commit()
    return SwapParlayOrderResponseData(
        success=True
    )