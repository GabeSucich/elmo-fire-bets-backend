"""Reading an open parlay's picks off the live boxscore.

Deliberately separate from the season pick sync. That one asks what a player has done all
year; this one asks what is happening in one slate, right now, and answers per pick rather
than per week.

Once a game is final, a leg the boxscore can answer is settled here too: Win, Loss or
Push, read straight off the number against the line. Everything that needs judgement stays
with a person. A player missing from a finished boxscore is most likely a void, so it is
left unsettled; a result already entered is never overwritten; and BOZO is decided when
the parlay is finalized, from all the legs together, exactly as for a result entered by
hand.
"""
import asyncio
import datetime
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Parlay, Pick, PickResult, PropBetDirection, PropBetTarget, PropBetType
from utils.parlays import apply_pick_result
from .client import SlateGame, fetch_boxscore, fetch_slate_games
from .game_context import apply_game_context, game_for
from .sync import athlete_id_for
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
    # Legs given a result because their game went final during this press.
    picks_settled: int = 0
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


def live_value_for(
    prop_type: PropBetType, line: GameStats | None, game_state: str,
) -> float | None:
    """What a leg reads, given whatever the boxscore had to say about its player.

    Three different kinds of nothing, which the numbers cannot tell apart:

    A player absent from the boxscore entirely. A boxscore lists only those who have
    recorded something, so what that means depends on whether there is still time to
    record it — ten minutes in, a receiver who has not been thrown at yet is simply on
    nought, and showing no bar at all reads as one that is broken rather than a bet that
    has not started moving. Once the game is over the same absence means he never took the
    field, which is a void rather than a nought, and stays unanswered.

    A player who is there with no line for this stat — a receiver with no carries — really
    has run for nothing. The same reading the season pick sync takes.

    A market the boxscore does not carry at all, where a nought would be a number nobody
    measured.
    """
    if line is None:
        return 0.0 if game_state == "in" else None

    value = resolve(prop_type, line)
    if value is not None:
        return value
    return None if prop_type in NOT_IN_BOXSCORE else 0.0


def result_from_final(pick: Pick, value: float) -> PickResult:
    """The gambler's call against the final number: the line that was actually bet, and
    the side they called — a veto is carried onto its own result by apply_pick_result,
    the same as when a person enters one."""
    line = pick.corrected_line if pick.corrected_line is not None else pick.line
    if value == line:
        return PickResult.PUSH
    went_over = value > line
    called_over = pick.direction == PropBetDirection.OVER
    return PickResult.WIN if went_over == called_over else PickResult.LOSS


def settle_if_final(pick: Pick, game_state: str) -> bool:
    """Give a leg its result if its game is over and the boxscore answered. True if set."""
    if game_state != "post" or pick.result is not None or pick.live_value is None:
        return False
    apply_pick_result(pick, result_from_final(pick, pick.live_value))
    return True


async def sync_parlay_progress(parlay_id: int, db: AsyncSession) -> ProgressReport:
    """Bring one parlay's picks up to date with what is happening on the field."""
    report = ProgressReport(parlay_id=parlay_id)

    parlay = (await db.execute(
        select(Parlay)
        .where(Parlay.id == parlay_id)
        .options(selectinload(Parlay.picks).selectinload(Pick.prop_bet_target))
        # Settling a leg carries its result onto an approved veto.
        .options(selectinload(Parlay.picks).selectinload(Pick.vetoes))
    )).scalar_one_or_none()
    if parlay is None:
        report.skipped.append(f"parlay {parlay_id} does not exist")
        return report

    games = fetch_slate_games(parlay.competition_date)
    if games is None:
        report.skipped.append("ESPN was unreachable — try again")
        return report

    # Before the boxscores, because a player is found in one by his numeric id and a target
    # created through the app arrives without it. Writing, so it is sequential — and after
    # the first pass on a given player there is nothing left to do.
    for pick in parlay.picks:
        target = pick.prop_bet_target
        if target.player_name and not target.espn_athlete_id:
            await athlete_id_for(target, db)

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

        # The slate is already in hand, so pick assessments get their game context for free.
        apply_game_context(pick, game)

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

        # Nothing to look him up by, and the attempt above did not find one. Said out loud
        # rather than left as an empty bar: this reads as progress that will not update,
        # which is indistinguishable from a player who has simply not done anything yet.
        if target.player_name and not target.espn_athlete_id:
            report.skip(pick, f"{target.player_name} could not be matched on ESPN")
            continue

        box = boxscores.get(game.event_id)
        if box is None:
            # Transient, unlike the two above: ESPN was unreachable or answered oddly, and
            # pressing again is the right response.
            report.skip(pick, "ESPN did not return a boxscore — try again")
            continue

        pick.live_value = live_value_for(pick.prop_type, stat_line(target, box, game), game.state)
        if settle_if_final(pick, game.state):
            report.picks_settled += 1
        report.picks_synced += 1

    await db.commit()
    logger.info(
        "parlay %s progress: %d/%d picks, %d settled, %d skipped",
        parlay_id, report.picks_synced, report.picks_seen, report.picks_settled, len(report.skipped),
    )
    return report
