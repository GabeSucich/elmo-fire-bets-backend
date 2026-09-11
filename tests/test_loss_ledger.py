"""What a bozo costs, and when it costs nothing.

The arithmetic is one subtraction; everything worth asserting is about which lays count
and which quietly do not.
"""
import pytest

from models import Parlay, ParlayResult, Pick, PickResult
from services.loss_ledger import loss_ledger


def lay(result, payout, picks, wager=5.0):
    parlay = Parlay(result=result, wager_pp=wager, payout_pp=payout)
    parlay.picks = [Pick(gambler_id=g, result=r) for g, r in picks]
    return parlay


def test_a_bozo_is_charged_what_the_lay_would_have_made():
    """Not what it would have returned. The stake was gone the moment it was placed, so
    billing it again charges somebody for money nobody lost on their account."""
    ledger = loss_ledger([lay(ParlayResult.BOZO, 135.0, [(1, PickResult.BOZO), (2, PickResult.LOSS)])])
    assert ledger == {1: 130.0}


def test_only_the_gambler_who_bozoed_is_charged():
    ledger = loss_ledger([lay(ParlayResult.BOZO, 105.0, [
        (1, PickResult.WIN), (2, PickResult.BOZO), (3, PickResult.WIN),
    ])])
    assert ledger == {2: 100.0}


def test_bozos_accumulate_across_the_season():
    ledger = loss_ledger([
        lay(ParlayResult.BOZO, 55.0, [(1, PickResult.BOZO)]),
        lay(ParlayResult.BOZO, 30.5, [(1, PickResult.BOZO)]),
        lay(ParlayResult.BOZO, 25.0, [(2, PickResult.BOZO)]),
    ])
    assert ledger == {1: 75.5, 2: 20.0}


def test_a_lay_with_no_payout_recorded_charges_nothing():
    """Every bozo in the league's history is currently in this state.

    A guess would be worse than a ledger that is quietly short, so it contributes nothing
    until somebody enters what the lay paid.
    """
    assert loss_ledger([lay(ParlayResult.BOZO, None, [(1, PickResult.BOZO)])]) == {}


def test_a_bozo_on_a_lay_that_merely_lost_still_counts():
    """One of the league's twenty-three bozos sits on a LOSS rather than a BOZO parlay.

    Keying on the parlay's own result would miss it; keying on the pick does not.
    """
    assert loss_ledger([lay(ParlayResult.LOSS, 80.0, [(1, PickResult.BOZO)])]) == {1: 75.0}


@pytest.mark.parametrize("result", [ParlayResult.WIN, ParlayResult.PUSH, ParlayResult.VOID])
def test_nothing_is_charged_on_a_lay_that_did_not_go_down(result):
    """A bozo pick on a lay that still came in cost nobody anything."""
    assert loss_ledger([lay(result, 200.0, [(1, PickResult.BOZO)])]) == {}


def test_a_payout_that_did_not_beat_the_stake_charges_nothing():
    """Defensive: a payout at or below the wager means there was nothing to lose."""
    assert loss_ledger([lay(ParlayResult.BOZO, 5.0, [(1, PickResult.BOZO)])]) == {}


def test_a_lay_nobody_bozoed_is_absent_rather_than_zero():
    """Absent, so the badge can be left off entirely rather than reading "$0"."""
    assert loss_ledger([lay(ParlayResult.LOSS, 90.0, [(1, PickResult.LOSS)])]) == {}
