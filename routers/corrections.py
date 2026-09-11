from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAIError
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Parlay, User
from services.correction_analysis import (
    CorrectionSuggestion,
    ExtractedLeg,
    extract_legs_from_images,
    match_legs_to_picks,
)
from services.correction_analysis.client import CorrectionAnalysisError

from .auth import manager
from .common import check_season_in_progress, check_user_access_to_parlay, query_parlay_with_selects
from .picks import user_can_override_picks

router = APIRouter(
    prefix="/parlays",
    dependencies=[Depends(manager)],
    tags=["Corrections"]
)

MAX_IMAGES = 6

# Neither endpoint writes. Accepted corrections are submitted one at a time through
# the existing POST /picks/{pick_id}/override, exactly as manual corrections are.


async def authorize_correction_analysis(parlay_id: int, user: User, db: AsyncSession) -> Parlay:
    parlay = (await query_parlay_with_selects(parlay_id, db)).scalar_one()

    await check_season_in_progress(parlay.gambling_season_id, db)
    await check_user_access_to_parlay(user, parlay, db)

    if not user_can_override_picks(parlay, user):
        raise HTTPException(status_code=500, detail="Only the parlay owner can correct picks!")

    return parlay


class ExtractCorrectionLegsRequestData(BaseModel):
    images: list[str]


class ExtractCorrectionLegsResponseData(BaseModel):
    legs: list[ExtractedLeg]
    stated_leg_count: int | None
    # As printed on the slip: whole lay, stake included. The client divides it.
    total_payout: float | None


@router.post(
    "/{parlay_id}/correction_analysis/extract",
    operation_id="extract_correction_legs",
    response_model=ExtractCorrectionLegsResponseData
)
async def extract_correction_legs(
    parlay_id: int,
    body: ExtractCorrectionLegsRequestData,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager)
) -> ExtractCorrectionLegsResponseData:

    await authorize_correction_analysis(parlay_id, user, db)

    if not body.images:
        raise HTTPException(status_code=400, detail="No screenshots were provided!")
    if len(body.images) > MAX_IMAGES:
        raise HTTPException(status_code=400, detail=f"Cannot analyze more than {MAX_IMAGES} screenshots at once!")

    try:
        result = await extract_legs_from_images(body.images)
    except (CorrectionAnalysisError, OpenAIError) as error:
        raise HTTPException(status_code=500, detail=str(error))

    return ExtractCorrectionLegsResponseData(
        legs=result.legs,
        stated_leg_count=result.stated_leg_count,
        total_payout=result.total_payout
    )


class MatchCorrectionLegsRequestData(BaseModel):
    legs: list[ExtractedLeg]


class MatchCorrectionLegsResponseData(BaseModel):
    suggestions: list[CorrectionSuggestion]


@router.post(
    "/{parlay_id}/correction_analysis/match",
    operation_id="match_correction_legs",
    response_model=MatchCorrectionLegsResponseData
)
async def match_correction_legs(
    parlay_id: int,
    body: MatchCorrectionLegsRequestData,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager)
) -> MatchCorrectionLegsResponseData:

    parlay = await authorize_correction_analysis(parlay_id, user, db)

    try:
        suggestions = await match_legs_to_picks(body.legs, parlay.picks)
    except (CorrectionAnalysisError, OpenAIError) as error:
        raise HTTPException(status_code=500, detail=str(error))

    return MatchCorrectionLegsResponseData(
        suggestions=suggestions
    )
