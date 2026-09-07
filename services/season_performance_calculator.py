from typing import *

from pydantic import BaseModel

from models import GamblingSeason, Parlay, ParlayState, PickVeto, Pick
from .metric_counter import PickVetoPair
from .score_correctors.score_corrector import GamblerScoreCorrector, ScoreCorrectionSet
from .metric_calculator import GamblerMetricsCalculator, GamblerAdvancedMetrics, ScoredMetrics

class GamblerPerformance(BaseModel):
    gambler_id: int
    corrected_score: float
    metrics: GamblerAdvancedMetrics
    scored_metrics: ScoredMetrics
    deductions: ScoreCorrectionSet
    augmentations: ScoreCorrectionSet

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
        metrics = {gambler_id: calculator.get_advanced_metrics() for gambler_id, calculator in self.gambler_metrics_calculators.items()}
        score_corrector = self.score_corrector_class(metrics)
        deductions = score_corrector.deductions()
        augmentations = score_corrector.augmentations()
        
        all_gambler_performances: dict[int, GamblerPerformance] = {}
        
        for gambler_id, gambler_metrics in metrics.items():
            gambler_deductions = deductions.get(gambler_id, {})
            gambler_augmentations = augmentations.get(gambler_id, {})
            scored = score_corrector.scored_metrics(gambler_metrics)
            base_score = scored.overall.win_rate
            if base_score is None:
                corrected_score = 0
            else:
                deduction_values = [d.adjustment for d in gambler_deductions.values()]
                augmentation_values = [a.adjustment for a in gambler_augmentations.values()]
                corrected_score = base_score + sum(deduction_values + augmentation_values)
            gambler_performance = GamblerPerformance(
                gambler_id=gambler_id,
                corrected_score=corrected_score,
                metrics=gambler_metrics,
                scored_metrics=scored,
                deductions=gambler_deductions,
                augmentations=gambler_augmentations
            )

            all_gambler_performances[gambler_id] = gambler_performance
        
        return all_gambler_performances
            
        