from abc import ABC, abstractmethod
from typing import *

from pydantic import BaseModel

class ScoreCorrection(BaseModel):
    identifier: str
    name: str
    associated_value: int | float
    adjustment: float
    # What the value actually counts, already pluralised: "8 bozos", "1 bitch loss".
    # Built here rather than in the client, which would otherwise have to strip the
    # "Most " off a name and guess at English plurals.
    summary: str


def counted(value: int | float, singular: str, plural: str) -> str:
    return f"{value} {singular if value == 1 else plural}"

ScoreCorrectionSet = dict[str, ScoreCorrection]
GamblerScoreCorrections = dict[int, ScoreCorrectionSet]

if TYPE_CHECKING:
    from services.metric_calculator import GamblerBaseMetrics, ScoredMetrics


class GamblerScoreCorrector(ABC):

    @abstractmethod
    def __init__(self, gambler_metrics: dict[int, "GamblerBaseMetrics"]) -> None: ...

    @abstractmethod
    def scored_metrics(self, gambler_metrics: "GamblerBaseMetrics") -> "ScoredMetrics":
        """The subset of a gambler's picks this season's rules run on.

        The score and the stats displayed alongside it both come from here, so a
        season that leaves some picks out of scoring cannot end up showing numbers
        that contradict the score it produced.
        """

    @abstractmethod
    def deductions(self) -> GamblerScoreCorrections: ...

    @abstractmethod
    def augmentations(self) -> GamblerScoreCorrections: ...