from pydantic import BaseModel
from typing import *

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Pick, User, PickVeto, Parlay, VetoApprovalStatus, VetoVote, GamblingSeason
from .auth import manager
from .common import PickVetoResponseData, VetoVoteResponseData, check_user_access_to_parlay, check_user_is_gambler, query_veto_with_selects, update_veto_approval_status, query_pick_with_selects, check_season_in_progress


router = APIRouter(
    prefix="/vetoes", 
    tags=["Vetoes"],
    dependencies=[Depends(manager)]
)

class CreatePickVetoRequestData(BaseModel):
    pick_id: int
    gambler_id: int

class CreatePickVetoResponseData(BaseModel):
    veto: PickVetoResponseData
    
@router.post("/", operation_id="create_pick_veto", response_model=CreatePickVetoResponseData)
async def create_pick_veto(
    body: CreatePickVetoRequestData, 
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager)
) -> CreatePickVetoResponseData | HTTPException:
    pick = (await db.execute(
        select(Pick).where(Pick.id == body.pick_id)
        .options(
            selectinload(Pick.vetoes)
        )
        .options(
            selectinload(Pick.parlay)
            .selectinload(Parlay.picks)
            .selectinload(Pick.vetoes)
        )
    )).scalar_one()

    await check_user_access_to_parlay(user, pick.parlay_id, db)
    await check_season_in_progress(pick.parlay.gambling_season_id, db)

    for other_pick in pick.parlay.picks:
        if len([veto for veto in other_pick.vetoes if veto.approval_status in [VetoApprovalStatus.APPROVED, VetoApprovalStatus.PENDING]]):
            if other_pick.id == pick.id:
                raise HTTPException(status_code=500, detail="That pick has already been vetoed!")
            else:
                raise HTTPException(status_code=500, detail="A pick in this parlay has already been vetoed!")

    if body.gambler_id == pick.gambler_id:
        raise HTTPException(status_code=500, detail="A gambler cannot veto their own pick!")
    veto = PickVeto(
        pick_id=body.pick_id,
        gambler_id=body.gambler_id
    )
    db.add(veto)
    await db.commit()
    await db.refresh(veto)
    return CreatePickVetoResponseData(
        veto=PickVetoResponseData(
            id=veto.id,
            pick_id=veto.pick_id,
            gambler_id=veto.gambler_id,
            approval_status=veto.approval_status,
            result=None,
            votes=[]
        )
    )
        
class SubmitVetoVoteRequestData(BaseModel):
    gambler_id: int
    affirmative: bool

class SubmitVetoVoteResponseData(BaseModel):
    vote: VetoVoteResponseData

@router.post("/{veto_id}/vote", operation_id="submit_veto_vote", response_model=SubmitVetoVoteResponseData)
async def submit_veto_vote(
    veto_id: int,
    body: SubmitVetoVoteRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db)
) -> SubmitVetoVoteResponseData | HTTPException:
    
    await check_user_is_gambler(user, body.gambler_id, db)

    veto = (await query_veto_with_selects(veto_id, db)).scalar_one()

    await check_user_access_to_parlay(user, veto.pick.parlay_id, db)
    await check_season_in_progress(veto.pick.parlay.gambling_season_id, db)

    if veto.gambler_id == body.gambler_id:
        raise HTTPException(status_code=500, detail="Gambler cannot vote on their own veto!")
    elif veto.pick.gambler_id == body.gambler_id:
        raise HTTPException(status_code=500, detail="Gambler cannot vote on a veto of ther own pick!")
    elif veto.approval_status != VetoApprovalStatus.PENDING:
        raise HTTPException(status_code=500, detail="This veto has already been approved or rejected")
    
    vote = (await db.execute(
        select(VetoVote).where(VetoVote.gambler_id == body.gambler_id, VetoVote.veto_id == veto_id)
    )).scalar_one_or_none()

    if vote:
        vote.affirmative = body.affirmative
    else:
        vote = VetoVote(
            veto_id = veto_id,
            gambler_id = body.gambler_id,
            affirmative = body.affirmative
        )
        db.add(vote)
    await db.commit()
    await db.refresh(vote)
    db.expire(veto)
    veto = (await query_veto_with_selects(veto_id, db)).scalar_one()
    await update_veto_approval_status(veto, db, require_terminal_status=False)
    
    return SubmitVetoVoteResponseData(
        vote=VetoVoteResponseData.from_model(model=vote)
    )

class DeleteVetoResponseData(BaseModel): ...

@router.delete("/{veto_id}", operation_id="delete_veto", response_model=DeleteVetoResponseData)
async def delete_veto(veto_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(manager)):
    veto = (await query_veto_with_selects(veto_id, db)).scalar_one()
    await check_season_in_progress(veto.pick.parlay.gambling_season_id, db)
    await check_user_is_gambler(user, veto.gambler_id, db)

    if veto.approval_status in [VetoApprovalStatus.APPROVED, VetoApprovalStatus.REJECTED]:
        raise HTTPException(status_code=500, detail="Cannot delete a veto after it has been voted on!")
    
    await db.delete(veto)
    await db.commit()
    return DeleteVetoResponseData()
