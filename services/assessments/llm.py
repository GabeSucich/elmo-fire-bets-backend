import json
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from services.correction_analysis.client import get_client

from .prompts import PARLAY_PROMPT, PICK_PROMPT

# Mini for the same reasons as correction analysis. Low effort rather than minimal: this
# is reading records for patterns rather than lifting text off a slip.
ASSESSMENT_MODEL = "gpt-5-mini"
REASONING_EFFORT = "low"


# A bracketed aside that names a payload field — "(this_prop_type)", "(trends
# spicy_picks)". The prompt forbids these and the model writes them anyway, about one
# suggestion in six, so they are cut here rather than asked about again.
_FIELD_ASIDE = re.compile(r"\s*\([^()]*\b[a-z]+_[a-z0-9_]+\b[^()]*\)")


def without_field_names(text: str) -> str:
    return _FIELD_ASIDE.sub("", text).strip()


class AssessmentError(Exception):
    """Raised when the model cannot produce a usable assessment."""


class SignalStrength(StrEnum):
    """How strongly the data behind a concern argues against the pick. See the prompt."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ConcernTag(StrEnum):
    """Where a concern comes from. One per concern; see the prompt for what each covers."""
    PAST_TREND = "past_trend"
    GAME_SCRIPT = "game_script"
    WEATHER = "weather"
    # Slate only: two legs on the same team fighting for the same volume.
    COMPETING_LINES = "competing_lines"
    # Slate only: several legs riding on one game's score.
    SAME_GAME = "same_game"


SIGNAL_ORDER = {SignalStrength.HIGH: 0, SignalStrength.MEDIUM: 1, SignalStrength.LOW: 2}


class Suggestion(BaseModel):
    title: str
    description: str
    signal: SignalStrength
    tag: ConcernTag


class AssessmentResult(BaseModel):
    suggestions: list[Suggestion] = Field(default_factory=list)


async def _assess(prompt: str, payload: dict[str, Any]) -> list[Suggestion]:
    response = await get_client().responses.parse(
        model=ASSESSMENT_MODEL,
        reasoning={"effort": REASONING_EFFORT},
        input=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, separators=(",", ":"))},
        ],
        text_format=AssessmentResult,
    )
    if response.output_parsed is None:
        raise AssessmentError("The model did not return an assessment.")
    # Strongest first, whatever order the model wrote them in. Stable, so concerns of equal
    # strength keep the model's own ranking.
    ranked = sorted(response.output_parsed.suggestions, key=lambda s: SIGNAL_ORDER[s.signal])
    return [
        s.model_copy(update={
            "title": without_field_names(s.title),
            "description": without_field_names(s.description),
        })
        for s in ranked[:3]
    ]


async def assess_pick(payload: dict[str, Any]) -> list[Suggestion]:
    return await _assess(PICK_PROMPT, payload)


async def assess_parlay(payload: dict[str, Any]) -> list[Suggestion]:
    return await _assess(PARLAY_PROMPT, payload)
