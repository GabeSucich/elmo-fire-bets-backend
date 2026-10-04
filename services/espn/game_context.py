"""Recording which game each pick was on, for pick assessments.

A pick says who the bet is on and never which fixture, so whether it was a home game, who
the opponent was and when it kicked off all have to be worked out from the scoreboard for
the parlay's date.

Matched by the team on the pick's target wherever that team is current — a parlay being
built, synced or closed. That is every caller except the backfill: assessment generation
(the only one that reaches a parlay still being built), the progress sync (which has the
slate already), and closing a parlay (which catches the final score on parlays nobody
synced). PropBetTarget.team_name is the team a player is at *now*, so for history it is
wrong for anyone traded since; backfill_game_context.py passes verify_with_gamelog and
matches on the player's own record of where he played instead. Measured on the 2025
season, team matching put 33 of 736 picks on a real game the player was not in.

What is written follows from what an assessment hashes. Static fields are written once,
since the schedule does not move; the market (spread, total, weather) is refreshed only
until kickoff, after which ESPN stops publishing it anyway; the score is written once the
game is final. Each field therefore changes a bounded number of times, and an assessment
run twice against the same picks sees the same input the second time.
"""
import asyncio
import datetime
import logging
from dataclasses import dataclass, field

from models import Parlay, Pick, PropBetTarget
from .client import SlateGame, fetch_athlete_teams, fetch_slate_games

logger = logging.getLogger(__name__)


@dataclass
class GameContextReport:
    picks_seen: int = 0
    picks_changed: int = 0
    # Most often a target whose team has been relabeled since the pick was made — the
    # player sync rewrites a shared PropBetTarget to the club the player is at now — or a
    # parlay filed under the wrong date. Left null rather than guessed at.
    unmatched: list[str] = field(default_factory=list)
    unreachable_dates: list[datetime.date] = field(default_factory=list)


def game_for(target: PropBetTarget, games: list[SlateGame]) -> SlateGame | None:
    """The game a target is playing in on this slate, found by its team.

    Team is the only link available: a pick records who the bet is on, never which fixture.
    That makes the team on a target load-bearing rather than decorative — a player whose
    club is a season out of date is matched to the wrong game or to none at all, which is
    what the admin player sync exists to prevent.
    """
    if not target.team_name:
        return None
    return next((g for g in games if target.team_name in g.teams), None)


def needs_game_context(pick: Pick) -> bool:
    """Whether the scoreboard still has anything to tell this pick.

    A final score is the last thing written, so a pick that has one is finished with.
    """
    return pick.game_event_id is None or pick.game_team_score is None


def apply_game_context(pick: Pick, game: SlateGame, team: str | None = None) -> bool:
    """Write what the scoreboard says about a pick's game. True if anything changed.

    `team` is the side the pick is on, where it is known better than the target's current
    team — for history, from the player's gamelog.
    """
    team = team or pick.prop_bet_target.team_name
    side = game.side(team) if team else None
    opponent = game.opponent_of(team) if team else None
    before = _snapshot(pick)

    if pick.game_event_id != game.event_id:
        # Unset, or a different game altogether — the parlay's date was corrected, or the
        # team on the target was. Either way what was stored described the wrong fixture,
        # so the market and score go with it rather than lingering against the new one.
        pick.game_event_id = game.event_id
        pick.game_team = side.abbreviation if side else None
        pick.game_kickoff_at = game.kickoff_at
        pick.game_week = game.week
        pick.game_indoor = game.indoor
        pick.game_neutral_site = game.neutral_site
        pick.game_is_home = side.is_home if side else None
        pick.game_opponent = opponent.abbreviation if opponent else None
        pick.game_team_spread = None
        pick.game_total = None
        pick.game_weather = None
        pick.game_team_score = None
        pick.game_opponent_score = None

    if game.state == "pre":
        # Only ever overwritten with a value: ESPN dropping the odds for an hour is not the
        # market disappearing, and the last real line is the better thing to keep.
        spread = game.spread_for(team) if team else None
        if spread is not None:
            pick.game_team_spread = spread
        if game.total is not None:
            pick.game_total = game.total
        if game.weather is not None:
            pick.game_weather = game.weather

    if game.state == "post" and side and opponent and pick.game_team_score is None:
        pick.game_team_score = side.score
        pick.game_opponent_score = opponent.score

    return _snapshot(pick) != before


def _snapshot(pick: Pick) -> tuple:
    return (
        pick.game_event_id, pick.game_team, pick.game_kickoff_at, pick.game_week, pick.game_is_home,
        pick.game_opponent, pick.game_indoor, pick.game_neutral_site,
        pick.game_team_score, pick.game_opponent_score,
        pick.game_team_spread, pick.game_total, pick.game_weather,
    )


def nfl_season(date: datetime.date) -> int:
    """The season a date belongs to: January and February playoffs are the year before."""
    return date.year if date.month >= 3 else date.year - 1


def _who(pick: Pick) -> str:
    target = pick.prop_bet_target
    who = target.player_name or target.team_name or f"pick {pick.id}"
    return f"{who} ({target.team_name}), pick {pick.id}"


def apply_slate(
    picks: list[Pick], games: list[SlateGame], report: GameContextReport,
    athlete_teams: dict[str, dict[str, str] | None] | None = None,
) -> None:
    """Match each pick to its game on the slate and record it.

    With athlete_teams, a player pick on a finished game is matched by where the player
    actually played. No entry for him on the slate means he did not play, or the target is
    not who we think — either way the target's team cannot be trusted for this date, so
    nothing is written. Games not yet over are not in a gamelog and fall back to the team,
    which for a game still to be played is the current one and so the right one.
    """
    by_event = {g.event_id: g for g in games}
    for pick in picks:
        report.picks_seen += 1
        target = pick.prop_bet_target
        game, team = None, None

        teams_played = (athlete_teams or {}).get(target.espn_athlete_id or "")
        if athlete_teams is not None and target.player_name and teams_played is not None:
            event_id = next((e for e in teams_played if e in by_event), None)
            if event_id is not None:
                game, team = by_event[event_id], teams_played[event_id]
            else:
                by_team = game_for(target, games)
                if by_team is not None and by_team.state != "post":
                    game = by_team
        else:
            game = game_for(target, games)

        if game is None:
            report.unmatched.append(_who(pick))
            continue
        if apply_game_context(pick, game, team):
            report.picks_changed += 1


# Same neighbourliness as the rest of this package.
FETCH_CONCURRENCY = 4


async def fill_game_context(parlays: list[Parlay], verify_with_gamelog: bool = False) -> GameContextReport:
    """Bring these parlays' picks up to date with the scoreboard. Does not commit.

    Parlays must have picks and their targets loaded. One scoreboard per distinct date,
    and none at all for a date whose picks are all already final. verify_with_gamelog adds
    one gamelog per player per season, which is what makes matching history trustworthy and
    is too many calls for anything but the backfill.
    """
    report = GameContextReport()

    by_date: dict[datetime.date, list[Pick]] = {}
    for parlay in parlays:
        pending = [p for p in parlay.picks if needs_game_context(p)]
        if pending:
            by_date.setdefault(parlay.competition_date, []).extend(pending)

    semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def bounded(fn, *args):
        async with semaphore:
            # requests is blocking, so each call gets a thread.
            return args, await asyncio.to_thread(fn, *args)

    slates = await asyncio.gather(*[bounded(fetch_slate_games, d) for d in by_date])

    athlete_teams: dict[int, dict[str, dict[str, str] | None]] = {}
    if verify_with_gamelog:
        wanted = {
            (pick.prop_bet_target.espn_athlete_id, nfl_season(date))
            for date, picks in by_date.items() for pick in picks
            if pick.prop_bet_target.player_name and pick.prop_bet_target.espn_athlete_id
        }
        for (athlete_id, season), teams in await asyncio.gather(
            *[bounded(fetch_athlete_teams, a, s) for a, s in wanted]
        ):
            athlete_teams.setdefault(season, {})[athlete_id] = teams

    for (date,), games in slates:
        if games is None:
            report.unreachable_dates.append(date)
            continue
        apply_slate(
            by_date[date], games, report,
            athlete_teams.get(nfl_season(date), {}) if verify_with_gamelog else None,
        )

    if report.unmatched or report.unreachable_dates:
        logger.info(
            "game context: %d/%d changed, unmatched %s, unreachable %s",
            report.picks_changed, report.picks_seen, report.unmatched, report.unreachable_dates,
        )
    return report
