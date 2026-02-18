from dataclasses import dataclass

from models import Parlay, Pick, PickVeto, PickResult, VetoResult, PropBetType, SauceFactor, VetoApprovalStatus, ParlayState, PropBetDirection

@dataclass
class PickVetoPair:
    pick: Pick
    veto: PickVeto | None

    def is_bozo(self):
        return self.pick.result == PickResult.BOZO or (self.veto and self.veto.result == VetoResult.BOZO)
    
    def pick_is_bozo(self):
        return self.pick.result == PickResult.BOZO

    def pick_is_win(self):
        return self.pick.result == PickResult.WIN
    
    def pick_is_loss(self):
        return self.pick.result in [PickResult.BOZO, PickResult.LOSS]
    
    def pick_is_push(self):
        return self.pick.result == PickResult.PUSH
    
    def pick_is_void(self):
        return self.pick.result == PickResult.VOID
    
    def veto_is_good(self):
        if not self.veto:
            return False
        return self.veto.result in [VetoResult.GOOD or VetoResult.BOZO_SAVER]

    def veto_is_bad(self):
        if not self.veto:
            return False
        return self.veto.result in [VetoResult.BAD, VetoResult.BOZO]
    
    def veto_is_bozo(self):
        if not self.veto:
            return False
        return self.veto.result == VetoResult.BOZO
    
    def veto_is_bozo_saver(self):
        if not self.veto:
            return False
        return self.veto.result == VetoResult.BOZO_SAVER
    
    def veto_is_void(self):
        if not self.veto:
            return False
        return self.veto.result == VetoResult.VOID
    
    def veto_is_push(self):
        if not self.veto:
            return False
        return self.veto.result == VetoResult.PUSH
    
    def is_TD_pick(self):
        return self.pick.prop_type == PropBetType.TDS
    
    def is_over_pick(self):
        return self.pick.direction == PropBetDirection.OVER
    
    def is_under_pick(self):
        return self.pick.direction == PropBetDirection.UNDER
    
    def is_spicy_pick(self):
        return self.pick.sauce_factor == SauceFactor.SPICY
    
    def is_bitch_pick(self):
        return self.pick.sauce_factor == SauceFactor.BITCH
    
    def pick_has_result(self):
        return self.pick.result is not None
    
    def has_approved_veto(self):
        return self.veto and self.veto.approval_status == VetoApprovalStatus.APPROVED
    
    def get_prop_type(self):
        return self.pick.prop_type

def pick_veto_pair_from_parlay(gambler_id: int, parlay: Parlay) -> PickVetoPair | None:
    gambler_pick: Pick | None = None
    gambler_veto: PickVeto | None = None
    for pick in parlay.picks:
        if pick.gambler_id == gambler_id:
            gambler_pick = pick
        elif pick.veto and pick.veto.gambler_id == gambler_id:
            gambler_veto = pick.veto
    if gambler_pick is not None:
        return PickVetoPair(pick=gambler_pick, veto=gambler_veto)
    return None


def get_gambler_picks_veto_pairs(gambler_id: int, sorted_parlays: list[Parlay]) -> list[PickVetoPair]:
    pick_veto_pairs: list[PickVetoPair] = []
    for parlay in sorted_parlays:
        if parlay.state != ParlayState.CLOSED or not parlay.result:
            continue
        pv_pair = pick_veto_pair_from_parlay(gambler_id, parlay)
        if pv_pair:
            pick_veto_pairs.append(pv_pair)
    return pick_veto_pairs