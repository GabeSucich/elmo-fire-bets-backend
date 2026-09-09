"""Fill in ESPN numeric athlete ids on existing prop bet targets.

PropBetTarget stores ESPN's uuid, which is opaque: it cannot be searched on and every
stats endpoint rejects it. The numeric id is what those endpoints want, and the only way
back to it is a name search — so rows created before that column existed have to be
resolved one at a time.

Safe to re-run. Targets that already have an id are left alone, so a second pass only
retries the ones that failed.

    uv run backfill_espn_ids.py            # every player target
    uv run backfill_espn_ids.py --season 1 # only targets used by that season's picks
"""
import argparse
import asyncio
import sys

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session
from models import PropBetTarget, SeasonPick
from services.espn.client import find_athlete_id


async def targets_to_fill(db: AsyncSession, season_id: int | None) -> list[PropBetTarget]:
    query = select(PropBetTarget).where(
        PropBetTarget.espn_athlete_id.is_(None),
        # Team targets need no id at all — the schedule endpoint takes the abbreviation
        # that is already stored in team_name.
        PropBetTarget.player_name.is_not(None),
    )
    if season_id is not None:
        query = query.where(PropBetTarget.id.in_(
            select(SeasonPick.prop_bet_target_id).where(SeasonPick.gambling_season_id == season_id)
        ))
    return list((await db.execute(query)).scalars())


async def main(season_id: int | None) -> int:
    async with async_session() as db:
        targets = await targets_to_fill(db, season_id)
        print(f"{len(targets)} target(s) to resolve\n")

        failed: list[PropBetTarget] = []
        for i, target in enumerate(targets, 1):
            found = find_athlete_id(target.player_name)
            if found:
                target.espn_athlete_id = found
                print(f"  [{i}/{len(targets)}] {target.player_name} -> {found}")
            else:
                failed.append(target)
                print(f"  [{i}/{len(targets)}] {target.player_name} -> NOT FOUND")
            # Committed as we go: a run that dies partway keeps what it resolved rather
            # than making the next attempt start over.
            if i % 20 == 0:
                await db.commit()
        await db.commit()

        print(f"\nresolved {len(targets) - len(failed)}/{len(targets)}")
        if failed:
            # Named rather than counted: these are the ones a human has to look at, and a
            # retired or renamed player will never resolve no matter how often this runs.
            print("\nUnresolved — these need a manual id, or their picks stay manual:")
            for t in failed:
                print(f"  {t.player_name!r} (team {t.team_name}, uuid {t.identifier})")
        return len(failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=None,
                        help="only targets used by this season's picks")
    args = parser.parse_args()
    sys.exit(0 if asyncio.run(main(args.season)) == 0 else 1)
