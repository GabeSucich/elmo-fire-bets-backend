"""What bozoing has cost each gambler.

A bozo is a leg that lost a lay everybody else had done their part on. This puts a number
on it: the money the lay would have paid out, which nobody got, laid at the door of the
person whose leg it was.
"""
from models import Parlay, ParlayResult, PickResult


def _lost(parlay: Parlay) -> bool:
    """Whether the lay went down.

    BOZO is its own parlay result rather than a flavour of LOSS, and in this league it is
    the usual one for a lay somebody bozoed — but not the only one, so both count.
    """
    return parlay.result in (ParlayResult.LOSS, ParlayResult.BOZO)


def loss_ledger(parlays: list[Parlay]) -> dict[int, float]:
    """Per gambler, what their bozos cost the group.

    The figure is what the lay would have *made*, not what it would have returned: the
    stake was gone the moment it was placed, so charging it again would bill somebody for
    money nobody lost on their account. A lay whose payout was never recorded contributes
    nothing — there is no honest number to charge, and guessing one would be worse than a
    ledger that is quietly short.

    A lay has only ever had one bozo on it. If that ever changes, each of them is charged
    the whole cost rather than a share: the number answers "what did this cost us", and
    halving it would let two people off more lightly than one.
    """
    ledger: dict[int, float] = {}

    for parlay in parlays:
        if not _lost(parlay) or parlay.payout_pp is None:
            continue
        cost = round(parlay.payout_pp - parlay.wager_pp, 2)
        if cost <= 0:
            continue
        for pick in parlay.picks:
            if pick.result is PickResult.BOZO:
                ledger[pick.gambler_id] = round(ledger.get(pick.gambler_id, 0.0) + cost, 2)

    return ledger
