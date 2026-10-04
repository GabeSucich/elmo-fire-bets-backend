"""A sync that finds a game final gives its legs their results.

Against the captured NE @ SEA final of 2026-09-09: Jaxon Smith-Njigba finished with 122
receiving yards, and Drake Maye with 178 passing yards on 23 completions.

Postgres in production, SQLite here.
"""
import datetime
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@localhost/unused")
os.environ.setdefault("SECRET", "unused-in-tests")

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import (
    Base, Gambler, GamblingSeason, GamblingSeasonState, Parlay, ParlayState, Pick, PickResult,
    PickVeto, PropBetDirection, PropBetTarget, PropBetType, SlateType, User,
    VetoApprovalStatus, VetoResult,
)
from services.espn.parlay_progress import result_from_final, sync_parlay_progress

FINAL = datetime.date(2026, 9, 9)
JSN = "4430878"
MAYE = "4431452"


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        yield db
    await engine.dispose()


async def synced(session, *bets):
    """An open parlay on the final slate with these bets on it, after one sync.

    Each bet is (athlete id, team, prop, line, direction, extra pick fields).
    """
    season = GamblingSeason(year=2026, name="2026", state=GamblingSeasonState.IN_PROGRESS)
    user = User(username="u", password="x", first_name="U", last_name="X")
    session.add_all([season, user])
    await session.flush()
    gambler = Gambler(user_id=user.id, gambling_season_id=season.id)
    session.add(gambler)
    await session.flush()
    parlay = Parlay(
        gambling_season_id=season.id, owner_id=gambler.id, slate_type=SlateType.WNF,
        competition_date=FINAL, state=ParlayState.OPEN, wager_pp=10, order=1,
    )
    session.add(parlay)
    await session.flush()

    picks = []
    for i, (athlete, team, prop, line, direction, extra) in enumerate(bets):
        target = PropBetTarget(identifier=f"t{i}", player_name=f"Player {i}", team_name=team, espn_athlete_id=athlete)
        session.add(target)
        await session.flush()
        pick = Pick(
            gambler_id=gambler.id, prop_bet_target_id=target.id, parlay_id=parlay.id,
            prop_type=prop, line=line, direction=direction, **extra,
        )
        session.add(pick)
        picks.append(pick)
    await session.commit()

    report = await sync_parlay_progress(parlay.id, session)
    return report, picks


async def test_a_final_game_settles_each_leg_from_the_number(session):
    report, (over_hit, over_missed, under_hit, pushed) = await synced(
        session,
        (JSN, "SEA", PropBetType.REC_YDS, 100.5, PropBetDirection.OVER, {}),
        (JSN, "SEA", PropBetType.REC_YDS, 130.5, PropBetDirection.OVER, {}),
        (MAYE, "NE", PropBetType.PASSING_YDS, 200.5, PropBetDirection.UNDER, {}),
        (MAYE, "NE", PropBetType.PASS_COMPLETIONS, 23, PropBetDirection.OVER, {}),
    )
    assert over_hit.result == PickResult.WIN
    assert over_missed.result == PickResult.LOSS
    assert under_hit.result == PickResult.WIN
    assert pushed.result == PickResult.PUSH
    assert report.picks_settled == 4


async def test_the_corrected_line_is_the_one_judged(session):
    # Recorded at 130.5, actually bet at 110.5 — 122 clears what was bet.
    _, (pick,) = await synced(
        session,
        (JSN, "SEA", PropBetType.REC_YDS, 130.5, PropBetDirection.OVER, {"corrected_line": 110.5}),
    )
    assert pick.result == PickResult.WIN


async def test_a_vetoed_call_that_missed_is_a_good_veto(session):
    veto = PickVeto(gambler_id=1, approval_status=VetoApprovalStatus.APPROVED)
    _, (pick,) = await synced(
        session,
        (JSN, "SEA", PropBetType.REC_YDS, 130.5, PropBetDirection.OVER, {"vetoes": [veto]}),
    )
    assert pick.result == PickResult.LOSS
    assert pick.vetoes[0].result == VetoResult.GOOD


async def test_a_result_entered_by_hand_is_never_overwritten(session):
    report, (pick,) = await synced(
        session,
        (JSN, "SEA", PropBetType.REC_YDS, 130.5, PropBetDirection.OVER, {"result": PickResult.VOID}),
    )
    assert pick.result == PickResult.VOID
    assert report.picks_settled == 0


async def test_a_player_missing_from_a_final_boxscore_is_left_for_a_person(session):
    # Most likely inactive, which is a void — a call the number cannot make.
    _, (pick,) = await synced(
        session,
        ("999999", "SEA", PropBetType.REC_YDS, 30.5, PropBetDirection.OVER, {}),
    )
    assert pick.live_value is None
    assert pick.result is None


def test_an_under_on_the_number_is_a_push_and_either_side_of_it_is_not():
    pick = Pick(line=50.0, corrected_line=None, direction=PropBetDirection.UNDER)
    assert result_from_final(pick, 50.0) == PickResult.PUSH
    assert result_from_final(pick, 49.0) == PickResult.WIN
    assert result_from_final(pick, 51.0) == PickResult.LOSS
