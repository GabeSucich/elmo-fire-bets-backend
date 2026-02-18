from dataclasses import dataclass, field

from models import PropBetType
from .common import PickVetoPair

def rounded(n: float, to=2):
    return round(n, to)

def calc_rate(numer: float, denom: float, round_to=2):
    if denom == 0:
        return None
    
    return rounded(100*numer/denom, to=round_to)


@dataclass
class PickCategoryCounter:
    total: int = 0
    wins: int = 0
    losses: int = 0
    pushes: int = 0
    voids: int = 0
    bozos: int = 0
    curr_win_streak: int = 0
    curr_loss_streak: int = 0
    curr_bozo_streak: int = 0
    longest_win_streak: int = 0
    longest_loss_streak: int = 0
    longest_bozo_streak: int = 0
    win_streak_freqs: dict[int, int] = field(default_factory=dict)
    loss_streak_freqs: dict[int, int] = field(default_factory=dict)
    bozo_streak_freqs: dict[int, int] = field(default_factory=dict)


    def process_pv_pair(self, pv_pair: PickVetoPair):
        if not pv_pair.pick_has_result():
            return self
        
        self.total += 1
        if pv_pair.pick_is_bozo():
            self.bozos += 1
            self.curr_bozo_streak += 1
            self.longest_bozo_streak = max(self.curr_bozo_streak, self.longest_bozo_streak)
        
        if pv_pair.pick_is_win():
            self.wins += 1
        elif pv_pair.pick_is_loss():
            self.losses += 1
        elif pv_pair.pick_is_push():
            self.pushes += 1
        elif pv_pair.pick_is_void():
            self.voids += 1
        
        if pv_pair.pick_is_win():
            self.curr_win_streak += 1
            self.longest_win_streak = max(self.longest_win_streak, self.curr_win_streak)
            if self.curr_loss_streak > 0:
                self.loss_streak_freqs[self.curr_loss_streak] = self.loss_streak_freqs.get(self.curr_loss_streak, 0) + 1
            if self.curr_bozo_streak > 0:
                self.bozo_streak_freqs[self.curr_bozo_streak] = self.bozo_streak_freqs.get(self.curr_bozo_streak, 0) + 1
            self.curr_loss_streak = 0
            self.curr_bozo_streak = 0
        elif pv_pair.pick_is_loss():
            self.curr_loss_streak += 1
            self.longest_loss_streak = max(self.longest_loss_streak, self.curr_loss_streak)
            self.curr_win_streak = 0
        
        return self
    
    def _corrected_total(self):
        return self.total - self.pushes - self.voids
    
    def _calc_rate(self, val: float):
        total = self._corrected_total()
        return calc_rate(val, total)
    
    def win_rate(self):
        return self._calc_rate(self.wins)
    
    def bozo_rate(self):
        return self._calc_rate(self.bozos)
            

@dataclass
class VetoCategoryCounter:
    total: int = 0
    goods: int = 0
    bads: int = 0
    pushes: int = 0
    voids: int = 0
    bozos: int = 0
    bozo_savers: int = 0

    curr_good_streak: int = 0
    curr_bad_streak: int = 0
    curr_bozo_streak: int = 0
    curr_bozo_saver_streak: int = 0

    def process_pv_pair(self, pv_pair: PickVetoPair):
        if not pv_pair.has_approved_veto():
            return self

        if pv_pair.veto_is_bozo():
            self.bozos += 1
            self.curr_bozo_streak += 1
        elif pv_pair.veto_is_bozo_saver():
            self.bozo_savers += 1
            self.curr_bozo_saver_streak += 1

        if pv_pair.veto_is_good():
            self.goods += 1
            self.curr_good_streak += 1
            self.curr_bad_streak = 0
            self.curr_bozo_streak = 0
        elif pv_pair.veto_is_bad():
            self.bads += 1
            self.curr_bad_streak += 1
            self.curr_good_streak = 0
            self.curr_bozo_saver_streak = 0
        elif pv_pair.veto_is_void():
            self.voids += 1
        elif pv_pair.veto_is_push():
            self.pushs += 1
        
        return self
    
    def _corrected_total(self):
        return self.total - self.pushes - self.voids
    
    def _calc_rate(self, val: float):
        total = self._corrected_total()
        return calc_rate(val, total)
    
    def good_rate(self):
        return self._calc_rate(self.goods)
    
    def bozo_rate(self):
        return self._calc_rate(self.bozos)
    
    def bozo_saver_rate(self):
        return self._calc_rate(self.bozo_savers)


@dataclass
class MetricCounter:
    overall: PickCategoryCounter = field(default_factory=PickCategoryCounter)
    TD: PickCategoryCounter = field(default_factory=PickCategoryCounter)
    non_TD: PickCategoryCounter = field(default_factory=PickCategoryCounter)
    spicy: PickCategoryCounter = field(default_factory=PickCategoryCounter)
    bitch: PickCategoryCounter = field(default_factory=PickCategoryCounter)
    overs: PickCategoryCounter = field(default_factory=PickCategoryCounter)
    unders: PickCategoryCounter = field(default_factory=PickCategoryCounter)
    vetoes: VetoCategoryCounter = field(default_factory=VetoCategoryCounter)
    over_vetoes: VetoCategoryCounter = field(default_factory=VetoCategoryCounter)
    under_vetoes: VetoCategoryCounter = field(default_factory=VetoCategoryCounter)
    prop_types: dict[PropBetType, "MetricCounter"] | None = field(default_factory=dict)

    def process_pv_pair(self, pv_pair: PickVetoPair):
        self.overall.process_pv_pair(pv_pair)

        if pv_pair.is_TD_pick():
            self.TD.process_pv_pair(pv_pair)
        else:
            self.non_TD.process_pv_pair(pv_pair)

        if pv_pair.is_spicy_pick():
            self.spicy.process_pv_pair(pv_pair)
        elif pv_pair.is_bitch_pick():
            self.bitch.process_pv_pair(pv_pair)

        if pv_pair.is_over_pick():
            self.overs.process_pv_pair(pv_pair)
            self.over_vetoes.process_pv_pair(pv_pair)
        elif pv_pair.is_under_pick():
            self.unders.process_pv_pair(pv_pair)
            self.under_vetoes.process_pv_pair(pv_pair)

        self.vetoes.process_pv_pair(pv_pair)
        
        if self.prop_types:
            prop_type = pv_pair.get_prop_type()
            self.prop_types[prop_type] = self.prop_types.get(prop_type, MetricCounter(prop_types=None)).process_pv_pair(pv_pair)
        
        return self

        


