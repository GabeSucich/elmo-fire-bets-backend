from typing import *

from sqlalchemy.ext.asyncio import AsyncSession

from models import Parlay, Pick, Pick, PickVeto, PickResult, VetoResult, VetoApprovalStatus, ParlayResult

PickAndVetoType = Tuple[Pick, PickResult, Tuple[PickVeto, VetoResult] | None]


def map_pick_result_to_veto_result(pick_result: PickResult, all_picks_right=False) -> VetoResult:
    match pick_result:
        case PickResult.WIN:
            if all_picks_right:
                return VetoResult.BOZO
            else:
                return VetoResult.BAD
        case PickResult.LOSS:
            return VetoResult.GOOD
        case PickResult.BOZO:
            return VetoResult.BOZO_SAVER
        case PickResult.VOID:
            return VetoResult.VOID
        case PickResult.PUSH:
            return VetoResult.PUSH
        case _:
            raise ValueError(f"Could not map pick result {pick_result} to any veto result!")


def approved_veto(pick: Pick) -> PickVeto | None:
    approved = [v for v in pick.vetoes if v.approval_status == VetoApprovalStatus.APPROVED]
    if len(approved) > 1:
        raise ValueError("There should never be more than one approved veto for a parlay!")
    return approved[0] if approved else None


def leg_lost(pick: Pick, result: PickResult) -> bool:
    """Whether the leg that actually ran came in wrong.

    A pick's stored result is always the INITIAL pick's, and an approved veto flips the
    bet that went on the slip — so a vetoed pick that was stored as a loss is a leg that
    won. Counting stored results directly treated it as a loss, which double-counted the
    veto and turned a bozo into a plain loss whenever another pick was also down.
    """
    if approved_veto(pick) is not None:
        return result == PickResult.WIN
    return result in (PickResult.LOSS, PickResult.BOZO)


async def finalize_parlay_results(parlay: Parlay, db: AsyncSession) -> Tuple[Parlay, list[ParlayResult]]:
    picks_and_results: list[Tuple[Pick, PickResult]] = []

    for pick in parlay.picks:
        pick_result = pick.result
        if pick_result is None:
            raise ValueError("Cannot finalize a parlay when some picks do not have results!")
        picks_and_results.append((pick, pick_result))

    lost_legs = [(pick, approved_veto(pick)) for pick, result in picks_and_results if leg_lost(pick, result)]

    if len(lost_legs) == 0:
        # Nothing the slip needed went wrong. A veto that flipped a losing pick into a
        # winning leg is the reason for that, and gets the credit.
        for pick, result in picks_and_results:
            veto = approved_veto(pick)
            if veto is not None and result == PickResult.LOSS:
                veto.result = VetoResult.BOZO_SAVER

        # A pushed or voided leg is neither won nor lost, and books differ on whether it
        # drops out of the parlay or settles the whole thing. Both readings are offered
        # rather than assumed. Only here: once a leg has actually lost, the parlay is lost
        # or bozo'd whatever else pushed.
        possible = [ParlayResult.WIN]
        results = [result for _, result in picks_and_results]
        if PickResult.PUSH in results:
            possible.append(ParlayResult.PUSH)
        if PickResult.VOID in results:
            possible.append(ParlayResult.VOID)
        return parlay, possible

    if len(lost_legs) == 1:
        # One leg away from a winner: somebody is the bozo. The vetoer wears it when the
        # veto is what turned a winning pick into a losing leg.
        pick, veto = lost_legs[0]
        if veto is not None:
            veto.result = VetoResult.BOZO
        else:
            pick.result = PickResult.BOZO
        return parlay, [ParlayResult.BOZO]

    return parlay, [ParlayResult.LOSS]
