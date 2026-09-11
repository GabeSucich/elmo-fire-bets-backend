"""Actions that belong to whoever runs the league rather than to a season.

Kept out of the season routers because none of this is scoped to one: the targets a player
sweep touches are shared across every season and both kinds of pick.
"""
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models import Gambler, GamblingSeason, User
from services.espn.sync import sync_all_players

from .auth import manager

router = APIRouter(prefix="/admin", dependencies=[Depends(manager)], tags=["Admin"])


async def require_any_admin(user: User, db: AsyncSession) -> Gambler:
    """Admin of any season is enough.

    What lives here is league-wide rather than seasonal — there is no season id to check
    against — so the question is whether this person runs a league at all, not which one.
    """
    gambler = (await db.execute(
        select(Gambler)
        .where(Gambler.user_id == user.id, Gambler.is_admin.is_(True))
        .options(selectinload(Gambler.gambling_season))
        .limit(1)
    )).scalar_one_or_none()
    if gambler is None:
        raise HTTPException(status_code=403, detail="Only a season admin can do this")
    return gambler


class SyncPlayersResponseData(BaseModel):
    """Enough to tell a sweep that worked from one that quietly matched nothing.

    `ids_failed` names the players ESPN could not find, which is the list worth acting on:
    a target with no athlete id is invisible to every later refresh until its name is
    fixed.
    """
    targets_seen: int
    ids_resolved: int
    ids_failed: list[str]
    team_changes: list[str]


@router.post("/sync_players", operation_id="sync_players", response_model=SyncPlayersResponseData)
async def sync_players_endpoint(
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> SyncPlayersResponseData:
    """Resolve missing ESPN ids across every player target, then correct their teams.

    Slow in proportion to how many players the league has ever bet on, and worth running
    after an offseason rather than on a timer: a badge that is a club out of date is the
    symptom, and it only appears when somebody moves.
    """
    await require_any_admin(user, db)
    report = await sync_all_players(db)
    return SyncPlayersResponseData(
        targets_seen=report.targets_seen,
        ids_resolved=report.ids_resolved,
        ids_failed=report.ids_failed,
        team_changes=report.team_changes,
    )
