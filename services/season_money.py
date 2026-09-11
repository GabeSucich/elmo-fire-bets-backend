"""What a season has actually paid out, per person.

Separate from the loss ledger next door: that one is about blame, this one is about the
balance. Both read the same two columns and neither is derivable from the other.
"""
from dataclasses import dataclass

from models import Parlay, ParlayResult, ParlayState


@dataclass
class SeasonMoney:
    """The season's running total for one person, and how complete it is."""
    # Net across every closed lay: what a win made, less what a loss cost. Per person,
    # because the stake and the return both are.
    net_pp: float
    # Wins whose payout nobody has recorded. They contribute nothing, so a total with any
    # of these is an understatement rather than an answer, and the screen should say so.
    wins_missing_payout: int
    closed_lays: int


def season_money(parlays: list[Parlay]) -> SeasonMoney:
    """Add up a season.

    Only closed lays: one still open has not paid or cost anything yet, and counting a
    building lay's stake would be charging for a bet nobody has placed.

    A push or a void returns the stake and makes nothing, so it moves the total by zero
    rather than by the wager — the money came back.
    """
    net = 0.0
    missing = 0
    closed = 0

    for parlay in parlays:
        if parlay.state is not ParlayState.CLOSED or parlay.result is None:
            continue
        closed += 1

        if parlay.result is ParlayResult.WIN:
            if parlay.payout_pp is None:
                # Counted as nothing rather than guessed at. The count beside the total is
                # what stops that reading as a season that simply did worse than it did.
                missing += 1
                continue
            net += parlay.payout_pp - parlay.wager_pp
        elif parlay.result in (ParlayResult.LOSS, ParlayResult.BOZO):
            net -= parlay.wager_pp

    return SeasonMoney(
        net_pp=round(net, 2),
        wins_missing_payout=missing,
        closed_lays=closed,
    )
