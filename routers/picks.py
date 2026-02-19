from enum import StrEnum
from typing import cast
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from database import get_db
from models import (
    PropBetDirection, 
    SauceFactor, 
    Pick, 
    User, 
    PropBetType,
    ParlayState,
    Parlay,
    PickResult,
    VetoResult,
    VetoApprovalStatus
)

from .auth import manager
from .common import (
    PickResponseData,
    PropBetTargetRequestData,
    get_or_create_prop_bet_target,
    map_pick_result_to_veto_result,
    query_pick_with_selects,
    check_user_access_to_parlay,
    check_season_in_progress,
    query_parlay_with_selects
)

router = APIRouter(
    prefix="/picks", 
    dependencies=[Depends(manager)],
    tags=["Picks"]
)

async def user_can_edit_picks(parlay: Parlay, user: User):
    return parlay.state == ParlayState.BUILDING or parlay.owner.user_id == user.id

def user_can_override_picks(parlay: Parlay, user: User):
    return parlay.owner.user_id == user.id

class CreatePickRequestData(BaseModel):
    gambler_id: int
    parlay_id: int
    target: PropBetTargetRequestData
    direction: PropBetDirection
    line: float
    sauce_factor: SauceFactor | None
    prop_type: PropBetType
    corrected_line: float | None = None

class CreatePickResponseData(BaseModel):
    pick: PickResponseData

@router.post("/", operation_id="create_pick", response_model=CreatePickResponseData)
async def create_pick(
    body: CreatePickRequestData, 
    user: User = Depends(manager), 
    db: AsyncSession = Depends(get_db)
) -> CreatePickResponseData | HTTPException:
    
    parlay = (await query_parlay_with_selects(body.parlay_id, db)).scalar_one()

    await check_season_in_progress(parlay.gambling_season_id, db)

    if not user_can_edit_picks(parlay, user):
        raise HTTPException(status_code=500, detail="After a parlay has been locked in, only the owner can change picks!")

    await check_user_access_to_parlay(user, parlay, db)

    target = await get_or_create_prop_bet_target(body.target, db)

    pick = Pick(
        gambler_id=body.gambler_id,
        prop_bet_target_id=target.id,
        parlay_id=body.parlay_id,
        line=body.line,
        direction=body.direction,
        sauce_factor=body.sauce_factor,
        prop_type=body.prop_type,
        corrected_line=body.corrected_line
    )
    db.add(pick)
    await db.commit()
    await db.refresh(pick)
    
    pick = (await query_pick_with_selects(pick.id, db)).scalar_one()
    
    return CreatePickResponseData(
        pick=PickResponseData.from_model(pick)
    )

class UpdatePickRequestData(BaseModel):
    target: PropBetTargetRequestData | None = None
    prop_type: PropBetType | None = None
    direction: PropBetDirection | None = None
    line: float | None = None
    sauce_factor: SauceFactor | None = None

class UpdatePickResponseData(CreatePickResponseData): ...

@router.patch("/{pick_id}", operation_id="update_pick", response_model=UpdatePickResponseData)
async def update_pick(
    pick_id: int,
    body: UpdatePickRequestData, 
    user: User = Depends(manager), 
    db: AsyncSession = Depends(get_db)
) -> UpdatePickResponseData | HTTPException:

    pick = (await query_pick_with_selects(pick_id, db)).scalar_one()
    parlay = (await query_parlay_with_selects(pick.parlay_id, db)).scalar_one()

    await check_season_in_progress(parlay.gambling_season_id, db)

    if not user_can_edit_picks(parlay, user):
        raise HTTPException(status_code=500, detail="After a parlay has been locked, only the owner can edit picks!")

    await check_user_access_to_parlay(user, parlay, db)

    if pick.corrected_line:
        raise HTTPException(status_code=500, detail="Cannot update a pick after an override has been applied!")

    target_id = (await get_or_create_prop_bet_target(body.target, db)).id if body.target else None
    delete_veto = False
    if target_id:
        pick.prop_bet_target_id = target_id
        delete_veto = True
    if body.direction:
        pick.direction = body.direction
        delete_veto = True
    if body.line:
        pick.line = body.line
    if body.sauce_factor:
        pick.sauce_factor = body.sauce_factor
    if body.prop_type:
        pick.prop_type = body.prop_type
        delete_veto = True
    
    if delete_veto:
        for veto in pick.vetoes:
            await db.delete(veto)
    
    await db.commit()
    await db.refresh(pick)

    pick = (await query_pick_with_selects(pick.id, db)).scalar_one()
    
    return UpdatePickResponseData(
        pick=PickResponseData.from_model(pick)
    )

class OverridePickRequestData(UpdatePickRequestData):
    delete_veto: bool = False

class OverridePickResponseData(BaseModel):
    pick: PickResponseData

@router.post("/{pick_id}/override", operation_id="apply_pick_override", response_model=OverridePickResponseData)
async def apply_pick_override(
    pick_id: int,
    body: OverridePickRequestData,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager)
) -> OverridePickResponseData | HTTPException:
    pick = (await query_pick_with_selects(pick_id, db)).scalar_one()
    parlay = (await query_parlay_with_selects(pick.parlay_id, db)).scalar_one()

    await check_season_in_progress(parlay.gambling_season_id, db)
    await check_user_access_to_parlay(user, parlay, db)

    if not user_can_override_picks(parlay, user):
            raise HTTPException(status_code=500, detail="Only the parlay owner can override picks!")
    
    if body.target:
        pick.prop_bet_target_id = (await get_or_create_prop_bet_target(body.target, db)).id
    if body.prop_type:
        pick.prop_type = body.prop_type
    if body.direction:
        pick.direction = body.direction
    if body.line:
        pick.corrected_line = body.line
    if body.sauce_factor:
        pick.sauce_factor = body.sauce_factor
    if body.delete_veto:
        for veto in pick.vetoes:
            await db.delete(veto)
    
    await db.commit()
    pick = (await query_pick_with_selects(pick.id, db)).scalar_one()
    return OverridePickResponseData(
        pick=PickResponseData.from_model(pick)
    )

class BasicPickResult(StrEnum):
    WIN = PickResult.WIN.value
    LOSS = PickResult.LOSS.value
    VOID = PickResult.VOID.value
    PUSH = PickResult.PUSH.value

class UpdatePickResultRequestData(BaseModel):
    result: BasicPickResult

class UpdatePickResultResponseData(BaseModel):
    pick: PickResponseData

@router.post("/{pick_id}/result", operation_id="update_pick_result", response_model=UpdatePickResultResponseData)
async def update_pick_result(
    pick_id: int, 
    body: UpdatePickResultRequestData, 
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager)
) -> UpdatePickResultResponseData | HTTPException:
    
    pick = (await query_pick_with_selects(pick_id, db)).scalar_one()
    parlay = (await query_parlay_with_selects(pick.parlay_id, db)).scalar_one()

    await check_season_in_progress(parlay.gambling_season_id, db)
    await check_user_access_to_parlay(user, parlay, db)

    if parlay.state == ParlayState.BUILDING:
        raise HTTPException(status_code=500, detail="Cannot only update pick results while a parlay is open!")
     
    elif parlay.state == ParlayState.CLOSED and parlay.owner.user_id != user.id:
        raise HTTPException(status_code=500, detail="Only the user can update results after a parlay has been closed!")


    mapped_result = PickResult(body.result.value)
    pick.result = mapped_result
    for veto in pick.vetoes:
        if veto.approval_status == VetoApprovalStatus.APPROVED:
            veto.result = map_pick_result_to_veto_result(mapped_result)
    
    await db.commit()
    pick = (await query_pick_with_selects(pick_id, db)).scalar_one()
    return UpdatePickResultResponseData(
        pick = PickResponseData.from_model(pick)
    )

    

    
    
