"""Reading an open parlay's picks off the live boxscore.

Deliberately separate from the season pick sync. That one asks what a player has done all
year; this one asks what is happening in one slate, right now, and answers per pick rather
than per week.

Nothing here writes Pick.result. A void, a push and a bozo are judgements about a bet that
no feed can make, and a settled result someone entered by hand must never be overwritten by
a number scraped mid-game.
"""
import asyncio
import datetime
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Parlay, Pick, PropBetTarget
from .client import SlateGame, fetch_boxscore, fetch_slate_games
from .gamelog import GameStats
from .stats import NOT_IN_BOXSCORE, resolve, supported

logger = logging.getLogger(__name__)


def _utc_now() -> datetime.datetime:
    """Naive UTC, matching the timestamps the rest of the schema stores."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

# A parlay's legs cluster into a handful of games, so this is nearly always the whole slate
# a single press needs. Same neighbourliness as the rest of this package.
FETCH_CONCURRENCY = 4


@dataclass
class ProgressReport:
    """What one press of sync managed, in enough detail to tell working from silent."""
    parlay_id: int
    picks_seen: int = 0
    picks_synced: int = 0
    skipped: list[str] = field(default_factory=list)

    def skip(self, pick: Pick, why: str) -> None:
        """Why one leg could not be read, in words the person who pressed sync can act on.

        A pick id tells them nothing. Which player, and which of the several quite
        different things went wrong, tells them whether to fix the lay's date, wait, or
        press again.
        """
        target = pick.prop_bet_target
        who = target.player_name or target.team_name or f"pick {pick.id}"
        self.skipped.append(f"{who}: {why}")


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


def stat_line(
    target: PropBetTarget, box: dict[str, dict[str, dict[str, str]]], game: SlateGame,
) -> GameStats | None:
    """One target's stats out of a game's boxscore.

    A team target — a field goals bet — has no athlete to look up, so its line is every
    kicker the team used, merged. Two kickers in one game is rare and daft, but summing
    what they made is still the right answer where taking the first is not.
    """
    players = box.get(target.team_name or "") or {}

    if target.player_name:
        values = players.get(target.espn_athlete_id or "")
        return GameStats(week=0, event_id=game.event_id, values=values) if values else None

    made = 0.0
    kicked = False
    for values in players.values():
        stats = GameStats(week=0, event_id=game.event_id, values=values)
        scored = stats.made_of("fieldGoalsMade-fieldGoalAttempts")
        if scored is not None:
            made += scored
            kicked = True

    if not kicked:
        return None
    # Rebuilt as a made-attempts pair so it reads back through the same path every other
    # kicking stat does. Attempts are not summed: nothing bets on them.
    return GameStats(
        week=0, event_id=game.event_id,
        values={"fieldGoalsMade-fieldGoalAttempts": f"{made:g}-0"},
    )


async def sync_parlay_progress(parlay_id: int, db: AsyncSession) -> ProgressReport:
    """Bring one parlay's picks up to date with what is happening on the field."""
    report = ProgressReport(parlay_id=parlay_id)

    parlay = (await db.execute(
        select(Parlay)
        .where(Parlay.id == parlay_id)
        .options(selectinload(Parlay.picks).selectinload(Pick.prop_bet_target))
    )).scalar_one_or_none()
    if parlay is None:
        report.skipped.append(f"parlay {parlay_id} does not exist")
        return report

    games = fetch_slate_games(parlay.competition_date)
    if games is None:
        report.skipped.append("ESPN was unreachable — try again")
        return report

    # Only the games this parlay actually touches, fetched once each however many legs sit
    # on them — a five-leg parlay is very often two or three fixtures, not five.
    needed = {
        g.event_id
        for pick in parlay.picks
        if (g := game_for(pick.prop_bet_target, games)) is not None
    }
    semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def bounded(event_id: str):
        async with semaphore:
            return event_id, await asyncio.to_thread(fetch_boxscore, event_id)

    boxscores = dict(await asyncio.gather(*[bounded(e) for e in needed]))

    for pick in parlay.picks:
        report.picks_seen += 1
        target = pick.prop_bet_target

        game = game_for(target, games)
        if game is None:
            # Overwhelmingly a lay whose date does not match when the team actually
            # played, which is a thing to go and fix rather than to retry.
            report.skip(pick, f"{target.team_name} had no game on "
                              f"{parlay.competition_date.strftime('%m/%d')}")
            continue

        # Recorded even before kickoff, and that is the point: it is what lets a card say
        # "yet to start" rather than showing a zero nobody has earned yet.
        pick.live_state = game.state
        pick.live_detail = game.detail
        pick.live_synced_at = _utc_now()

        if game.state == "pre":
            pick.live_value = None
            report.picks_synced += 1
            continue

        if not supported(pick.prop_type):
            report.skip(pick, f"{pick.prop_type} cannot be read live")
            continue

        box = boxscores.get(game.event_id)
        if box is None:
            # Transient, unlike the two above: ESPN was unreachable or answered oddly, and
            # pressing again is the right response.
            report.skip(pick, "ESPN did not return a boxscore — try again")
            continue

        line = stat_line(target, box, game)
        if line is None:
            # Left alone rather than zeroed. A player absent from the boxscore has not
            # taken the field, which is not the same as having done nothing — and the
            # pick is usually voided rather than lost.
            pick.live_value = None
        else:
            value = resolve(pick.prop_type, line)
            # He is out there and has none of it yet, which is a zero. The same reading the
            # season sync takes: a receiver with no carries really has run for nothing.
            # Except where the boxscore simply does not carry the market, where a zero
            # would be a number nobody measured.
            pick.live_value = (
                value if value is not None
                else None if pick.prop_type in NOT_IN_BOXSCORE
                else 0.0
            )
        report.picks_synced += 1

    await db.commit()
    logger.info(
        "parlay %s progress: %d/%d picks, %d skipped",
        parlay_id, report.picks_synced, report.picks_seen, len(report.skipped),
    )
    return report
