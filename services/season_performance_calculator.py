from typing import *

from pydantic import BaseModel

from models import GamblingSeason, Parlay, ParlayState, PickVeto, Pick
from .metric_counter import PickVetoPair
from .score_correctors.score_corrector_2025 import GamblerScoreCorrector2025
from .score_correctors.score_corrector import GamblerScoreCorrector, ScoreCorrectionSet
from .metric_calculator import GamblerBaseMetrics, GamblerMetricsCalculator, GamblerMetricsWithBetTypes

SCORE_CORRECTORS = {
    2025: GamblerScoreCorrector2025,
}

def get_season_score_corrector_class(season_year: int):
    return SCORE_CORRECTORS.get(season_year, GamblerScoreCorrector2025)

class GamblerPerformance(BaseModel):
    gambler_id: int
    corrected_score: float
    metrics: GamblerBaseMetrics
    deductions: ScoreCorrectionSet
    augmentations: ScoreCorrectionSet

def get_gambler_picks_veto_pairs(gambler_id: int, sorted_parlays: list[Parlay]) -> list[PickVetoPair]:
    pick_veto_pairs: list[PickVetoPair] = []
    for parlay in sorted_parlays:
        if parlay.state != ParlayState.CLOSED or not parlay.result:
            continue
        gambler_pick: Pick | None = None
        gambler_veto: PickVeto | None = None
        for pick in parlay.picks:
            if pick.gambler_id == gambler_id:
                gambler_pick = pick
            elif pick.veto and pick.veto.gambler_id == gambler_id:
                gambler_veto = pick.veto
        if gambler_pick is not None:
            pick_veto_pairs.append(PickVetoPair(pick=gambler_pick, veto=gambler_veto))
    return pick_veto_pairs

class SeasonPerformanceCalculator:

    def __init__(
            self, 
            gambler_metrics_calculators: dict[int, GamblerMetricsCalculator],
            score_corrector_class: type[GamblerScoreCorrector]
        ) -> None:
        self.gambler_metrics_calculators = gambler_metrics_calculators
        self.score_corrector_class = score_corrector_class
        self._performances = self._get_performances()
            
    @property
    def performances(self):
        return self._performances

    def _get_performances(self) -> dict[int, GamblerPerformance]:
        metrics = {gambler_id: calculator.get_base_metrics() for gambler_id, calculator in self.gambler_metrics_calculators.items()}
        score_corrector = self.score_corrector_class(metrics)
        deductions = score_corrector.deductions()
        augmentations = score_corrector.augmentations()
        
        all_gambler_performances: dict[int, GamblerPerformance] = {}
        
        for gambler_id, gambler_metrics in metrics.items():
            gambler_deductions = deductions.get(gambler_id, {})
            gambler_augmentations = augmentations.get(gambler_id, {})
            win_rate = gambler_metrics.overall.win_rate
            if win_rate is None:
                corrected_score = 0
            else:
                deduction_values = [d.adjustment for d in gambler_deductions.values()]
                augmentation_values = [a.adjustment for a in gambler_augmentations.values()]
                corrected_score = win_rate + sum(deduction_values + augmentation_values)
            gambler_performance = GamblerPerformance(
                gambler_id=gambler_id,
                corrected_score=corrected_score,
                metrics=gambler_metrics,
                deductions=gambler_deductions,
                augmentations=gambler_augmentations
            )

            all_gambler_performances[gambler_id] = gambler_performance
        
        return all_gambler_performances
            
        