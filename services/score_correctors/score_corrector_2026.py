from typing import *

from services.metric_calculator import ScoredMetrics
from .score_corrector import GamblerScoreCorrector, GamblerScoreCorrections, ScoreCorrection

if TYPE_CHECKING:
    from services.metric_calculator import GamblerBaseMetrics

MOST_BITCH_LOSSES_DATA = ["most-bitch-losses", "Most bitch losses"]
MOST_BOZOS_DATA = ["most-bozos", "Most bozos"]

class GamblerScoreCorrector2026(GamblerScoreCorrector):
    """2026 rules: TD slate parlays are excluded from scoring entirely, and there
    is no longer a bonus for spicy hits."""

    def __init__(self, all_gambler_metrics: dict[int, 'GamblerBaseMetrics']) -> None:
        self.all_gambler_metrics = all_gambler_metrics

    def scored_metrics(self, gambler_metrics: 'GamblerBaseMetrics') -> ScoredMetrics:
        # 2026 leaves TD slates out of scoring entirely.
        return ScoredMetrics.of(gambler_metrics.non_TD_slate)

    def deductions(self) -> GamblerScoreCorrections:
        gamblers_with_most_bozos: list[int] = []
        gamblers_with_most_bitch_losses: list[int] = []

        max_bozo_cnt = 0
        max_bitch_losses = 0
        for gambler_id, metrics in self.all_gambler_metrics.items():
            bozos = metrics.non_TD_slate.overall.bozos
            if bozos > max_bozo_cnt:
                gamblers_with_most_bozos = [gambler_id]
                max_bozo_cnt = bozos
            elif bozos == max_bozo_cnt and max_bozo_cnt > 0:
                gamblers_with_most_bozos.append(gambler_id)

            bitch_losses = metrics.non_TD_slate.sauce_factor.bitch.losses
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
        return {}
