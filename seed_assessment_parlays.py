"""Seed BUILDING parlays to try pick assessments against. Local only.

Each gambler's pick is built from their own season so the assessment has something to
say: the prop type they take most, on a player they have taken it on before whose team
plays on the seed date, at their usual line and side. Dated 2026-10-11 because that slate
is captured in fixtures/espn with its odds and forecasts, so game context fills in fully
without a network call.

Three parlays: five picks, three picks, and two — the last to see the "needs 3 picks"
block. Ordered after everything else in the season, so the whole season is their history.

    uv run seed_assessment_parlays.py                 # 2025 season
    uv run seed_assessment_parlays.py --reset         # delete the ones it made, then reseed
"""
import argparse
import asyncio
import datetime
import math
import os
import statistics
import sys
from collections import Counter

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env")

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from database import async_session
from models import (
    Gambler, GamblingSeason, Parlay, ParlayState, Pick, PropBetType, SlateType,
)
from services.espn.client import fetch_slate_games

SEED_DATE = datetime.date(2026, 10, 11)
PARLAYS = [(SlateType.AFTERNOON_SLATE, 5), (SlateType.MORNING_SLATE, 3), (SlateType.SNF, 2)]


def refuse_unless_local() -> None:
    url = os.environ.get("DATABASE_URL", "")
    if "localhost" not in url and "127.0.0.1" not in url:
        sys.exit("Refusing: DATABASE_URL is not a local database.")


def candidates(gambler: Gambler, history: list[Parlay], playing: set[str]) -> list[dict]:
    """This gambler's likeliest bets on the seed slate, most characteristic first."""
    picks = [p for parlay in history for p in parlay.picks if p.gambler_id == gambler.id]
    by_prop = Counter(p.prop_type for p in picks if p.prop_type != PropBetType.TDS)
    out = []
    for rank, (prop_type, _) in enumerate(by_prop.most_common()):
        same_prop = [p for p in picks if p.prop_type == prop_type]
        by_target = Counter(
            p.prop_bet_target_id for p in same_prop
            if p.prop_bet_target.team_name in playing
        )
        for target_id, _ in by_target.most_common():
            on_target = [p for p in same_prop if p.prop_bet_target_id == target_id]
            out.append({
                "gambler_id": gambler.id,
                "prop_bet_target_id": target_id,
                "prop_type": prop_type,
                "rank": rank,
                # Snapped to the half point: a whole-number line could push.
                "line": math.floor(statistics.median(p.corrected_line or p.line for p in on_target)) + 0.5,
                "direction": Counter(p.direction for p in on_target).most_common(1)[0][0],
            })
    return out


async def main(year: int, reset: bool) -> int:
    refuse_unless_local()
    games = fetch_slate_games(SEED_DATE)
    if not games:
        print(f"No games found for {SEED_DATE} — is ESPN_FIXTURE_DIR set?")
        return 1
    playing = {team for g in games for team in g.teams}

    async with async_session() as db:
        season = (await db.execute(select(GamblingSeason).where(GamblingSeason.year == year))).scalar_one()

        if reset:
            seeded = select(Parlay.id).where(
                Parlay.gambling_season_id == season.id,
                Parlay.competition_date == SEED_DATE,
                Parlay.state == ParlayState.BUILDING,
            )
            ids = list((await db.execute(seeded)).scalars())
            await db.execute(delete(Pick).where(Pick.parlay_id.in_(ids)))
            await db.execute(delete(Parlay).where(Parlay.id.in_(ids)))
            await db.commit()
            print(f"deleted {len(ids)} seeded parlay(s): {ids}")

        gamblers = list((await db.execute(
            select(Gambler).where(Gambler.gambling_season_id == season.id).options(selectinload(Gambler.user))
        )).scalars())
        gamblers.sort(key=lambda g: g.user.first_name)
        history = list((await db.execute(
            select(Parlay)
            .where(Parlay.gambling_season_id == season.id, Parlay.state == ParlayState.CLOSED)
            .options(selectinload(Parlay.picks).joinedload(Pick.prop_bet_target))
        )).scalars().unique())
        order = (await db.execute(
            select(func.coalesce(func.max(Parlay.order), 0)).where(Parlay.gambling_season_id == season.id)
        )).scalar_one()

        options = {g.id: candidates(g, history, playing) for g in gamblers}

        for n, (slate_type, size) in enumerate(PARLAYS):
            order += 1
            parlay = Parlay(
                gambling_season_id=season.id, owner_id=gamblers[0].id, slate_type=slate_type,
                competition_date=SEED_DATE, state=ParlayState.BUILDING, wager_pp=10, order=order,
            )
            db.add(parlay)
            await db.flush()

            used: set[int] = set()
            print(f"\nparlay {parlay.id} — {slate_type.value}, {size} picks")
            for gambler in gamblers[:size]:
                # Each parlay leans on a different one of the gambler's habits — their most
                # common prop type on the first, second on the next — so the three differ.
                fresh = [c for c in options[gambler.id] if c["prop_bet_target_id"] not in used]
                if not fresh:
                    print(f"  {gambler.user.first_name}: nothing on this slate, skipped")
                    continue
                ranks = sorted({c["rank"] for c in fresh})
                wanted = ranks[min(n, len(ranks) - 1)]
                choice = {k: v for k, v in next(c for c in fresh if c["rank"] == wanted).items() if k != "rank"}
                used.add(choice["prop_bet_target_id"])
                pick = Pick(parlay_id=parlay.id, **choice)
                db.add(pick)
                await db.flush()
                await db.refresh(pick, ["prop_bet_target"])
                target = pick.prop_bet_target
                print(f"  {gambler.user.first_name}: {target.player_name or target.team_name} ({target.team_name}) "
                      f"{pick.direction.value} {pick.line:g} {pick.prop_type.value}")

        await db.commit()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--reset", action="store_true", help="delete parlays this made before seeding")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.year, args.reset)))
