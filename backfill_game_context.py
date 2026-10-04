"""Fill in game context — home or away, opponent, kickoff, final score — on past picks.

Pick assessments read a gambler's history with the game each pick was on, and picks made
before that existed have none. ESPN is free and this is one scoreboard per distinct date,
so a whole season is a few dozen calls.

The market around a game (spread, total, weather) is not recoverable this way: ESPN stops
publishing it at kickoff. Those stay null on everything this fills.

Player picks are matched by the player's own gamelog rather than by his target's team,
which the player sync relabels to wherever he plays now — matching on it puts a traded
player's old picks on the wrong game. That costs one gamelog per player, once.

Dry run unless --apply is given, so the unmatched list can be looked at first. A pick goes
unmatched when the player has no game that day (inactive, or the parlay is filed under the
wrong date) or a team target's team did not play. Neither is guessed at.

Safe to re-run: a pick whose game is already final is skipped without a fetch.

    uv run backfill_game_context.py               # the season in progress, dry run
    uv run backfill_game_context.py --apply
    uv run backfill_game_context.py --season 2 --apply
"""
import argparse
import asyncio

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env")

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database import async_session
from models import GamblingSeason, GamblingSeasonState, Parlay, Pick
from services.espn.game_context import fill_game_context


async def main(season_id: int | None, apply: bool) -> int:
    async with async_session() as db:
        if season_id is None:
            season = (await db.execute(
                select(GamblingSeason).where(GamblingSeason.state == GamblingSeasonState.IN_PROGRESS)
            )).scalars().first()
            if season is None:
                print("No season in progress; pass --season.")
                return 1
            season_id = season.id

        parlays = list((await db.execute(
            select(Parlay)
            .where(Parlay.gambling_season_id == season_id)
            .options(selectinload(Parlay.picks).selectinload(Pick.prop_bet_target))
        )).scalars())

        report = await fill_game_context(parlays, verify_with_gamelog=True)

        print(f"season {season_id}: {len(parlays)} parlays, {report.picks_seen} picks needing context")
        print(f"  {report.picks_changed} would change" if not apply else f"  {report.picks_changed} changed")
        if report.unreachable_dates:
            print(f"  ESPN unreachable for: {', '.join(d.isoformat() for d in report.unreachable_dates)}")
        if report.unmatched:
            print(f"  {len(report.unmatched)} unmatched:")
            for line in report.unmatched:
                print(f"    {line}")

        if apply:
            await db.commit()
            print("committed")
        else:
            await db.rollback()
            print("dry run — nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", type=int, help="gambling season id; defaults to the one in progress")
    parser.add_argument("--apply", action="store_true", help="write the changes")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.season, args.apply)))
