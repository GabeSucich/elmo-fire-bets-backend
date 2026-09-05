from typing import *

from models import Pick, PropBetDirection, VetoApprovalStatus

from .models import PickForMatching


def effective_direction(pick: Pick) -> PropBetDirection:
    """The direction a pick is *displayed* with.

    An approved veto flips the displayed direction without touching `pick.direction`
    in the database — see `lineAndDirectionDisplay` in frontend/util/picks.ts. The
    matcher has to be told the displayed direction, otherwise every vetoed pick
    reports a direction mismatch against the slip and the warning becomes noise.
    """
    veto_approved = any(
        veto.approval_status == VetoApprovalStatus.APPROVED for veto in pick.vetoes
    )
    if not veto_approved:
        return pick.direction
    return (
        PropBetDirection.UNDER
        if pick.direction == PropBetDirection.OVER
        else PropBetDirection.OVER
    )


def serialize_picks_for_matching(picks: list[Pick]) -> list[PickForMatching]:
    return [
        PickForMatching(
            pick_id=pick.id,
            player_name=pick.prop_bet_target.player_name,
            team_name=pick.prop_bet_target.team_name,
            prop_type=pick.prop_type,
            direction=effective_direction(pick),
            line=pick.corrected_line if pick.corrected_line is not None else pick.line,
        )
        for pick in picks
    ]
