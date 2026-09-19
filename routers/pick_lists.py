"""Lists a season keeps about picks — today the ban list, and built so it is not the only one.

Nothing below asks which kind of list it is holding. A list is a row, its entries are rows
against it, and the one piece of behaviour that could differ between types — what counts as
a bet being "on" a list — lives in PickListItem.matches. Adding a second type is a migration
and an icon on the client.

The lists themselves are never created by hand: a season gets whatever DEFAULT_PICK_LISTS
says it should have, the first time anybody reads them.
"""
from typing import *

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import (
    Gambler,
    GamblingSeason,
    GamblingSeasonState,
    PickList,
    PickListItem,
    PickListType,
    PropBetDirection,
    PropBetType,
    User,
)

from .auth import manager
from .common import (
    PropBetTargetRequestData,
    PropBetTargetResponseData,
    get_or_create_prop_bet_target,
)

router = APIRouter(
    prefix="/pick_lists",
    dependencies=[Depends(manager)],
    tags=["PickLists"],
)


# Every list a season should have, and what to call it. Seasons are only ever born in
# seed_season.py, so rather than a creation hook and a backfill migration for the seasons
# that already exist, the read path makes good whatever is missing.
DEFAULT_PICK_LISTS: list[tuple[PickListType, str]] = [
    (PickListType.BAN, "Ban List"),
]


class PickListItemResponseData(BaseModel):
    id: int
    pick_list_id: int
    gambler_id: int
    prop_bet_target_id: int
    # The whole target, like SeasonPickResponseData carries: the editor repopulates its
    # selection from this rather than being able only to print a name.
    prop_bet_target: PropBetTargetResponseData
    # Null on both means the player outright, either market, either side.
    prop_type: PropBetType | None
    direction: PropBetDirection | None

    @classmethod
    def from_model(cls, model: PickListItem):
        return cls(
            id=model.id,
            pick_list_id=model.pick_list_id,
            gambler_id=model.gambler_id,
            prop_bet_target_id=model.prop_bet_target_id,
            prop_bet_target=PropBetTargetResponseData.from_model(model.prop_bet_target),
            prop_type=model.prop_type,
            direction=model.direction,
        )


class PickListResponseData(BaseModel):
    id: int
    gambling_season_id: int
    list_type: PickListType
    display_name: str
    # Everybody's, not just the reader's. The screen shows the whole league side by side,
    # and who may edit what is decided by gambler_id rather than by what was sent.
    items: list[PickListItemResponseData]

    @classmethod
    def from_model(cls, model: PickList):
        return cls(
            id=model.id,
            gambling_season_id=model.gambling_season_id,
            list_type=model.list_type,
            display_name=model.display_name,
            items=[PickListItemResponseData.from_model(i) for i in model.items],
        )


class ListPickListsResponseData(BaseModel):
    pick_lists: list[PickListResponseData]
    # Whether writes are accepted at all. A finished season stays readable and stops taking
    # entries, and the client should not have to re-derive that rule.
    editable: bool


class PickListItemRequestData(BaseModel):
    gambler_id: int
    target: PropBetTargetRequestData
    prop_type: PropBetType | None = None
    direction: PropBetDirection | None = None


class PickListItemResponse(BaseModel):
    item: PickListItemResponseData


class DeletePickListItemResponseData(BaseModel):
    success: bool


async def load_season(season_id: int, db: AsyncSession) -> GamblingSeason:
    season = (await db.execute(
        select(GamblingSeason)
        .where(GamblingSeason.id == season_id)
        .options(selectinload(GamblingSeason.gamblers))
    )).scalar_one_or_none()
    if season is None:
        raise HTTPException(status_code=404, detail="Season not found")
    return season


def gambler_for_user(season: GamblingSeason, user: User) -> Gambler:
    for gambler in season.gamblers:
        if gambler.user_id == user.id:
            return gambler
    raise HTTPException(status_code=403, detail="You are not part of this season")


def require_can_manage(season: GamblingSeason, user: User, gambler_id: int) -> Gambler:
    """Your list is yours.

    No admin override, unlike season picks: there is nothing to lock in and nothing to
    referee, and somebody else deciding who you are allowed to hate is the one thing this
    feature should never do.
    """
    if season.state == GamblingSeasonState.COMPLETE:
        raise HTTPException(status_code=409, detail="This season is complete and can no longer be edited")
    viewer = gambler_for_user(season, user)
    if viewer.id != gambler_id:
        raise HTTPException(status_code=403, detail="You can only manage your own list entries")
    return viewer


async def ensure_default_pick_lists(season_id: int, db: AsyncSession) -> list[PickList]:
    """The season's lists, creating any that do not exist yet.

    Idempotent, and cheap in the normal case: after the first read it is one query that
    finds everything already there. The unique constraint on (season, type) is what makes
    two people opening the screen at once harmless.
    """
    lists = list((await db.execute(
        select(PickList)
        .where(PickList.gambling_season_id == season_id)
        .options(
            selectinload(PickList.items)
            .joinedload(PickListItem.prop_bet_target)
        )
        .order_by(PickList.id)
    )).unique().scalars())

    missing = [(t, name) for t, name in DEFAULT_PICK_LISTS if not any(l.list_type == t for l in lists)]
    if not missing:
        return lists

    for list_type, display_name in missing:
        db.add(PickList(
            gambling_season_id=season_id,
            list_type=list_type,
            display_name=display_name,
        ))
    await db.commit()
    return await ensure_default_pick_lists(season_id, db)


async def query_item(item_id: int, db: AsyncSession) -> PickListItem:
    item = (await db.execute(
        select(PickListItem)
        .where(PickListItem.id == item_id)
        .options(
            joinedload(PickListItem.prop_bet_target),
            joinedload(PickListItem.pick_list),
        )
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="That list entry no longer exists")
    return item


async def load_list(pick_list_id: int, db: AsyncSession) -> PickList:
    pick_list = (await db.execute(
        select(PickList).where(PickList.id == pick_list_id)
    )).scalar_one_or_none()
    if pick_list is None:
        raise HTTPException(status_code=404, detail="List not found")
    return pick_list


async def check_not_duplicate(
    pick_list_id: int,
    gambler_id: int,
    prop_bet_target_id: int,
    prop_type: PropBetType | None,
    direction: PropBetDirection | None,
    db: AsyncSession,
    ignoring_item_id: int | None = None,
) -> None:
    """Refuse an entry somebody already has, exactly.

    Only an exact repeat: "Jamarr Chase" alongside "Jamarr Chase / Rec Yards / Over" is a
    redundancy rather than a mistake, and both are kept — the drawer picks the narrower one
    when it has to name a reason.
    """
    # `== None` would compile to `= NULL`, which is never true, so the broad entries — the
    # ones most likely to be added twice — have to be matched with IS NULL.
    matches_prop_type = (
        PickListItem.prop_type.is_(None) if prop_type is None else PickListItem.prop_type == prop_type
    )
    matches_direction = (
        PickListItem.direction.is_(None) if direction is None else PickListItem.direction == direction
    )
    existing = (await db.execute(
        select(PickListItem).where(
            PickListItem.pick_list_id == pick_list_id,
            PickListItem.gambler_id == gambler_id,
            PickListItem.prop_bet_target_id == prop_bet_target_id,
            matches_prop_type,
            matches_direction,
        )
    )).scalars().all()
    if any(item.id != ignoring_item_id for item in existing):
        raise HTTPException(status_code=409, detail="That is already on your list")


@router.get("/season/{season_id}", operation_id="list_pick_lists", response_model=ListPickListsResponseData)
async def list_pick_lists(
    season_id: int,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> ListPickListsResponseData:
    season = await load_season(season_id, db)
    gambler_for_user(season, user)
    lists = await ensure_default_pick_lists(season_id, db)

    return ListPickListsResponseData(
        pick_lists=[PickListResponseData.from_model(l) for l in lists],
        editable=season.state != GamblingSeasonState.COMPLETE,
    )


@router.post("/{pick_list_id}/items", operation_id="create_pick_list_item", response_model=PickListItemResponse)
async def create_pick_list_item(
    pick_list_id: int,
    body: PickListItemRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> PickListItemResponse:
    pick_list = await load_list(pick_list_id, db)
    season = await load_season(pick_list.gambling_season_id, db)
    require_can_manage(season, user, body.gambler_id)

    target = await get_or_create_prop_bet_target(body.target, db)
    await check_not_duplicate(pick_list_id, body.gambler_id, target.id, body.prop_type, body.direction, db)

    item = PickListItem(
        pick_list_id=pick_list_id,
        gambler_id=body.gambler_id,
        prop_bet_target_id=target.id,
        prop_type=body.prop_type,
        direction=body.direction,
    )
    db.add(item)
    await db.commit()

    return PickListItemResponse(item=PickListItemResponseData.from_model(await query_item(item.id, db)))


@router.put("/items/{item_id}", operation_id="update_pick_list_item", response_model=PickListItemResponse)
async def update_pick_list_item(
    item_id: int,
    body: PickListItemRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> PickListItemResponse:
    item = await query_item(item_id, db)
    season = await load_season(item.pick_list.gambling_season_id, db)
    # Checked against the entry's owner rather than the body's, so re-pointing somebody
    # else's entry at your own gambler id is not a way in.
    require_can_manage(season, user, item.gambler_id)

    target = await get_or_create_prop_bet_target(body.target, db)
    await check_not_duplicate(
        item.pick_list_id, item.gambler_id, target.id, body.prop_type, body.direction, db,
        ignoring_item_id=item.id,
    )

    item.prop_bet_target_id = target.id
    item.prop_type = body.prop_type
    item.direction = body.direction
    await db.commit()

    return PickListItemResponse(item=PickListItemResponseData.from_model(await query_item(item.id, db)))


@router.delete("/items/{item_id}", operation_id="delete_pick_list_item", response_model=DeletePickListItemResponseData)
async def delete_pick_list_item(
    item_id: int,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> DeletePickListItemResponseData:
    item = await query_item(item_id, db)
    season = await load_season(item.pick_list.gambling_season_id, db)
    require_can_manage(season, user, item.gambler_id)

    await db.delete(item)
    await db.commit()
    return DeletePickListItemResponseData(success=True)
