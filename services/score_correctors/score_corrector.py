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
    from services.metric_calculator import GamblerBaseMetrics


class GamblerScoreCorrector(ABC):

    @abstractmethod
    def __init__(self, gambler_metrics: dict[int, "GamblerBaseMetrics"]) -> None: ...

    @abstractmethod
    def deductions(self) -> GamblerScoreCorrections: ...

    @abstractmethod
    def augmentations(self) -> GamblerScoreCorrections: ...