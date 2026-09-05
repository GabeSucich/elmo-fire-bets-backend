import json
from typing import *

from .client import CorrectionAnalysisError, get_client
from .models import ExtractedLeg, MatchingResult, PickForMatching
from .prompts import MATCHING_PROMPT

# Mini rather than nano: at minimal effort it is both quicker and right, where nano
# mismatched the same fixture. Measured on the real slip — nano/low 11.4s, mini/minimal 2.9s.
MATCHING_MODEL = "gpt-5-mini"

# Matching is pure identity resolution, so the model is shown only identity. Withholding
# the pick's number is the point: `pipeline` copies the number from the matched leg and
# recomputes the direction mismatch itself, so a number here could only ever mislead —
# a recorded 39.5 against a placed 42.5 reads as evidence of a different bet when it is
# in fact the exact case this feature exists to correct.
PICK_FIELDS = {"pick_id", "player_name", "team_name", "prop_type"}
LEG_FIELDS = {"leg_index", "player_name", "team_name", "prop_type", "raw_text"}


async def match_legs(
    legs: list[ExtractedLeg],
    picks: list[PickForMatching],
) -> MatchingResult:
    """Assign each recorded pick at most one leg from the slip.

    Uniqueness is asserted deterministically afterwards in `pipeline`; asking for it
    here only makes a correct answer more likely, it does not guarantee one.
    """
    payload = {
        "PICKS": [pick.model_dump(mode="json", include=PICK_FIELDS) for pick in picks],
        "LEGS": [leg.model_dump(mode="json", include=LEG_FIELDS) for leg in legs],
    }

    response = await get_client().responses.parse(
        model=MATCHING_MODEL,
        reasoning={"effort": "minimal"},
        input=[
            {"role": "system", "content": MATCHING_PROMPT},
            {"role": "user", "content": json.dumps(payload, indent=2)},
        ],
        text_format=MatchingResult,
    )

    if response.output_parsed is None:
        raise CorrectionAnalysisError("Could not match those bet lines to the recorded picks.")

    return response.output_parsed
