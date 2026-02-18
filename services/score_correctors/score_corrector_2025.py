from typing import *

from models import Parlay
from .score_corrector import GamblerScoreCorrector, GamblerScoreCorrections, ScoreCorrectionSet, ScoreCorrection

if TYPE_CHECKING:
    from services.metric_calculator import GamblerBaseMetrics

MOST_BITCH_LOSSES_DATA = ["most-bitch-losses", "Most bitch losses"]
MOST_BOZOS_DATA = ["most-bozos", "Most bozos"]
MOST_SPICY_HITS_DATA = ["most-spicy-hits", "Most spicy hits"]

class GamblerScoreCorrector2025(GamblerScoreCorrector):

    def __init__(self, all_gambler_metrics: dict[int, 'GamblerBaseMetrics']) -> None:
        self.all_gambler_metrics = all_gambler_metrics

    def deductions(self) -> GamblerScoreCorrections:
        gamblers_with_most_bozos: list[int] = []
        gamblers_with_most_bitch_losses: list[int] = []

        max_bozo_cnt = 0
        max_bitch_losses = 0
        for gambler_id, metrics in self.all_gambler_metrics.items():
            bozos = metrics.overall.bozos
            if bozos > max_bozo_cnt:
                gamblers_with_most_bozos = [gambler_id]
                max_bozo_cnt = bozos
            elif bozos == max_bozo_cnt and max_bozo_cnt > 0:
                gamblers_with_most_bozos.append(gambler_id)
            
            bitch_losses = metrics.sauce_factor.bitch.losses
            if bitch_losses > max_bitch_losses:
                gamblers_with_most_bitch_losses = [gambler_id]
                max_bitch_losses = bitch_losses
            elif bitch_losses == max_bitch_losses and max_bitch_losses > 0:
                gamblers_with_most_bitch_losses.append(gambler_id)
        
        if max_bitch_losses == 0:
            gamblers_with_most_bitch_losses = []
        if max_bozo_cnt == 0:
            gamblers_with_most_bozos = []
        
        corrections: GamblerScoreCorrections = {}

        for gambler_id in gamblers_with_most_bozos:
            existing = corrections.get(gambler_id, {})
            score_correction = ScoreCorrection(
                identifier=MOST_BOZOS_DATA[0],
                name=MOST_BOZOS_DATA[1],
                associated_value=max_bozo_cnt,
                adjustment=-2
            )
            corrections[gambler_id] = {**existing, MOST_BOZOS_DATA[0]: score_correction}
        
        for gambler_id in gamblers_with_most_bitch_losses:
            existing = corrections.get(gambler_id, {})
            score_correction = ScoreCorrection(
                identifier=MOST_BITCH_LOSSES_DATA[0],
                name=MOST_BITCH_LOSSES_DATA[1],
                associated_value=max_bitch_losses,
                adjustment=-2
            )
            corrections[gambler_id] = {**existing, MOST_BITCH_LOSSES_DATA[0]: score_correction}
        
        return corrections
            
    def augmentations(self) -> GamblerScoreCorrections:
        gamblers_with_most_spicy_wins: list[int] = []

        max_spicy_wins = 0
        for gambler_id, metrics in self.all_gambler_metrics.items():
            spicy_wins = metrics.sauce_factor.spicy.wins
            if spicy_wins > max_spicy_wins:
                gamblers_with_most_spicy_wins = [gambler_id]
                max_spicy_wins = spicy_wins
            elif spicy_wins == max_spicy_wins and max_spicy_wins > 0:
                gamblers_with_most_spicy_wins.append(spicy_wins)
        
        if max_spicy_wins == 0:
            return {}
        
        score_correction = ScoreCorrection(
            identifier=MOST_SPICY_HITS_DATA[0],
            name=MOST_SPICY_HITS_DATA[1],
            adjustment=2,
            associated_value=max_spicy_wins
        )
        
        return {gambler_id: {MOST_SPICY_HITS_DATA[0]: score_correction} for gambler_id in gamblers_with_most_spicy_wins}
        

