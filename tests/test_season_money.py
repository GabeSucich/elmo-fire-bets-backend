"""Adding up a season's money.

The arithmetic is trivial; what is worth asserting is which lays move the total, by how
much, and which quietly do not move it at all.
"""
from models import Parlay, ParlayResult, ParlayState
from services.season_money import season_money


def lay(result, payout=None, wager=5.0, state=ParlayState.CLOSED):
    return Parlay(result=result, payout_pp=payout, wager_pp=wager, state=state)


def test_a_win_adds_what_it_made_not_what_it_returned():
    """The stake was already spent, so only the profit is new money."""
    assert season_money([lay(ParlayResult.WIN, 185.0)]).net_pp == 180.0


def test_a_loss_costs_the_stake():
    assert season_money([lay(ParlayResult.LOSS)]).net_pp == -5.0


def test_a_bozo_costs_the_stake_like_any_other_loss():
    """What it additionally cost the group is the ledger's business, not the balance's."""
    assert season_money([lay(ParlayResult.BOZO)]).net_pp == -5.0


def test_a_push_and_a_void_move_nothing():
    """The stake came back, so neither a gain nor a loss."""
    assert season_money([lay(ParlayResult.PUSH), lay(ParlayResult.VOID)]).net_pp == 0.0


def test_a_season_adds_up():
    result = season_money([
        lay(ParlayResult.WIN, 105.0),   # +100
        lay(ParlayResult.LOSS),         # -5
        lay(ParlayResult.LOSS),         # -5
        lay(ParlayResult.BOZO),         # -5
        lay(ParlayResult.PUSH),         #  0
    ])
    assert result.net_pp == 85.0
    assert result.closed_lays == 5


def test_a_win_with_no_payout_is_counted_and_left_out():
    """Left out of the total so nothing is invented, and counted so the screen can say the
    total is a floor rather than an answer."""
    result = season_money([lay(ParlayResult.WIN, None), lay(ParlayResult.LOSS)])
    assert result.net_pp == -5.0
    assert result.wins_missing_payout == 1


def test_only_closed_lays_count():
    """An open lay has neither paid nor cost anything yet, and a building one is not a bet."""
    for state in (ParlayState.OPEN, ParlayState.BUILDING):
        result = season_money([lay(ParlayResult.LOSS, state=state)])
        assert result.net_pp == 0.0
        assert result.closed_lays == 0


def test_a_closed_lay_with_no_result_is_not_counted():
    assert season_money([lay(None)]).closed_lays == 0
