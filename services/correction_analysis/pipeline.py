from collections import Counter
from typing import *

from models import Pick, PropBetType

from .extraction import extract_legs
from .matching import match_legs
from .models import CorrectionSuggestion, ExtractedLeg, ExtractionResult
from .picks import serialize_picks_for_matching

MULTI_MATCH_NOTE = "More than one pick matched this line, so it needs a manual correction."
NO_MATCH_NOTE = "No line on the slip matched this player and bet type."
CROSS_TARGET_NOTE = (
    "The slip names a player but this pick is on a team (or the other way round), which only "
    "lines up for field goals. Correct this one manually."
)

# A team's total and one player's total describe the same event only where a single player
# produces the whole team figure — the placekicker and field goals. Everything else a team
# accumulates across several players, so the two are different bets. The matching prompt says
# as much, but the model matches team rushing yards to a running back often enough that this
# has to be enforced here rather than asked for.
LOOSE_MATCH_PROP_TYPES = {PropBetType.FGS}


def _dedupe_legs(legs: list[ExtractedLeg]) -> list[ExtractedLeg]:
    """Collapse the same leg appearing in overlapping screenshots.

    Safe because the league never runs the same player and bet type twice in one
    parlay. `leg_index` is left untouched, so gaps are expected after this runs.
    """
    seen: set[tuple[str, str | None]] = set()
    kept: list[ExtractedLeg] = []
    for leg in legs:
        key = leg.target_key()
        if key in seen:
            continue
        seen.add(key)
        kept.append(leg)
    return kept


async def extract_legs_from_images(images: list[str]) -> ExtractionResult:
    result = await extract_legs(images)
    return ExtractionResult(
        legs=_dedupe_legs(result.legs),
        stated_leg_count=result.stated_leg_count,
    )


def _cleared(suggestion: CorrectionSuggestion, note: str) -> CorrectionSuggestion:
    return CorrectionSuggestion(
        pick_id=suggestion.pick_id,
        matched_leg_index=None,
        suggested_number=None,
        direction_mismatch=False,
        loose_target_match=False,
        note=note,
    )


async def match_legs_to_picks(
    legs: list[ExtractedLeg],
    picks: list[Pick],
) -> list[CorrectionSuggestion]:
    """Produce exactly one suggestion per pick, in the order the picks were given.

    Everything the reviewer acts on is derived deterministically from the matched
    leg. The model's only load-bearing output is *which* leg was matched; the
    number is copied from extraction and the direction mismatch is recomputed
    here, so neither can be invented during matching.
    """
    if not picks:
        return []

    pick_payload = serialize_picks_for_matching(picks)
    directions = {p.pick_id: p.direction for p in pick_payload}
    legs_by_index = {leg.leg_index: leg for leg in legs}

    if not legs:
        return [
            CorrectionSuggestion(
                pick_id=p.pick_id,
                matched_leg_index=None,
                suggested_number=None,
                direction_mismatch=False,
                loose_target_match=False,
                note=NO_MATCH_NOTE,
            )
            for p in pick_payload
        ]

    result = await match_legs(legs, pick_payload)

    by_pick: dict[int, CorrectionSuggestion] = {}
    for suggestion in result.suggestions:
        if suggestion.pick_id not in directions or suggestion.pick_id in by_pick:
            continue
        if suggestion.matched_leg_index not in legs_by_index:
            suggestion = _cleared(suggestion, suggestion.note or NO_MATCH_NOTE)
        by_pick[suggestion.pick_id] = suggestion

    # A pick the model skipped entirely is the same outcome as an unmatched one.
    for pick in pick_payload:
        if pick.pick_id not in by_pick:
            by_pick[pick.pick_id] = CorrectionSuggestion(
                pick_id=pick.pick_id,
                matched_leg_index=None,
                suggested_number=None,
                direction_mismatch=False,
                loose_target_match=False,
                note=NO_MATCH_NOTE,
            )

    # The same leg landing on two picks is model error, not a real data condition.
    # Drop every member of the conflict rather than picking a winner.
    claimed = Counter(
        s.matched_leg_index for s in by_pick.values() if s.matched_leg_index is not None
    )
    contested = {index for index, count in claimed.items() if count > 1}

    reconciled: list[CorrectionSuggestion] = []
    for pick in pick_payload:
        suggestion = by_pick[pick.pick_id]

        if suggestion.matched_leg_index in contested:
            reconciled.append(_cleared(suggestion, MULTI_MATCH_NOTE))
            continue

        if suggestion.matched_leg_index is None:
            suggestion.loose_target_match = False
            reconciled.append(suggestion)
            continue

        leg = legs_by_index[suggestion.matched_leg_index]
        crosses_target_kind = (pick.player_name is None) != (leg.player_name is None)

        if crosses_target_kind and pick.prop_type not in LOOSE_MATCH_PROP_TYPES:
            reconciled.append(_cleared(suggestion, CROSS_TARGET_NOTE))
            continue

        suggestion.loose_target_match = crosses_target_kind
        suggestion.suggested_number = leg.number
        suggestion.direction_mismatch = leg.direction != directions[pick.pick_id]
        reconciled.append(suggestion)

    _match_team_picks_to_lone_player_leg(
        reconciled, pick_payload, legs, legs_by_index, directions, contested
    )

    return reconciled


def _match_team_picks_to_lone_player_leg(
    reconciled: list[CorrectionSuggestion],
    pick_payload,
    legs: list[ExtractedLeg],
    legs_by_index: dict[int, ExtractedLeg],
    directions,
    contested: set[int | None],
) -> None:
    """Line a team-recorded pick up with a player leg without needing to know the roster.

    A slip usually shows the team only as a logo, so a kicker's leg arrives with no team
    attached and the matching model has to know from memory who he plays for. It often
    does not. Where the pick is on a team and exactly one unclaimed leg on the slip is a
    player's leg of the same market, there is nothing to be ambiguous about — take it,
    and flag it so a human confirms. Two candidates means a real choice, so leave both.

    Restricted to the markets where a team total genuinely is one player's total; see
    LOOSE_MATCH_PROP_TYPES.
    """
    claimed = {s.matched_leg_index for s in reconciled if s.matched_leg_index is not None}
    claimed |= contested

    picks_by_id = {pick.pick_id: pick for pick in pick_payload}

    for suggestion in reconciled:
        if suggestion.matched_leg_index is not None:
            continue

        pick = picks_by_id[suggestion.pick_id]
        if pick.player_name is not None or pick.prop_type not in LOOSE_MATCH_PROP_TYPES:
            continue

        candidates = [
            leg for leg in legs
            if leg.leg_index not in claimed
            and leg.prop_type == pick.prop_type
            and leg.player_name is not None
        ]
        if len(candidates) != 1:
            continue

        leg = candidates[0]
        claimed.add(leg.leg_index)

        suggestion.matched_leg_index = leg.leg_index
        suggestion.suggested_number = leg.number
        suggestion.direction_mismatch = leg.direction != directions[pick.pick_id]
        suggestion.loose_target_match = True
        suggestion.note = None
