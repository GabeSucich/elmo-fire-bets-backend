import datetime
from typing import *

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Feedback, FeedbackComment, FeedbackRating, FeedbackStatus, Gambler, GamblingSeason, User

from services.feedback_titles import MAX_TITLE_LENGTH, generate_title

from .auth import manager

router = APIRouter(
    prefix="/feedback",
    dependencies=[Depends(manager)],
    tags=["Feedback"],
)


async def viewer_gambler(season_id: int, user: User, db: AsyncSession) -> Gambler:
    """Who the reader is within this season.

    Feedback belongs to a season, so everything about it — authorship, voting, the right
    to resolve — is expressed as that season's gambler rather than as the account.
    """
    gambler = (await db.execute(
        select(Gambler).where(
            Gambler.gambling_season_id == season_id, Gambler.user_id == user.id
        ).options(selectinload(Gambler.user))
    )).scalar_one_or_none()
    if gambler is None:
        raise HTTPException(status_code=403, detail="You are not part of this season")
    return gambler


class FeedbackResponseData(BaseModel):
    id: int
    gambler_id: int
    author_name: str
    title: str
    comment: str
    status: FeedbackStatus
    created_at: datetime.datetime
    # Upvotes less downvotes. The two tallies are never shown apart, and the backlog is
    # ranked on the net, so only the net is sent.
    score: int
    comment_count: int
    # -1, 0 or +1: how the person reading it voted, so the control can show its state
    # without shipping every rating row.
    viewer_vote: int
    viewer_is_author: bool


class ListFeedbackResponseData(BaseModel):
    feedback: list[FeedbackResponseData]
    viewer_is_admin: bool


class FeedbackCommentResponseData(BaseModel):
    id: int
    feedback_id: int
    gambler_id: int
    author_name: str
    comment: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    viewer_is_author: bool


class ListFeedbackCommentsResponseData(BaseModel):
    comments: list[FeedbackCommentResponseData]


class FeedbackVotersResponseData(BaseModel):
    """Who voted, by first name.

    Kept off the list response: it is a handful of names per suggestion and the cards show
    only the total, so fetching them for every row to render none of them would be waste.
    """
    up: list[str]
    down: list[str]


class FeedbackRequestData(BaseModel):
    comment: str


class UpdateFeedbackRequestData(BaseModel):
    title: str | None = None
    comment: str | None = None


class FeedbackResponse(BaseModel):
    feedback: FeedbackResponseData


class CommentRequestData(BaseModel):
    comment: str


class VoteRequestData(BaseModel):
    """The direction tapped. Sending the same one again takes the vote back."""
    value: Literal[-1, 1]


class CommentResponse(BaseModel):
    comment: FeedbackCommentResponseData


def author_name(gambler: Gambler | None) -> str:
    return gambler.user.first_name if gambler and gambler.user else "Unknown"


def require_open(feedback: Feedback) -> None:
    """Settled feedback is read-only, whether it was resolved or retired.

    Those tabs are a record of what has been answered; letting votes and replies keep
    landing on them would make that record move under you.
    """
    if feedback.status is not FeedbackStatus.OPEN:
        raise HTTPException(
            status_code=409,
            detail=f"This feedback has been {feedback.status.value.lower()} and can no longer be changed",
        )


def require_not_author(feedback: Feedback, viewer: Gambler) -> None:
    """You cannot vote for your own suggestion.

    Everyone would vote for their own, so the votes would say nothing beyond who bothered
    to raise something.
    """
    if feedback.gambler_id == viewer.id:
        raise HTTPException(status_code=403, detail="You cannot vote on your own suggestion")


async def load_feedback(feedback_id: int, db: AsyncSession) -> Feedback:
    feedback = (await db.execute(
        select(Feedback).where(Feedback.id == feedback_id)
        .options(selectinload(Feedback.gambler).selectinload(Gambler.user))
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if feedback is None or feedback.archived_at is not None:
        raise HTTPException(status_code=404, detail="That feedback no longer exists")
    return feedback


async def feedback_response(feedback: Feedback, viewer: Gambler, db: AsyncSession) -> FeedbackResponseData:
    score = (await db.execute(
        select(func.coalesce(func.sum(FeedbackRating.value), 0)).where(
            FeedbackRating.feedback_id == feedback.id
        )
    )).scalar_one()
    comment_count = (await db.execute(
        select(func.count()).select_from(FeedbackComment).where(
            FeedbackComment.feedback_id == feedback.id, FeedbackComment.archived_at.is_(None)
        )
    )).scalar_one()
    viewer_vote = (await db.execute(
        select(FeedbackRating.value).where(
            FeedbackRating.feedback_id == feedback.id, FeedbackRating.gambler_id == viewer.id
        )
    )).scalar_one_or_none() or 0

    return FeedbackResponseData(
        id=feedback.id,
        gambler_id=feedback.gambler_id,
        author_name=author_name(feedback.gambler),
        title=feedback.title,
        comment=feedback.comment,
        status=feedback.status,
        created_at=feedback.created_at,
        score=score,
        comment_count=comment_count,
        viewer_vote=viewer_vote,
        viewer_is_author=feedback.gambler_id == viewer.id,
    )


@router.get("/season/{season_id}", operation_id="list_feedback", response_model=ListFeedbackResponseData)
async def list_feedback(
    season_id: int,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> ListFeedbackResponseData:
    """Everything at once, open and resolved.

    There will never be many, and the client splits them by tab and by age. Comments are
    the expensive part and are left until a suggestion is opened.
    """
    viewer = await viewer_gambler(season_id, user, db)

    score = (
        select(FeedbackRating.feedback_id, func.sum(FeedbackRating.value).label("score"))
        .group_by(FeedbackRating.feedback_id)
        .subquery()
    )
    comment_count = (
        select(FeedbackComment.feedback_id, func.count().label("comments"))
        .where(FeedbackComment.archived_at.is_(None))
        .group_by(FeedbackComment.feedback_id)
        .subquery()
    )
    viewer_rating = (
        select(FeedbackRating.feedback_id, FeedbackRating.value)
        .where(FeedbackRating.gambler_id == viewer.id)
        .subquery()
    )

    rows = (await db.execute(
        select(
            Feedback,
            func.coalesce(score.c.score, 0),
            func.coalesce(comment_count.c.comments, 0),
            func.coalesce(viewer_rating.c.value, 0),
        )
        .outerjoin(score, score.c.feedback_id == Feedback.id)
        .outerjoin(comment_count, comment_count.c.feedback_id == Feedback.id)
        .outerjoin(viewer_rating, viewer_rating.c.feedback_id == Feedback.id)
        .join(Gambler, Gambler.id == Feedback.gambler_id)
        .where(Feedback.archived_at.is_(None), Gambler.gambling_season_id == season_id)
        .options(selectinload(Feedback.gambler).selectinload(Gambler.user))
        # Most wanted first, and the newest of an equally wanted pair ahead of the rest.
        .order_by(func.coalesce(score.c.score, 0).desc(), Feedback.created_at.desc())
    )).all()

    return ListFeedbackResponseData(
        feedback=[
            FeedbackResponseData(
                id=f.id,
                gambler_id=f.gambler_id,
                author_name=author_name(f.gambler),
                title=f.title,
                comment=f.comment,
                status=f.status,
                created_at=f.created_at,
                score=votes,
                comment_count=comments,
                viewer_vote=viewer_voted,
                viewer_is_author=f.gambler_id == viewer.id,
            )
            for f, votes, comments, viewer_voted in rows
        ],
        viewer_is_admin=viewer.is_admin,
    )


@router.post("/season/{season_id}", operation_id="create_feedback", response_model=FeedbackResponse)
async def create_feedback(
    season_id: int,
    body: FeedbackRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    viewer = await viewer_gambler(season_id, user, db)

    comment = body.comment.strip()
    if not comment:
        raise HTTPException(status_code=400, detail="Say something before submitting")

    # Titled from the description so the list is scannable. Never fails the submission:
    # a fallback title is derived locally if the model is slow or unavailable.
    title = await generate_title(comment)

    feedback = Feedback(gambler_id=viewer.id, title=title, comment=comment)
    db.add(feedback)
    await db.commit()

    return FeedbackResponse(feedback=await feedback_response(await load_feedback(feedback.id, db), viewer, db))


@router.put("/{feedback_id}", operation_id="update_feedback", response_model=FeedbackResponse)
async def update_feedback(
    feedback_id: int,
    body: UpdateFeedbackRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    feedback = await load_feedback(feedback_id, db)
    viewer = await viewer_gambler(feedback.gambler.gambling_season_id, user, db)
    require_open(feedback)
    if feedback.gambler_id != viewer.id:
        raise HTTPException(status_code=403, detail="You can only edit your own feedback")

    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="A title cannot be empty")
        if len(title) > MAX_TITLE_LENGTH:
            raise HTTPException(status_code=400, detail=f"Keep the title under {MAX_TITLE_LENGTH} characters")
        feedback.title = title

    if body.comment is not None:
        comment = body.comment.strip()
        if not comment:
            raise HTTPException(status_code=400, detail="A description cannot be empty")
        feedback.comment = comment

    await db.commit()
    return FeedbackResponse(feedback=await feedback_response(await load_feedback(feedback_id, db), viewer, db))


@router.delete("/{feedback_id}", operation_id="delete_feedback")
async def delete_feedback(
    feedback_id: int,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    feedback = await load_feedback(feedback_id, db)
    viewer = await viewer_gambler(feedback.gambler.gambling_season_id, user, db)
    require_open(feedback)
    if feedback.gambler_id != viewer.id:
        raise HTTPException(status_code=403, detail="You can only delete your own feedback")

    # Archived rather than deleted, so its replies and votes are not orphaned.
    feedback.archived_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    await db.commit()
    return {"deleted": feedback_id}


class StatusRequestData(BaseModel):
    status: FeedbackStatus


@router.put("/{feedback_id}/status", operation_id="set_feedback_status", response_model=FeedbackResponse)
async def set_feedback_status(
    feedback_id: int,
    body: StatusRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    """Resolve, retire, or put one back into the open list.

    Deliberately not guarded by require_open: reopening is the whole point of being able
    to change a status, and an admin who retires something by mistake needs a way back.
    """
    feedback = await load_feedback(feedback_id, db)
    viewer = await viewer_gambler(feedback.gambler.gambling_season_id, user, db)
    if not viewer.is_admin:
        raise HTTPException(status_code=403, detail="Only an admin can change a suggestion's status")

    feedback.status = body.status
    await db.commit()

    return FeedbackResponse(feedback=await feedback_response(await load_feedback(feedback_id, db), viewer, db))


@router.put("/{feedback_id}/vote", operation_id="vote_on_feedback", response_model=FeedbackResponse)
async def vote_on_feedback(
    feedback_id: int,
    body: VoteRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    feedback = await load_feedback(feedback_id, db)
    viewer = await viewer_gambler(feedback.gambler.gambling_season_id, user, db)

    require_open(feedback)
    require_not_author(feedback, viewer)

    existing = (await db.execute(
        select(FeedbackRating).where(
            FeedbackRating.feedback_id == feedback.id, FeedbackRating.gambler_id == viewer.id
        )
    )).scalar_one_or_none()

    if existing is None:
        db.add(FeedbackRating(feedback_id=feedback.id, gambler_id=viewer.id, value=body.value))
    elif existing.value == body.value:
        # Tapping the same arrow again takes the vote back.
        await db.delete(existing)
    else:
        # Tapping the other one changes your mind, rather than needing two taps.
        existing.value = body.value
    await db.commit()

    return FeedbackResponse(feedback=await feedback_response(await load_feedback(feedback_id, db), viewer, db))


@router.get("/{feedback_id}/votes", operation_id="list_feedback_votes", response_model=FeedbackVotersResponseData)
async def list_feedback_votes(
    feedback_id: int,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> FeedbackVotersResponseData:
    """Readable whatever the status: a settled suggestion's votes are part of its record."""
    feedback = await load_feedback(feedback_id, db)
    await viewer_gambler(feedback.gambler.gambling_season_id, user, db)

    rows = (await db.execute(
        select(FeedbackRating.value, User.first_name)
        .join(Gambler, Gambler.id == FeedbackRating.gambler_id)
        .join(User, User.id == Gambler.user_id)
        .where(FeedbackRating.feedback_id == feedback_id)
        .order_by(User.first_name)
    )).all()

    return FeedbackVotersResponseData(
        up=[name for value, name in rows if value > 0],
        down=[name for value, name in rows if value < 0],
    )


@router.get("/{feedback_id}/comments", operation_id="list_feedback_comments", response_model=ListFeedbackCommentsResponseData)
async def list_feedback_comments(
    feedback_id: int,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> ListFeedbackCommentsResponseData:
    feedback = await load_feedback(feedback_id, db)
    viewer = await viewer_gambler(feedback.gambler.gambling_season_id, user, db)

    comments = list((await db.execute(
        select(FeedbackComment)
        .where(FeedbackComment.feedback_id == feedback_id, FeedbackComment.archived_at.is_(None))
        .options(selectinload(FeedbackComment.gambler).selectinload(Gambler.user))
        # Oldest first: a thread reads top to bottom, and the client's reply box sits at
        # the bottom, so a new reply appears directly above where it was typed.
        .order_by(FeedbackComment.created_at.asc())
        .execution_options(populate_existing=True)
    )).scalars())

    return ListFeedbackCommentsResponseData(comments=[
        FeedbackCommentResponseData(
            id=c.id,
            feedback_id=c.feedback_id,
            gambler_id=c.gambler_id,
            author_name=author_name(c.gambler),
            comment=c.comment,
            created_at=c.created_at,
            updated_at=c.updated_at,
            viewer_is_author=c.gambler_id == viewer.id,
        )
        for c in comments
    ])


@router.post("/{feedback_id}/comments", operation_id="create_feedback_comment", response_model=CommentResponse)
async def create_feedback_comment(
    feedback_id: int,
    body: CommentRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> CommentResponse:
    feedback = await load_feedback(feedback_id, db)
    viewer = await viewer_gambler(feedback.gambler.gambling_season_id, user, db)

    require_open(feedback)

    text = body.comment.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Say something before replying")

    comment = FeedbackComment(feedback_id=feedback_id, gambler_id=viewer.id, comment=text)
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    return CommentResponse(comment=FeedbackCommentResponseData(
        id=comment.id,
        feedback_id=comment.feedback_id,
        gambler_id=comment.gambler_id,
        author_name=author_name(viewer),
        comment=comment.comment,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        viewer_is_author=True,
    ))


async def load_own_comment(comment_id: int, user: User, db: AsyncSession) -> Tuple[FeedbackComment, Gambler]:
    comment = (await db.execute(
        select(FeedbackComment).where(FeedbackComment.id == comment_id)
        .options(selectinload(FeedbackComment.gambler).selectinload(Gambler.user))
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if comment is None or comment.archived_at is not None:
        raise HTTPException(status_code=404, detail="That comment no longer exists")

    viewer = await viewer_gambler(comment.gambler.gambling_season_id, user, db)
    require_open(await load_feedback(comment.feedback_id, db))
    if comment.gambler_id != viewer.id:
        raise HTTPException(status_code=403, detail="You can only change your own comments")
    return comment, viewer


@router.put("/comments/{comment_id}", operation_id="update_feedback_comment", response_model=CommentResponse)
async def update_feedback_comment(
    comment_id: int,
    body: CommentRequestData,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> CommentResponse:
    comment, viewer = await load_own_comment(comment_id, user, db)

    text = body.comment.strip()
    if not text:
        raise HTTPException(status_code=400, detail="A comment cannot be empty")

    comment.comment = text
    await db.commit()
    await db.refresh(comment)

    return CommentResponse(comment=FeedbackCommentResponseData(
        id=comment.id,
        feedback_id=comment.feedback_id,
        gambler_id=comment.gambler_id,
        author_name=author_name(viewer),
        comment=comment.comment,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        viewer_is_author=True,
    ))


@router.delete("/comments/{comment_id}", operation_id="delete_feedback_comment")
async def delete_feedback_comment(
    comment_id: int,
    user: User = Depends(manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    comment, _ = await load_own_comment(comment_id, user, db)
    comment.archived_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    await db.commit()
    return {"deleted": comment_id}
