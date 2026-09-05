"""Seed a single gambling season and its gamblers, without touching existing data.

Unlike seed.py, this script never drops tables and never seeds parlays. Every step
is a get-or-create, so it is safe to re-run against a database that is already
partially set up.
"""

import argparse
import asyncio
import sys

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

load_dotenv(".env")

from database import async_session
from models import Gambler, GamblingSeason, GamblingSeasonState, User
from seed import users_and_passwords
from utils.auth import hash_password
from utils.env_vars import load_env_var, EnvVarName

DATABASE_URL = load_env_var(EnvVarName.DATABASE_URL)

DEFAULT_YEAR = 2026


async def get_or_create_users(session: AsyncSession) -> list[User]:
    """Ensure every user in the seed roster exists, matched on username.

    Existing users are left completely untouched — in particular their password is
    never reset, so running this against a real database cannot clobber a login.
    """
    users: list[User] = []
    for username, (password, first_name, last_name) in users_and_passwords.items():
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                username=username,
                password=hash_password(password),
                first_name=first_name,
                last_name=last_name,
            )
            session.add(user)
            await session.flush()
            print(f"  + created user {username!r} (id={user.id})")
        else:
            print(f"  = user {username!r} already exists (id={user.id}), left untouched")
        users.append(user)
    return users


async def get_or_create_season(session: AsyncSession, name: str, year: int) -> GamblingSeason:
    """Get or create the season, matched on (name, year)."""
    result = await session.execute(
        select(GamblingSeason).where(GamblingSeason.name == name, GamblingSeason.year == year)
    )
    seasons = result.scalars().all()
    if len(seasons) > 1:
        raise ValueError(
            f"Found {len(seasons)} seasons matching name={name!r} year={year} "
            f"(ids={[s.id for s in seasons]}). Resolve the duplicates before seeding."
        )
    if seasons:
        season = seasons[0]
        print(f"  = season {name!r} ({year}) already exists (id={season.id}, state={season.state})")
        if season.state != GamblingSeasonState.IN_PROGRESS:
            print(
                f"  ! WARNING: existing season state is {season.state}, not "
                f"{GamblingSeasonState.IN_PROGRESS}. Leaving it as-is."
            )
        return season

    season = GamblingSeason(name=name, year=year, state=GamblingSeasonState.IN_PROGRESS)
    session.add(season)
    await session.flush()
    print(f"  + created season {name!r} ({year}) (id={season.id}, state={season.state})")
    return season


async def get_or_create_gamblers(
    session: AsyncSession, users: list[User], season: GamblingSeason
) -> list[Gambler]:
    """Ensure each user has a gambler in this season, matched on (user_id, season_id)."""
    gamblers: list[Gambler] = []
    for user in users:
        result = await session.execute(
            select(Gambler).where(
                Gambler.user_id == user.id, Gambler.gambling_season_id == season.id
            )
        )
        gambler = result.scalars().first()
        if gambler is None:
            gambler = Gambler(user_id=user.id, gambling_season_id=season.id)
            session.add(gambler)
            await session.flush()
            print(f"  + created gambler for {user.username!r} (id={gambler.id})")
        else:
            print(f"  = gambler for {user.username!r} already exists (id={gambler.id})")
        gamblers.append(gambler)
    return gamblers


async def run_seed_season(name: str, year: int):
    # One session, one commit: either the whole season lands or none of it does.
    async with async_session() as session:
        print("Users:")
        users = await get_or_create_users(session)
        print("Season:")
        season = await get_or_create_season(session, name, year)
        print("Gamblers:")
        gamblers = await get_or_create_gamblers(session, users, season)
        await session.commit()

    print(f"\nDone. Season {season.name!r} (id={season.id}) has {len(gamblers)} gamblers.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed a single gambling season and its gamblers.")
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR, help=f"Season year (default: {DEFAULT_YEAR})")
    parser.add_argument("--name", default=None, help='Season name (default: "EF Boys <year>")')
    args = parser.parse_args()

    name = args.name if args.name is not None else f"EF Boys {args.year}"

    if "localhost" not in DATABASE_URL:
        x = input(f"You are running this against non-dev DB url {DATABASE_URL}. Is this your intention? (Y/N)")
        if x.strip().lower() != "y":
            sys.exit(1)

    asyncio.run(run_seed_season(name, args.year))
