"""Emoji reactions and reply threads on a pick.

A second router on the /picks prefix rather than more of picks.py, which is about the bet
itself — what it is, what it was overridden to, and how it settled. This is the noise the
league makes around it.

The comment half is deliberately shape-for-shape with routers/feedback.py, so the one
thread component on the client can render either without knowing which it is holding.
"""
import datetime
from typing import *

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import (
    Gambler,
    ParlayState,
    Pick,
    PickComment,
    PickReaction,
    User,
    PICK_REACTION_EMOJI,
)

from .auth import manager
from .common import (
    PickReactionResponseData,
    PickResponseData,
    check_season_in_progress,
    query_pick_with_selects,
    summarize_reactions,
)

router = APIRouter(
    prefix="/picks",
    dependencies=[Depends(manager)],
    tags=["PickSocial"],
)


def author_name(gambler: Gambler | None) -> str:
    return gambler.user.first_name if gambler and gambler.user else "Unknown"


async def load_pick_with_parlay(pick_id: int, db: AsyncSession) -> Pick:
    """The pick, with the parlay that answers who may touch it and whether it is still open."""
    pick = (await db.execute(
        select(Pick).where(Pick.id == pick_id)
        .options(selectinload(Pick.parlay))
        .options(selectinload(Pick.reactions))
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if pick is None:
        raise HTTPException(status_code=404, detail="That pick no longer exists")
    return pick


async def viewer_gambler_for_pick(pick: Pick, user: User, db: AsyncSession) -> Gambler:
    """Who the reader is within the season this pick belongs to.

    The same move feedback makes: everything about authorship is expressed as that season's
    gambler rather than as the account, so a user in two seasons cannot act across them.
    """
    gambler = (await db.execute(
        select(Gambler).where(
            Gambler.gambling_season_id == pick.parlay.gambling_season_id,
            Gambler.user_id == user.id,
        ).options(selectinload(Gambler.user))
    )).scalar_one_or_none()
    if gambler is None:
        raise HTTPException(status_code=403, detail="You are not part of this season")
    return gambler


def require_pick_writable(pick: Pick) -> None:
    """A closed parlay is a record, and records do not move.

    Reads stay open in every state, so whatever a pick collected while it was live keeps
    showing once it is settled — it just stops taking anything new.
    """
    if pick.parlay.state is ParlayState.CLOSED:
        raise HTTPException(
            status_code=409,
            detail="This parlay is closed and can no longer be reacted to or replied to",
        )


async def prepare_write(pick_id: int, user: User, db: AsyncSession) -> Tuple[Pick, Gambler]:
    """Everything the four write paths check, in the order they check it."""
    pick = await load_pick_with_parlay(pick_id, db)
    viewer = await viewer_gambler_for_pick(pick, user, db)
    await check_season_in_progress(pick.parlay.gambling_season_id, db)
    require_pick_writable(pick)
    return pick, viewer


class PickCommentResponseData(BaseModel):
    """Field for field FeedbackCommentResponseData, on a different parent."""
    id: int
    pick_id: int
    gambler_id: int
    author_name: str
    comment: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    viewer_is_author: bool


class ListPickCommentsResponseData(BaseModel):
    comments: list[PickCommentResponseData]
    # Always the whole current set, never filtered by `after`. A reaction can be taken
    # back, and no cursor over insertions can ever show a removal — so the drawer's poll
    # replaces this wholesale while it appends replies incrementally.
    reactions: list[PickReactionResponseData]


class PickResponse(BaseModel):
    pick: PickResponseData


class PickCommentResponse(BaseModel):
    comment: PickCommentResponseData


class PickCommentRequestData(BaseModel):
    comment: str


class ReactionRequestData(BaseModel):
    """The emoji tapped. Sending one you already left takes it back."""
    emoji: str


@router.put("/{pick_id}/reactions", operation_id="react_to_pick", response_model=PickResponse)
async def react_to_pick(
    pick_id: int,
    body: ReactionRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> PickResponse:
    """Toggle one emoji on one pick.

    Unlike a feedback vote there is no single row per gambler to overwrite: several
    different emoji may stand at once, so this only ever adds or removes the one sent.

    Returns the whole pick so the client patches one object and the chips on the card and
    in the open drawer — the same array — move together.
    """
    pick, viewer = await prepare_write(pick_id, user, db)

    if body.emoji not in PICK_REACTION_EMOJI:
        raise HTTPException(status_code=400, detail="That is not one of the reactions you can leave")

    existing = next(
        (r for r in pick.reactions if r.gambler_id == viewer.id and r.emoji == body.emoji), None
    )
    if existing is None:
        db.add(PickReaction(pick_id=pick.id, gambler_id=viewer.id, emoji=body.emoji))
    else:
        await db.delete(existing)
    await db.commit()

    return PickResponse(pick=PickResponseData.from_model(
        (await query_pick_with_selects(pick_id, db)).scalar_one()
    ))


@router.get("/{pick_id}/comments", operation_id="list_pick_comments", response_model=ListPickCommentsResponseData)
async def list_pick_comments(
    pick_id: int,
    after: datetime.datetime | None = Query(
        None,
        description="Only replies created after this. Send back a created_at from a previous "
                    "response verbatim; used by the open drawer to poll for new replies.",
    ),
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> ListPickCommentsResponseData:
    """The thread, in full or from a cursor.

    Readable whatever the parlay's state: a closed pick's argument is part of its record.
    """
    pick = await load_pick_with_parlay(pick_id, db)
    viewer = await viewer_gambler_for_pick(pick, user, db)

    query = (
        select(PickComment)
        .where(PickComment.pick_id == pick_id, PickComment.archived_at.is_(None))
        .options(selectinload(PickComment.gambler).selectinload(Gambler.user))
        # Oldest first: a thread reads top to bottom, and the reply box sits at the bottom,
        # so a new reply appears directly above where it was typed.
        .order_by(PickComment.created_at.asc())
        .execution_options(populate_existing=True)
    )
    if after is not None:
        # Timestamps are stored naive UTC, so an offset-aware value from the client is
        # converted and flattened before it reaches the column. Comparing an aware value
        # against a naive one silently asks about the wrong instant.
        if after.tzinfo is not None:
            after = after.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        query = query.where(PickComment.created_at > after)

    comments = list((await db.execute(query)).scalars())

    return ListPickCommentsResponseData(
        comments=[comment_response(c, viewer) for c in comments],
        reactions=summarize_reactions(pick.reactions),
    )


def comment_response(comment: PickComment, viewer: Gambler) -> PickCommentResponseData:
    return PickCommentResponseData(
        id=comment.id,
        pick_id=comment.pick_id,
        gambler_id=comment.gambler_id,
        author_name=author_name(comment.gambler),
        comment=comment.comment,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        viewer_is_author=comment.gambler_id == viewer.id,
    )


@router.post("/{pick_id}/comments", operation_id="create_pick_comment", response_model=PickCommentResponse)
async def create_pick_comment(
    pick_id: int,
    body: PickCommentRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> PickCommentResponse:
    _, viewer = await prepare_write(pick_id, user, db)

    text = body.comment.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Say something before replying")

    comment = PickComment(pick_id=pick_id, gambler_id=viewer.id, comment=text)
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    return PickCommentResponse(comment=PickCommentResponseData(
        id=comment.id,
        pick_id=comment.pick_id,
        gambler_id=comment.gambler_id,
        author_name=author_name(viewer),
        comment=comment.comment,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        viewer_is_author=True,
    ))


# Registered after the /{pick_id}/… routes above. "/comments/5" cannot be mistaken for
# one of them — that would need a literal second segment — but keeping the literal prefix
# last is the habit that stops a future /{pick_id}/{something} from swallowing it.
async def load_own_comment(comment_id: int, user: User, db: AsyncSession) -> Tuple[PickComment, Gambler]:
    comment = (await db.execute(
        select(PickComment).where(PickComment.id == comment_id)
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if comment is None or comment.archived_at is not None:
        raise HTTPException(status_code=404, detail="That comment no longer exists")

    _, viewer = await prepare_write(comment.pick_id, user, db)
    if comment.gambler_id != viewer.id:
        raise HTTPException(status_code=403, detail="You can only change your own comments")
    return comment, viewer


@router.put("/comments/{comment_id}", operation_id="update_pick_comment", response_model=PickCommentResponse)
async def update_pick_comment(
    comment_id: int,
    body: PickCommentRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> PickCommentResponse:
    comment, viewer = await load_own_comment(comment_id, user, db)

    text = body.comment.strip()
    if not text:
        raise HTTPException(status_code=400, detail="A comment cannot be empty")

    comment.comment = text
    await db.commit()
    await db.refresh(comment)

    return PickCommentResponse(comment=PickCommentResponseData(
        id=comment.id,
        pick_id=comment.pick_id,
        gambler_id=comment.gambler_id,
        author_name=author_name(viewer),
        comment=comment.comment,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        viewer_is_author=True,
    ))


@router.delete("/comments/{comment_id}", operation_id="delete_pick_comment")
async def delete_pick_comment(
    comment_id: int,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    comment, _ = await load_own_comment(comment_id, user, db)
    # Archived rather than removed, so a thread does not close over the gap.
    comment.archived_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    await db.commit()
    return {"deleted": comment_id}
