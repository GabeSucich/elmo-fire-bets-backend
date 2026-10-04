import datetime

from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAIError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models import Parlay, ParlayState, PropBetDirection, PropBetType, SauceFactor, User
from services.assessments.llm import AssessmentError, ConcernTag, SignalStrength, without_field_names
from services.assessments.service import MIN_PICKS, SlotReport, SlotStatus, current_report, generate

from .auth import manager
from .common import check_season_in_progress, check_user_access_to_parlay

router = APIRouter(
    prefix="/parlays",
    dependencies=[Depends(manager)],
    tags=["Assessments"]
)


class AssessmentSuggestionData(BaseModel):
    title: str
    description: str
    # Both null on concerns written before they existed.
    signal: SignalStrength | None = None
    tag: ConcernTag | None = None


class AssessedPickData(BaseModel):
    """A pick as it stood when it was assessed, for comparing against how it stands now."""
    pick_id: int
    player: str | None
    prop_type: PropBetType
    line: float
    direction: PropBetDirection
    sauce_factor: SauceFactor | None
    vetoed: bool


class AssessmentSlotData(BaseModel):
    # Null for the assessment of the parlay as a whole.
    pick_id: int | None
    status: SlotStatus
    # Empty when stale: advice about a pick that has since changed is not advice about
    # this one. assessed_against still says what it was about.
    suggestions: list[AssessmentSuggestionData]
    assessed_at: datetime.datetime | None
    # One pick for a pick's slot, every pick for the parlay's.
    assessed_against: list[AssessedPickData]


class ParlayAssessmentResponseData(BaseModel):
    can_request: bool
    # Why can_request is false, in words fit to show.
    request_blocked_reason: str | None
    picks: list[AssessmentSlotData]
    parlay: AssessmentSlotData


def _blocked_reason(parlay: Parlay) -> str | None:
    if parlay.state != ParlayState.BUILDING:
        return "Picks can only be analyzed while a parlay is being built."
    if len(parlay.picks) < MIN_PICKS:
        return f"A parlay needs at least {MIN_PICKS} picks to be analyzed."
    return None


def _slot_data(report: SlotReport) -> AssessmentSlotData:
    assessment = report.assessment
    if assessment is None:
        return AssessmentSlotData(
            pick_id=report.pick_id, status=report.status,
            suggestions=[], assessed_at=None, assessed_against=[],
        )
    snapshot = assessment.subject_snapshot
    picks = snapshot["picks"] if "picks" in snapshot else [snapshot]
    return AssessmentSlotData(
        pick_id=report.pick_id,
        status=report.status,
        suggestions=[] if report.status == SlotStatus.STALE else [
            # Cleaned on the way out as well as on the way in, so assessments stored before
            # the cleaning existed read the same as new ones.
            AssessmentSuggestionData(**{
                **s,
                "title": without_field_names(s["title"]),
                "description": without_field_names(s["description"]),
            })
            for s in assessment.suggestions
        ],
        assessed_at=assessment.created_at,
        assessed_against=[
            AssessedPickData(
                pick_id=pick["pick_id"], player=pick["player"], prop_type=pick["prop_type"],
                line=pick["line"], direction=pick["direction"],
                sauce_factor=pick["sauce_factor"], vetoed=pick["vetoed"],
            )
            for pick in picks
        ],
    )


def _response(parlay: Parlay, reports: list[SlotReport]) -> ParlayAssessmentResponseData:
    reason = _blocked_reason(parlay)
    return ParlayAssessmentResponseData(
        can_request=reason is None,
        request_blocked_reason=reason,
        picks=[_slot_data(r) for r in reports if r.pick_id is not None],
        parlay=next(_slot_data(r) for r in reports if r.pick_id is None),
    )


@router.get(
    "/{parlay_id}/assessment",
    operation_id="get_parlay_assessment",
    response_model=ParlayAssessmentResponseData,
)
async def get_parlay_assessment(
    parlay_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager),
) -> ParlayAssessmentResponseData:
    await check_user_access_to_parlay(user, parlay_id, db)
    parlay, reports = await current_report(parlay_id, db)
    return _response(parlay, reports)


@router.post(
    "/{parlay_id}/assessment",
    operation_id="request_parlay_assessment",
    response_model=ParlayAssessmentResponseData,
)
async def request_parlay_assessment(
    parlay_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager),
) -> ParlayAssessmentResponseData:
    # Anyone in the season may ask, by decision — it costs a few cents and only says things.
    await check_user_access_to_parlay(user, parlay_id, db)
    parlay = (await db.execute(
        select(Parlay).where(Parlay.id == parlay_id).options(selectinload(Parlay.picks))
    )).scalar_one()
    await check_season_in_progress(parlay.gambling_season_id, db)

    reason = _blocked_reason(parlay)
    if reason is not None:
        raise HTTPException(status_code=400, detail=reason)

    try:
        parlay, reports = await generate(parlay_id, db)
    except (AssessmentError, OpenAIError) as error:
        raise HTTPException(status_code=500, detail=str(error))
    return _response(parlay, reports)
