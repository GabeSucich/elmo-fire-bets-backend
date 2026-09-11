from typing import *

from pydantic import BaseModel

from models import PropBetType, PropBetDirection


class ExtractedLeg(BaseModel):
    """A single bet leg read off an uploaded parlay screenshot.

    `raw_text` is carried through to the review UI so a reviewer can see what the
    model actually read, which is the only practical check on alternate-line
    normalization (`2+` becoming Over 1.5).
    """
    leg_index: int
    raw_text: str
    player_name: str | None
    team_name: str | None
    prop_type: PropBetType | None
    direction: PropBetDirection
    number: float

    def target_key(self) -> tuple[str, str | None]:
        """Identity of the thing being bet on, for deduplication across images."""
        name = self.player_name or self.team_name or self.raw_text
        return (name.strip().lower(), self.prop_type.value if self.prop_type else None)


class ExtractionResult(BaseModel):
    legs: list[ExtractedLeg]
    stated_leg_count: int | None
    # What the slip says the bet returns if it lands, as printed — the whole return with
    # the stake inside it, and for the whole lay rather than per person. Null when the
    # slip does not show one, which is common on a screenshot cropped to the legs.
    total_payout: float | None


class PickForMatching(BaseModel):
    """A recorded pick as the matching model sees it.

    `direction` here is the *effective* direction — already flipped if an approved
    veto is in play — so a vetoed pick does not read as a direction mismatch.
    """
    pick_id: int
    player_name: str | None
    team_name: str
    prop_type: PropBetType
    direction: PropBetDirection
    line: float


class CorrectionSuggestion(BaseModel):
    """The model's proposal for one pick.

    There is deliberately no field capable of expressing a target or prop-type
    change: the "only the number moves" rule is enforced by this shape rather
    than by prompt compliance.
    """
    pick_id: int
    matched_leg_index: int | None
    suggested_number: float | None
    direction_mismatch: bool
    # True when a pick recorded against a team was matched to a leg naming a player, or the
    # reverse — legitimate for a kicker's field goals, wrong for anything a team accumulates
    # across several players. Always worth a human confirming.
    loose_target_match: bool
    note: str | None


class MatchingResult(BaseModel):
    suggestions: list[CorrectionSuggestion]
