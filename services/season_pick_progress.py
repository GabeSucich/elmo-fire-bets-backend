import datetime
from enum import StrEnum
from typing import *

from pydantic import BaseModel

from models import SeasonPick, SeasonPickKind, PropBetDirection
from .season_rules import SeasonRules, latest_open_week


class SeasonPickStatus(StrEnum):
    PENDING = "Pending"
    HIT = "Hit"
    MISSED = "Missed"


class SeasonPickWeekProgress(BaseModel):
    week: int
    played: bool
    value: float | None


class SeasonPickProgress(BaseModel):
    total: float
    weeks_recorded: int
    weeks_played: int
    missing_weeks: list[int]
    # Lowest week that is open for entry and has no row yet. Backfill comes first,
    # so a missed week keeps surfacing instead of being skipped for a newer one.
    next_week_to_enter: int | None
    status: SeasonPickStatus
    weeks: list[SeasonPickWeekProgress]


def _status(pick: SeasonPick, total: float, weeks_remaining: int) -> SeasonPickStatus:
    """Decided as soon as the outcome is certain, otherwise pending.

    An OVER is settled the moment the line is cleared and can never come back. An
    UNDER is dead on the same event. The reverse only settles early for team wins,
    where the games left cap how much the total can still move; a player's stat has
    no such ceiling, so it stays pending until every week is in.
    """
    if pick.direction == PropBetDirection.OVER:
        if total > pick.line:
            return SeasonPickStatus.HIT
    else:
        if total > pick.line:
            return SeasonPickStatus.MISSED

    if weeks_remaining == 0:
        cleared = total > pick.line
        hit = cleared if pick.direction == PropBetDirection.OVER else not cleared
        return SeasonPickStatus.HIT if hit else SeasonPickStatus.MISSED

    if pick.kind == SeasonPickKind.TEAM_WINS:
        # Every remaining game is worth at most one win.
        best_case = total + weeks_remaining
        if pick.direction == PropBetDirection.OVER and best_case <= pick.line:
            return SeasonPickStatus.MISSED
        if pick.direction == PropBetDirection.UNDER and best_case < pick.line:
            return SeasonPickStatus.HIT

    return SeasonPickStatus.PENDING


def build_progress(
    pick: SeasonPick,
    rules: SeasonRules,
    today: datetime.date | None = None,
) -> SeasonPickProgress:
    by_week = {w.week: w for w in pick.weeks}
    total = sum(w.value or 0 for w in pick.weeks if w.played)

    open_through = latest_open_week(rules, today)
    missing = [wk for wk in range(1, open_through + 1) if wk not in by_week]

    return SeasonPickProgress(
        total=total,
        weeks_recorded=len(by_week),
        weeks_played=sum(1 for w in pick.weeks if w.played),
        missing_weeks=missing,
        next_week_to_enter=missing[0] if missing else None,
        status=_status(pick, total, rules.weeks - len(by_week)),
        weeks=sorted(
            (SeasonPickWeekProgress(week=w.week, played=w.played, value=w.value) for w in pick.weeks),
            key=lambda w: w.week,
        ),
    )
