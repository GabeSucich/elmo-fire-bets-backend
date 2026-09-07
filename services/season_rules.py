import datetime
from dataclasses import dataclass

from .score_correctors.score_corrector import GamblerScoreCorrector
from .score_correctors.score_corrector_2025 import GamblerScoreCorrector2025
from .score_correctors.score_corrector_2026 import GamblerScoreCorrector2026

# NFL regular season: 18 weeks, 17 games, one bye per team.
REGULAR_SEASON_WEEKS = 18

# An NFL week runs Tuesday to Monday. A week opens for entry on the Tuesday it starts,
# before its games are played — nothing is enterable yet, but the slot is there and the
# previous week is still open behind it. Anchoring on that Tuesday rather than on a fixed
# offset means a Wednesday or Thursday opener resolves to the same date either way.
TUESDAY = 1


@dataclass(frozen=True)
class SeasonRules:
    """Everything that varies year to year.

    The kickoff date lives here rather than on the season row for now: changing it
    is a deploy, but it keeps the migration smaller. Moving it to the database later
    is additive, with this as the fallback.
    """
    corrector: type[GamblerScoreCorrector]
    season_long_picks: bool = False
    pick_count: int = 10
    weeks: int = REGULAR_SEASON_WEEKS
    week_one_kickoff: datetime.date | None = None


SEASON_RULES: dict[int, SeasonRules] = {
    2025: SeasonRules(
        corrector=GamblerScoreCorrector2025,
        season_long_picks=False,
    ),
    2026: SeasonRules(
        corrector=GamblerScoreCorrector2026,
        season_long_picks=True,
        week_one_kickoff=datetime.date(2026, 9, 9),
    ),
}

DEFAULT_RULES = SeasonRules(corrector=GamblerScoreCorrector2025)

# ---------------------------------------------------------------------------
# TEMPORARY: pins the season clock so the season-picks UI can be seen mid-season
# before week one has actually opened. Set back to None before shipping.
# ---------------------------------------------------------------------------
WEEK_OVERRIDE: int | None = None


def get_season_rules(season_year: int) -> SeasonRules:
    return SEASON_RULES.get(season_year, DEFAULT_RULES)


def get_season_score_corrector_class(season_year: int) -> type[GamblerScoreCorrector]:
    return get_season_rules(season_year).corrector


def week_one_opens(rules: SeasonRules) -> datetime.date | None:
    """The Tuesday that week one starts on — the last Tuesday on or before kickoff."""
    if rules.week_one_kickoff is None:
        return None
    kickoff = rules.week_one_kickoff
    days_back = (kickoff.weekday() - TUESDAY) % 7
    return kickoff - datetime.timedelta(days=days_back)


def week_opens_on(rules: SeasonRules, week: int) -> datetime.date | None:
    """The first day a week's results can be entered, or None if the season has no
    kickoff date configured."""
    opening = week_one_opens(rules)
    if opening is None:
        return None
    return opening + datetime.timedelta(days=7 * (week - 1))


def latest_open_week(rules: SeasonRules, today: datetime.date | None = None) -> int:
    """The highest week whose results can be entered, or 0 before week one closes."""
    if WEEK_OVERRIDE is not None:
        return min(WEEK_OVERRIDE, rules.weeks)
    opening = week_one_opens(rules)
    if opening is None:
        return 0
    elapsed = ((today or datetime.date.today()) - opening).days
    if elapsed < 0:
        return 0
    return min(elapsed // 7 + 1, rules.weeks)
