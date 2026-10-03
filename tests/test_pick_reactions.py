"""Toggling an emoji on a pick, through the real endpoint function.

Plain behavioural cover: what comes back, what is written, what a second tap does.

It deliberately does NOT claim to cover the MissingGreenlet bug of 2026-10-02, where the
response read Pick.parlay after query_pick_with_selects had refreshed that instance
without it. That one cannot be reproduced here: ORM instances sit in reference cycles, so
until the cycle collector runs the orphaned Parlay is still alive in the session's weak
identity map and the lazy load is answered from memory without touching the database.
Every attempt to force it — a clean identity map, ids instead of objects, collecting on
commit, collecting on the Pick refresh — still passed against the broken code, which is
also why the bug reached production and behaved intermittently once there.

Postgres in production, SQLite here.
"""
import datetime
import os

# Set before the imports below: database.py reads DATABASE_URL at module scope and
# routers.auth reads SECRET. A URL is enough — create_async_engine does not connect, and
# every test here passes its own session, so the module-level engine is never used.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@localhost/unused")
os.environ.setdefault("SECRET", "unused-in-tests")

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import (
    Base,
    Gambler,
    GamblingSeason,
    GamblingSeasonState,
    Parlay,
    ParlayState,
    Pick,
    PickReaction,
    PropBetDirection,
    PropBetTarget,
    PropBetType,
    SlateType,
    User,
    PICK_REACTION_EMOJI,
)
from routers.pick_social import ReactionRequestData, react_to_pick

FIRE = PICK_REACTION_EMOJI[0]
CLOWN = PICK_REACTION_EMOJI[9]


@pytest.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db


@pytest.fixture
async def world(session):
    """One season, one gambler, one open parlay, one pick on it."""
    user = User(username="keith", password="x", first_name="Keith", last_name="K")
    season = GamblingSeason(year=2026, name="2026", state=GamblingSeasonState.IN_PROGRESS)
    session.add_all([user, season])
    await session.flush()

    gambler = Gambler(user_id=user.id, gambling_season_id=season.id)
    target = PropBetTarget(identifier="espn:1", player_name="Ja'Marr Chase", team_name="Bengals")
    session.add_all([gambler, target])
    await session.flush()

    parlay = Parlay(
        gambling_season_id=season.id,
        owner_id=gambler.id,
        slate_type=SlateType.SNF,
        competition_date=datetime.date(2026, 10, 4),
        state=ParlayState.OPEN,
        wager_pp=20.0,
        order=1,
    )
    session.add(parlay)
    await session.flush()

    pick = Pick(
        gambler_id=gambler.id,
        prop_bet_target_id=target.id,
        prop_type=PropBetType.REC_YDS,
        parlay_id=parlay.id,
        line=65.5,
        direction=PropBetDirection.OVER,
    )
    session.add(pick)
    await session.commit()

    ids = {
        "user_id": user.id,
        "gambler_id": gambler.id,
        "pick_id": pick.id,
        "parlay_id": parlay.id,
    }
    # Ids, never the ORM objects, and the user is re-fetched below. The identity map holds
    # its contents WEAKLY: the bug is a lazy load of Pick.parlay, and that load only has to
    # touch the database when nothing else still references the Parlay. A fixture handing
    # back the parlay object keeps it alive, the load is served from memory, and the test
    # passes against the broken code — which is exactly what this one did at first.
    session.expunge_all()
    return ids


async def react(world, emoji, db):
    """One request. The User is fetched per call, as a request's auth dependency does."""
    user = (await db.execute(select(User).where(User.id == world["user_id"]))).scalar_one()
    return await react_to_pick(
        world["pick_id"], ReactionRequestData(emoji=emoji), user=user, db=db)


async def test_reacting_returns_the_pick(session, world):
    res = await react(world, FIRE, session)

    assert res.pick.id == world["pick_id"]
    assert [(r.emoji, r.gambler_ids) for r in res.pick.reactions] == [(FIRE, [world["gambler_id"]])]


async def test_the_reaction_is_actually_saved(session, world):
    await react(world, FIRE, session)

    rows = (await session.execute(PickReaction.__table__.select())).all()
    assert len(rows) == 1


async def test_tapping_the_same_emoji_again_takes_it_back(session, world):
    await react(world, FIRE, session)
    res = await react(world, FIRE, session)

    assert res.pick.reactions == []
    rows = (await session.execute(PickReaction.__table__.select())).all()
    assert rows == []


async def test_a_second_emoji_stands_alongside_the_first(session, world):
    await react(world, CLOWN, session)
    res = await react(world, FIRE, session)

    # Palette order, not the order they were tapped — see summarize_reactions.
    assert [r.emoji for r in res.pick.reactions] == [FIRE, CLOWN]
