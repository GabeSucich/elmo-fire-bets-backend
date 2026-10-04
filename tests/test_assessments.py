"""When an assessment is reused, shown, or asked for again.

The model is replaced with a counter: what is under test is the bookkeeping around it —
above all that asking twice for the same picks costs nothing the second time. The building
parlay sits on 2026-10-11, a captured slate, so game context is filled from the fixture
exactly as it would be live.

Postgres in production, SQLite here.
"""
import datetime
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@localhost/unused")
os.environ.setdefault("SECRET", "unused-in-tests")

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import (
    Base, Gambler, GamblingSeason, GamblingSeasonState, Parlay, ParlayResult, ParlayState,
    Pick, PickResult, PickVeto, PropBetDirection, PropBetTarget, PropBetType, SlateType,
    User, VetoApprovalStatus,
)
from services.assessments import payload
from services.assessments import service
from services.assessments.llm import ConcernTag, SignalStrength, Suggestion
from services.assessments.service import SlotStatus


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        yield db
    await engine.dispose()


@pytest.fixture
def model_calls(monkeypatch):
    calls = []

    async def fake(payload):
        calls.append(payload)
        return [Suggestion(title="Cold on this", description="1/4.", signal=SignalStrength.MEDIUM, tag=ConcernTag.PAST_TREND)]

    monkeypatch.setattr(service, "assess_pick", fake)
    monkeypatch.setattr(service, "assess_parlay", fake)
    return calls


PLAYERS = [("Nico Collins", "HOU"), ("Calvin Ridley", "TEN"), ("Jayden Reed", "GB")]


@pytest.fixture
async def world(session):
    """Three gamblers, one settled parlay behind them and one being built on 10/11."""
    season = GamblingSeason(year=2026, name="2026", state=GamblingSeasonState.IN_PROGRESS)
    session.add(season)
    await session.flush()

    gamblers, targets = [], []
    for i, (player, team) in enumerate(PLAYERS):
        user = User(username=f"u{i}", password="x", first_name=f"Gambler{i}", last_name="X")
        session.add(user)
        await session.flush()
        gambler = Gambler(user_id=user.id, gambling_season_id=season.id)
        target = PropBetTarget(identifier=f"t{i}", player_name=player, team_name=team)
        session.add_all([gambler, target])
        gamblers.append(gambler)
        targets.append(target)
    await session.flush()

    def parlay(order, date, state, result=None):
        p = Parlay(
            gambling_season_id=season.id, owner_id=gamblers[0].id, slate_type=SlateType.MORNING_SLATE,
            competition_date=date, state=state, wager_pp=10, order=order, result=result,
        )
        session.add(p)
        return p

    settled = parlay(1, datetime.date(2026, 9, 27), ParlayState.CLOSED, ParlayResult.LOSS)
    building = parlay(2, datetime.date(2026, 10, 11), ParlayState.BUILDING)
    await session.flush()

    for gambler, target in zip(gamblers, targets):
        session.add(Pick(
            gambler_id=gambler.id, prop_bet_target_id=target.id, parlay_id=settled.id,
            prop_type=PropBetType.REC_YDS, line=60.5, direction=PropBetDirection.OVER,
            result=PickResult.LOSS,
        ))
        session.add(Pick(
            gambler_id=gambler.id, prop_bet_target_id=target.id, parlay_id=building.id,
            prop_type=PropBetType.REC_YDS, line=55.5, direction=PropBetDirection.OVER,
        ))
    await session.commit()
    return {"season": season, "gamblers": gamblers, "targets": targets, "building": building}


async def statuses(session, parlay_id):
    _, reports = await service.current_report(parlay_id, session)
    return [r.status for r in reports]


async def test_asking_twice_for_the_same_picks_costs_nothing_the_second_time(session, world, model_calls):
    parlay_id = world["building"].id
    _, reports = await service.generate(parlay_id, session)
    assert len(model_calls) == 4  # three picks and the parlay
    assert all(r.status == SlotStatus.FRESH for r in reports)

    # Game context was filled before the first hash, so it is not new the second time.
    _, reports = await service.generate(parlay_id, session)
    assert len(model_calls) == 4
    assert all(r.status == SlotStatus.FRESH for r in reports)


async def test_the_model_sees_the_game_and_the_settled_history(session, world, model_calls):
    await service.generate(world["building"].id, session)
    pick_input = next(c for c in model_calls if "pick" in c)

    # HOU @ TEN on the 10/11 fixture, HOU -6.5.
    assert pick_input["pick"]["game"]["venue"] == "away"
    assert pick_input["pick"]["game"]["team_spread"] == -6.5
    assert [r["call_result"] for r in pick_input[payload.RECENT_PICKS_KEY]] == ["Loss"]
    assert pick_input["trends"]["this_player"]["overall"]["losses"] == 1


async def test_changing_a_pick_hides_its_assessment_and_the_parlays_but_no_others(session, world, model_calls):
    parlay_id = world["building"].id
    await service.generate(parlay_id, session)

    parlay, _ = await service.load_season(parlay_id, session)
    changed = sorted(parlay.picks, key=lambda p: p.id)[0]
    changed.line = 70.5
    await session.commit()

    assert await statuses(session, parlay_id) == [
        SlotStatus.STALE, SlotStatus.FRESH, SlotStatus.FRESH, SlotStatus.STALE,
    ]
    await service.generate(parlay_id, session)
    assert len(model_calls) == 6  # that pick and the parlay, nothing else

    # Changed back: its first assessment is found again rather than paid for.
    changed.line = 55.5
    await session.commit()
    _, reports = await service.generate(parlay_id, session)
    assert len(model_calls) == 6
    assert all(r.status == SlotStatus.FRESH for r in reports)


async def test_the_line_moving_before_kickoff_does_not_invalidate_anything(session, world, model_calls):
    parlay_id = world["building"].id
    await service.generate(parlay_id, session)

    parlay, _ = await service.load_season(parlay_id, session)
    for pick in parlay.picks:
        pick.game_team_spread = (pick.game_team_spread or 0) + 1.5
        pick.game_weather = "Snow, 20°F"
    await session.commit()

    assert set(await statuses(session, parlay_id)) == {SlotStatus.FRESH}


async def test_a_newly_settled_parlay_outdates_assessments_without_hiding_them(session, world, model_calls):
    parlay_id = world["building"].id
    await service.generate(parlay_id, session)

    # Another of the settled parlay's picks gets corrected after the fact: new history,
    # same picks on the slate being built.
    season_parlays = (await service.load_season(parlay_id, session))[1]
    settled = next(p for p in season_parlays if p.state == ParlayState.CLOSED)
    settled.picks[0].result = PickResult.WIN
    await session.commit()

    assert set(await statuses(session, parlay_id)) == {SlotStatus.FRESH, SlotStatus.OUTDATED}
    assert SlotStatus.STALE not in await statuses(session, parlay_id)


async def test_a_veto_counts_against_the_call_but_for_the_leg():
    pick = Pick(
        direction=PropBetDirection.OVER, result=PickResult.LOSS,
        vetoes=[PickVeto(approval_status=VetoApprovalStatus.APPROVED)],
    )
    assert payload.played_direction(pick) == PropBetDirection.UNDER
    assert payload.leg_hit(pick) is True

    pick.vetoes = []
    assert payload.leg_hit(pick) is False
    pick.result = PickResult.PUSH
    assert payload.leg_hit(pick) is None


async def test_concerns_come_back_strongest_first(monkeypatch):
    from types import SimpleNamespace
    from services.assessments import llm

    written = [
        Suggestion(title="Weather", description="Wind.", signal=SignalStrength.LOW, tag=ConcernTag.WEATHER),
        Suggestion(title="0/3 on him", description="0/3.", signal=SignalStrength.HIGH, tag=ConcernTag.PAST_TREND),
        Suggestion(title="Soft trend", description="4/12.", signal=SignalStrength.MEDIUM, tag=ConcernTag.PAST_TREND),
    ]

    class Responses:
        async def parse(self, **kwargs):
            return SimpleNamespace(output_parsed=llm.AssessmentResult(suggestions=written))

    monkeypatch.setattr(llm, "get_client", lambda: SimpleNamespace(responses=Responses()))
    ranked = await llm.assess_pick({})
    assert [s.signal for s in ranked] == [SignalStrength.HIGH, SignalStrength.MEDIUM, SignalStrength.LOW]


def test_field_names_are_cut_from_what_the_model_wrote():
    from services.assessments.llm import without_field_names
    assert without_field_names(
        "Mark is 10/24 on passing-ints overs (this_prop_type this season), so it has been losing."
    ) == "Mark is 10/24 on passing-ints overs, so it has been losing."
    assert without_field_names("Spicy picks are 15/35 this season (trends spicy_picks).") == \
        "Spicy picks are 15/35 this season."
    # An ordinary aside stays.
    assert without_field_names("Jason is 7/20 (a big sample).") == "Jason is 7/20 (a big sample)."
