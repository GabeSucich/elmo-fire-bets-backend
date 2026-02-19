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


async def finalize_parlay_results(parlay: Parlay, db: AsyncSession) -> Tuple[Parlay, list[ParlayResult]]:
    picks_and_results: list[Tuple[Pick, PickResult]] = []

    for pick in parlay.picks:
        pick_result = pick.result
        if pick_result is None:
            raise ValueError("Cannot finalize a parlay when some picks do not have results!")
        picks_and_results.append((pick, pick_result))
    
    incorrect_picks = [pick for (pick, result) in picks_and_results if result == PickResult.LOSS or result == PickResult.BOZO]

    possible_parlay_results: list[ParlayResult] = []
    if len(incorrect_picks) == 0:
        approved_vetoes: list[PickVeto] = []
        for pick, _ in picks_and_results:
            approved_vetoes.extend([v for v in pick.vetoes if v.approval_status == VetoApprovalStatus.APPROVED])
        if len(approved_vetoes) > 1:
            raise ValueError("There should never be more than one approved veto for a parlay!")
        elif len(approved_vetoes) == 1:
            bozo_veto = approved_vetoes[0]
            bozo_veto.result = VetoResult.BOZO
            possible_parlay_results = [ParlayResult.BOZO]
        else:
            possible_parlay_results = [ParlayResult.WIN]
        
    elif len(incorrect_picks) == 1:
        bozo_pick = incorrect_picks[0]
        bozo_pick.result = PickResult.BOZO
        approved_vetoes = [v for v in bozo_pick.vetoes if v.approval_status == VetoApprovalStatus.APPROVED]
        if len(approved_vetoes) > 1:
            raise ValueError("There should never be more than one approved veto for a parlay!")
        elif len(approved_vetoes) == 1:
            veto = approved_vetoes[0]
            veto.result = VetoResult.BOZO_SAVER
            possible_parlay_results = [ParlayResult.WIN]
        else:
            parlay.result = ParlayResult.LOSS
            possible_parlay_results = [ParlayResult.BOZO]

    else:
        possible_parlay_results = [ParlayResult.LOSS]

    return parlay, possible_parlay_results
    


    
