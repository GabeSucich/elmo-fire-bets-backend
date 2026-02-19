from dataclasses import dataclass
from types import UnionType
from typing import Union

from pydantic import BaseModel

from models import PropBetType, Parlay, Pick, PickVeto, VetoResult, PickResult, ParlayState, SauceFactor, PropBetDirection
from .metric_counter import MetricCounter, PickCategoryCounter, VetoCategoryCounter
from .common import PickVetoPair, pick_veto_pair_from_parlay

def round_to(n: float, to=4):
    return round(n, to)

class SetMetrics(BaseModel):
    total: int
    wins: int
    losses: int
    bozos: int
    pushes: int
    voids: int
    curr_win_streak: int
    curr_loss_streak: int
    curr_bozo_streak: int
    longest_win_streak: int
    longest_loss_streak: int
    longest_bozo_streak: int
    win_rate: float | None
    bozo_rate: float | None

    @classmethod
    def from_counter(cls, counter: PickCategoryCounter):
        return cls(
            total=counter.total,
            wins=counter.wins,
            losses=counter.losses,
            bozos=counter.bozos,
            pushes=counter.pushes,
            voids=counter.voids,
            curr_win_streak=counter.curr_win_streak,
            curr_loss_streak=counter.curr_loss_streak,
            curr_bozo_streak=counter.curr_bozo_streak,
            longest_win_streak=counter.longest_win_streak,
            longest_loss_streak=counter.longest_loss_streak,
            longest_bozo_streak=counter.longest_bozo_streak,
            win_rate=counter.win_rate(),
            bozo_rate=counter.bozo_rate()
        )

class SetVetoMetrics(BaseModel):
    total: int
    goods: int
    bads: int
    bozos: int
    bozo_savers: int
    pushes: int
    voids: int
    curr_good_streak: int
    curr_bad_streak: int
    curr_bozo_streak: int
    curr_bozo_saver_streak: int
    good_rate: float | None
    bozo_rate: float | None
    bozo_saver_rate: float | None

    @classmethod
    def from_counter(cls, counter: VetoCategoryCounter):
        return cls(
            total=counter.total,
            goods=counter.goods,
            bads=counter.bads,
            bozos=counter.bozos,
            bozo_savers=counter.bozo_savers,
            pushes=counter.pushes,
            voids=counter.voids,
            curr_good_streak=counter.curr_good_streak,
            curr_bad_streak=counter.curr_bad_streak,
            curr_bozo_streak=counter.curr_bozo_streak,
            curr_bozo_saver_streak=counter.curr_bozo_saver_streak,
            good_rate=counter.good_rate(),
            bozo_rate=counter.bozo_rate(),
            bozo_saver_rate=counter.bozo_saver_rate()
        )

class SauceFactorMetrics(BaseModel):
    spicy: SetMetrics
    bitch: SetMetrics

class DirectionVetoMetrics(BaseModel):
    overs: SetVetoMetrics
    unders: SetVetoMetrics

class DirectionMetrics(BaseModel):
    overs: SetMetrics
    unders: SetMetrics
    vetoes: DirectionVetoMetrics

class PropBetTypeMetrics(BaseModel):
    overall: SetMetrics
    sauce_factor: SauceFactorMetrics
    direction_metrics: DirectionMetrics
    vetoes: SetVetoMetrics

    @classmethod
    def from_counter(cls, counter: MetricCounter):
        return cls(
            overall=SetMetrics.from_counter(counter.overall),
            sauce_factor=SauceFactorMetrics(
                spicy=SetMetrics.from_counter(counter.spicy),
                bitch=SetMetrics.from_counter(counter.bitch)
            ),
            direction_metrics=DirectionMetrics(
                overs=SetMetrics.from_counter(counter.overs),
                unders=SetMetrics.from_counter(counter.unders),
                vetoes=DirectionVetoMetrics(
                    overs=SetVetoMetrics.from_counter(counter.over_vetoes),
                    unders=SetVetoMetrics.from_counter(counter.under_vetoes)
                )
            ),
            vetoes=SetVetoMetrics.from_counter(counter.vetoes)
        )

class BetTypeMetrics(BaseModel):
    bet_types: dict[PropBetType, PropBetTypeMetrics]
    
    @classmethod
    def from_counter(cls, counter: MetricCounter):
        if counter.prop_types is None:
            return cls(bet_types={})
        return cls(
            bet_types={
                prop_type: PropBetTypeMetrics.from_counter(counter) 
                for prop_type, counter in counter.prop_types.items()
            }
        )

    

class PropTargetMetrics(BaseModel):
    prop_targets: dict[int, PropBetTypeMetrics]
    target_names: dict[int, str]

    @classmethod
    def from_counter(cls, counter: MetricCounter, target_names: dict[int, str]):
        if counter.prop_targets is None:
            return cls(prop_targets={}, target_names={})
        return cls(
            prop_targets={
                target_id: PropBetTypeMetrics.from_counter(target_counter)
                for target_id, target_counter in counter.prop_targets.items()
            },
            target_names=target_names
        )


class GamblerBaseMetrics(BaseModel):
    overall: SetMetrics
    TD: SetMetrics
    non_TD: SetMetrics
    sauce_factor: SauceFactorMetrics
    direction: DirectionMetrics
    veto_metrics: SetVetoMetrics

class GamblerAdvancedMetrics(GamblerBaseMetrics):
    bet_types: BetTypeMetrics
    prop_target_metrics: PropTargetMetrics

class GamblerMetricsCalculator:
    def __init__(self) -> None:
        self.mc = MetricCounter()
        self._pv_pairs: list[PickVetoPair] = []
        self._target_names: dict[int, str] = {}

    def process_pv_pair(self, pv_pair: PickVetoPair):
        self.mc.process_pv_pair(pv_pair)
        self._pv_pairs.append(pv_pair)
        target_id = pv_pair.get_prop_target_id()
        if target_id not in self._target_names:
            self._target_names[target_id] = pv_pair.get_prop_target_display_name()
    
    @classmethod
    def calculator_from_parlays(cls, gambler_id: int, parlays: list[Parlay]):
        calculator = cls()
        sorted_parlays = sorted(parlays, key=lambda p: p.order)
        for parlay in sorted_parlays:
            if not parlay.result or parlay.state != ParlayState.CLOSED:
                continue
            pv_pair = pick_veto_pair_from_parlay(gambler_id, parlay)
            if pv_pair:
                calculator.process_pv_pair(pv_pair)
        return calculator
    
    @classmethod
    def calculator_dict_from_parlays(cls, gambler_ids: list[int], parlays: list[Parlay]):
        return {
            gambler_id: cls.calculator_from_parlays(gambler_id, parlays) for gambler_id in gambler_ids
        }
    
    def get_base_metrics(self) -> GamblerBaseMetrics:
        return GamblerBaseMetrics(
            overall=SetMetrics.from_counter(self.mc.overall),
            TD=SetMetrics.from_counter(self.mc.TD),
            non_TD=SetMetrics.from_counter(self.mc.non_TD),
            sauce_factor=SauceFactorMetrics(
                spicy=SetMetrics.from_counter(self.mc.spicy),
                bitch=SetMetrics.from_counter(self.mc.bitch)
            ),
            direction=DirectionMetrics(
                overs=SetMetrics.from_counter(self.mc.overs),
                unders=SetMetrics.from_counter(self.mc.unders),
                vetoes=DirectionVetoMetrics(
                    overs=SetVetoMetrics.from_counter(self.mc.over_vetoes),
                    unders=SetVetoMetrics.from_counter(self.mc.under_vetoes)
                )
            ),
            veto_metrics=SetVetoMetrics.from_counter(self.mc.vetoes)
        )
    

    def get_advanced_metrics(self) -> GamblerAdvancedMetrics:
        return GamblerAdvancedMetrics(
            overall=SetMetrics.from_counter(self.mc.overall),
            TD=SetMetrics.from_counter(self.mc.TD),
            non_TD=SetMetrics.from_counter(self.mc.non_TD),
            sauce_factor=SauceFactorMetrics(
                spicy=SetMetrics.from_counter(self.mc.spicy),
                bitch=SetMetrics.from_counter(self.mc.bitch)
            ),
            direction=DirectionMetrics(
                overs=SetMetrics.from_counter(self.mc.overs),
                unders=SetMetrics.from_counter(self.mc.unders),
                vetoes=DirectionVetoMetrics(
                    overs=SetVetoMetrics.from_counter(self.mc.over_vetoes),
                    unders=SetVetoMetrics.from_counter(self.mc.under_vetoes)
                )
            ),
            bet_types=BetTypeMetrics.from_counter(self.mc),
            prop_target_metrics=PropTargetMetrics.from_counter(self.mc, self._target_names),
            veto_metrics=SetVetoMetrics.from_counter(self.mc.vetoes)
        )