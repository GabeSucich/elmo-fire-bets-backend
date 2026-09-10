"""Filling in season pick results from ESPN.

Reads every season pick in a season, asks ESPN what actually happened each week, and
writes it into SeasonPickWeek. ESPN is treated as the source of truth: a week it can
answer is overwritten even if someone entered it by hand, so the two can never disagree.

A week it *cannot* answer is left exactly as it was. That is the important half — an
unmappable prop, a name that no longer resolves, or an outage must never turn a real
entered value into a zero or wipe it out.
"""
import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import (
    GamblingSeason,
    PropBetTarget,
    SeasonPick,
    SeasonPickKind,
    SeasonPickWeek,
)
from .client import fetch_gamelog, fetch_team_results, find_athlete_id
from .stats import resolve, supported

logger = logging.getLogger(__name__)


@dataclass
class SyncReport:
    """What the sweep did, in enough detail to tell working from silently doing nothing."""
    season_id: int
    picks_seen: int = 0
    picks_synced: int = 0
    weeks_written: int = 0
    weeks_updated: int = 0
    skipped: list[str] = field(default_factory=list)

    def skip(self, pick: SeasonPick, why: str) -> None:
        self.skipped.append(f"pick {pick.id}: {why}")


async def athlete_id_for(target: PropBetTarget, db: AsyncSession) -> str | None:
    """ESPN's numeric id for a target, looked up by name and remembered if it is missing.

    backfill_espn_ids.py is the main route — resolving up front gives a list of names that
    failed while there is still time to look at them, rather than discovering it mid-sweep.
    This is the safety net for whatever it did not cover: a target created before the
    column existed, one added while ESPN was unreachable, or a row the backfill has simply
    not been run against yet.

    The result is written back, so a name search is paid at most once per target however
    many weeks or syncs follow.
    """
    if target.espn_athlete_id:
        return target.espn_athlete_id
    if not target.player_name:
        return None

    found = find_athlete_id(target.player_name)
    if found:
        target.espn_athlete_id = found
        await db.commit()
    return found


def upsert_week(
    pick: SeasonPick, week: int, played: bool, value: float | None,
    existing: dict[int, SeasonPickWeek], report: SyncReport, db: AsyncSession,
    team_played: bool | None = None,
) -> None:
    row = existing.get(week)
    if row is None:
        db.add(SeasonPickWeek(
            season_pick_id=pick.id, week=week, played=played,
            value=value, team_played=team_played,
        ))
        report.weeks_written += 1
        return
    # ESPN wins over whatever was there, including a manual entry — but only when it has
    # an answer at all. Callers never reach here with an unknown value.
    if row.played != played or row.value != value or row.team_played != team_played:
        row.played, row.value, row.team_played = played, value, team_played
        report.weeks_updated += 1


# Enough to make a league's worth of picks finish inside one request, low enough to stay a
# polite neighbour to a public API nobody is paying for.
FETCH_CONCURRENCY = 6


async def gather_espn_data(
    picks: list[SeasonPick], season_year: int, report: SyncReport, db: AsyncSession,
) -> tuple[dict[str, object], dict[str, dict[int, float]]]:
    """Fetch each distinct player and team once, in parallel.

    Keyed on the target rather than the pick: five gamblers backing the same team is one
    schedule, not five. That alone is most of the difference between this finishing inside
    a request and not.
    """
    athlete_ids: set[str] = set()
    team_abbrs: set[str] = set()

    for pick in picks:
        if pick.kind is SeasonPickKind.TEAM_WINS:
            if pick.prop_bet_target.team_name:
                team_abbrs.add(pick.prop_bet_target.team_name)
            continue
        if pick.prop_type is None or not supported(pick.prop_type):
            continue
        # Player props need the schedule too, to tell a week the player missed from one
        # nobody played. Same set as the team picks, so a player on a team somebody has
        # backed outright costs no extra call.
        if pick.prop_bet_target.team_name:
            team_abbrs.add(pick.prop_bet_target.team_name)
        # Sequential and before the parallel phase, because it writes: a target that has
        # to be resolved by name gets its id saved, and after the first sync there are
        # none of these left to do.
        athlete_id = await athlete_id_for(pick.prop_bet_target, db)
        if athlete_id:
            athlete_ids.add(athlete_id)

    semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def bounded(fn, key):
        async with semaphore:
            # requests is blocking, so each call gets a thread; the semaphore is what keeps
            # that from becoming a thread per target.
            return key, await asyncio.to_thread(fn, key, season_year)

    results = await asyncio.gather(
        *[bounded(fetch_gamelog, a) for a in athlete_ids],
        *[bounded(fetch_team_results, t) for t in team_abbrs],
    )

    logs = {k: v for k, v in results if k in athlete_ids}
    schedules = {k: v for k, v in results if k in team_abbrs}
    return logs, schedules


def apply_weeks(
    pick: SeasonPick, played: dict[int, float], existing: dict[int, SeasonPickWeek],
    report: SyncReport, db: AsyncSession, team_weeks: set[int] | None = None,
) -> None:
    """Write the weeks that happened, and mark the gaps below them as not played.

    `team_weeks` is every week the team has actually completed a game in. With it, a week
    the player is missing from is either a game they sat out or a bye, and the two are
    recorded differently — which is the whole point, since only one of them spends a game.
    Without it nothing is claimed either way and team_played stays null.
    """
    # A game the player recorded proves the team played it, schedule or no schedule.
    for week, value in played.items():
        upsert_week(pick, week, True, value, existing, report, db, team_played=True)

    # The schedule reaches further than the gamelog whenever the player missed the most
    # recent games, so it sets how far to walk. Falling back to the gamelog's own last
    # week keeps a season in progress from filling with byes for games not yet played.
    last = max(played, default=0)
    if team_weeks:
        last = max(last, max(team_weeks))
    for week in range(1, last + 1):
        if week not in played:
            upsert_week(pick, week, False, None, existing, report, db,
                        team_played=None if team_weeks is None else week in team_weeks)


async def sync_season_picks(season_id: int, db: AsyncSession) -> SyncReport:
    """Bring every season pick in one season up to date with ESPN."""
    report = SyncReport(season_id=season_id)

    season = (await db.execute(
        select(GamblingSeason).where(GamblingSeason.id == season_id)
    )).scalar_one_or_none()
    if season is None:
        report.skipped.append(f"season {season_id} does not exist")
        return report

    picks = list((await db.execute(
        select(SeasonPick)
        .where(SeasonPick.gambling_season_id == season_id)
        .options(selectinload(SeasonPick.prop_bet_target))
        .options(selectinload(SeasonPick.weeks))
    )).scalars())

    logs, schedules = await gather_espn_data(picks, season.year, report, db)

    for pick in picks:
        report.picks_seen += 1
        existing = {w.week: w for w in pick.weeks}
        target = pick.prop_bet_target

        if pick.kind is SeasonPickKind.TEAM_WINS:
            results = schedules.get(target.team_name)
            if results is None:
                report.skip(pick, f"ESPN schedule unavailable for {target.team_name}")
                continue
            apply_weeks(pick, results, existing, report, db, set(results))
        else:
            if pick.prop_type is None or not supported(pick.prop_type):
                report.skip(pick, f"prop type {pick.prop_type} has no ESPN equivalent")
                continue
            log = logs.get(target.espn_athlete_id or "")
            if log is None:
                report.skip(pick, f"no ESPN gamelog for {target.player_name!r}")
                continue
            # A player who appeared but has no line for this stat — a receiver with no
            # rushing attempts — really did record zero, so that is not a gap.
            values = {g.week: (resolve(pick.prop_type, g) or 0.0) for g in log}
            # None rather than an empty set when the schedule is missing: an empty set
            # would assert the team has played nothing, which is a much stronger claim.
            schedule = schedules.get(target.team_name or "")
            team_weeks = set(schedule) if schedule is not None else None
            apply_weeks(pick, values, existing, report, db, team_weeks)

        report.picks_synced += 1

    await db.commit()
    logger.info(
        "season %s sync: %d/%d picks, %d weeks written, %d updated, %d skipped",
        season_id, report.picks_synced, report.picks_seen,
        report.weeks_written, report.weeks_updated, len(report.skipped),
    )
    return report
