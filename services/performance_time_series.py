from typing import *

from pydantic import BaseModel

from .season_performance_calculator import SeasonPerformanceCalculator
from models import Pick, Parlay, ParlayState
from .metric_calculator import GamblerBaseMetrics, GamblerMetricsCalculator
from .score_correctors.score_corrector import GamblerScoreCorrector
from .common import PickVetoPair, get_gambler_picks_veto_pairs, pick_veto_pair_from_parlay

class TimeSeriesDatum(BaseModel):
    gambler_id: int
    parlay_order: int
    parlay_id: int
    metrics: GamblerBaseMetrics
    corrected_score: float

class TimeSeriesCalculator:
    def __init__(self, gambler_ids: list[int], parlays: list[Parlay], score_corrector_class: type[GamblerScoreCorrector]) -> None:
        self.gambler_ids = gambler_ids
        self.ordered_parlays = sorted(parlays, key=lambda p: p.order)
        self.score_corrector_class = score_corrector_class

    def create_time_series(self):

        gambler_metrics = {gambler_id: GamblerMetricsCalculator() for gambler_id in self.gambler_ids}
        time_series_data: dict[int, list[TimeSeriesDatum]] = {gambler_id: [] for gambler_id in self.gambler_ids}
        for parlay in self.ordered_parlays:
            if parlay.state != ParlayState.CLOSED or parlay.result is None:
                continue
            for gambler_id, calculator in gambler_metrics.items():
                pv_pair = pick_veto_pair_from_parlay(gambler_id, parlay)
                if pv_pair:
                    calculator.process_pv_pair(pv_pair)
            gambler_performances = SeasonPerformanceCalculator(
                gambler_metrics,
                self.score_corrector_class
            ).performances

            for gambler_id, calculator in gambler_metrics.items():
                time_series_data[gambler_id].append(
                    TimeSeriesDatum(
                        gambler_id=gambler_id,
                        parlay_order=parlay.order,
                        parlay_id=parlay.id,
                        metrics=calculator.get_base_metrics(),
                        corrected_score=gambler_performances[gambler_id].corrected_score
                    )
                )
        
        return time_series_data
                
        
    