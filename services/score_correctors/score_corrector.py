from abc import ABC, abstractmethod
from typing import *

from pydantic import BaseModel

class ScoreCorrection(BaseModel):
    identifier: str
    name: str
    associated_value: int | float
    adjustment: float

ScoreCorrectionSet = dict[str, ScoreCorrection]
GamblerScoreCorrections = dict[int, ScoreCorrectionSet]

if TYPE_CHECKING:
    from services.metric_calculator import GamblerAdvancedMetrics, ScoredMetrics


class GamblerScoreCorrector(ABC):

    @abstractmethod
    def __init__(self, gambler_metrics: dict[int, "GamblerAdvancedMetrics"]) -> None: ...

    @abstractmethod
    def scored_metrics(self, gambler_metrics: "GamblerAdvancedMetrics") -> "ScoredMetrics":
        """The subset of a gambler's picks this season's rules run on.

        The score and the stats displayed alongside it both come from here, so a
        season that leaves some picks out of scoring cannot end up showing numbers
        that contradict the score it produced.
        """

    @abstractmethod
    def deductions(self) -> GamblerScoreCorrections: ...

    @abstractmethod
    def augmentations(self) -> GamblerScoreCorrections: ...