import datetime
from enum import StrEnum
from typing import *

from pydantic import BaseModel

from models import SeasonPick, SeasonPickKind, PropBetDirection, PropBetType
from .season_rules import SeasonRules, latest_open_week


# Markets whose season figure is the best single game rather than the sum of every game.
# build_progress adds the weeks up, which is right for a stat you accumulate and nonsense
# for one you only set a new best in: fifteen weeks of a longest reception sum to 329 for
# a player whose longest all year was 45, clearing a 55.5 line that was never beaten.
# Kept here rather than in the router because the sum below is the reason for the rule.
SEASON_UNSUPPORTED_PROPS: frozenset[PropBetType] = frozenset({
    PropBetType.LONGEST_RUSH,
    PropBetType.LONGEST_RECEPTION,
    PropBetType.LONGEST_TD,
    PropBetType.LONGEST_COMPLETION,
})


class SeasonPickStatus(StrEnum):
    PENDING = "Pending"
    HIT = "Hit"
    MISSED = "Missed"


class SeasonPickWeekProgress(BaseModel):
    week: int
    played: bool
    value: float | None
    # Null where the sync has not been able to say — see SeasonPickWeek.team_played.
    team_played: bool | None


class SeasonPickProgress(BaseModel):
    total: float
    weeks_recorded: int
    weeks_played: int
    # How far into the team's 17 games the season is, which is what pace and the rate a
    # pick still needs are measured against. Distinct from weeks_played, which counts the
    # games the *player* appeared in: someone who missed three games is three games behind
    # the season, not three games short of a shorter one.
    games_elapsed: int
    missing_weeks: list[int]
    # Lowest week that is open for entry and has no row yet. Backfill comes first,
    # so a missed week keeps surfacing instead of being skipped for a newer one.
    next_week_to_enter: int | None
    status: SeasonPickStatus
    weeks: list[SeasonPickWeekProgress]


def _status(
    pick: SeasonPick, total: float, weeks_remaining: int, games_remaining: int,
) -> SeasonPickStatus:
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
        # Every remaining game is worth at most one win — games, not weeks. A team plays
        # 17 of the 18, so counting weeks credits them with the bye and keeps a bet that
        # is already decided sitting at pending until the bye has been played through.
        best_case = total + games_remaining
        if pick.direction == PropBetDirection.OVER and best_case <= pick.line:
            return SeasonPickStatus.MISSED
        if pick.direction == PropBetDirection.UNDER and best_case < pick.line:
            return SeasonPickStatus.HIT

    return SeasonPickStatus.PENDING


def team_played(week) -> bool:
    """Whether the team had a game that week.

    Falls back to the player's own appearance where the sync could not say — the reading
    this had before team_played existed, and still the best available for a week entered
    by hand.
    """
    return week.played if week.team_played is None else week.team_played


def build_progress(
    pick: SeasonPick,
    rules: SeasonRules,
    today: datetime.date | None = None,
) -> SeasonPickProgress:
    by_week = {w.week: w for w in pick.weeks}
    total = sum(w.value or 0 for w in pick.weeks if w.played)

    games_elapsed = sum(1 for w in pick.weeks if team_played(w))
    open_through = latest_open_week(rules, today)
    missing = [wk for wk in range(1, open_through + 1) if wk not in by_week]

    return SeasonPickProgress(
        total=total,
        weeks_recorded=len(by_week),
        weeks_played=sum(1 for w in pick.weeks if w.played),
        games_elapsed=games_elapsed,
        missing_weeks=missing,
        next_week_to_enter=missing[0] if missing else None,
        # Two different clocks, deliberately. The season is over when every week is in;
        # what a team can still win depends on the games it has left, which is fewer.
        status=_status(
            pick, total,
            weeks_remaining=rules.weeks - len(by_week),
            games_remaining=rules.games - games_elapsed,
        ),
        weeks=sorted(
            (
                SeasonPickWeekProgress(
                    week=w.week, played=w.played, value=w.value, team_played=w.team_played,
                )
                for w in pick.weeks
            ),
            key=lambda w: w.week,
        ),
    )
