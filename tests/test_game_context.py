"""What a pick learns about its game from the scoreboard.

Against captured slates: 2026-09-27 is a finished Sunday (scores, no odds — ESPN drops
them at kickoff), 2026-10-11 the Sunday after capture (odds and forecasts, no scores).
"""
import dataclasses
import datetime

import pytest
import requests

from models import Parlay, Pick, PropBetDirection, PropBetTarget, PropBetType, SlateType, ParlayState
from services.espn.client import fetch_slate_games
from services.espn.game_context import apply_game_context, fill_game_context, game_for

FINAL = datetime.date(2026, 9, 27)
UPCOMING = datetime.date(2026, 10, 11)


def pick_on(team: str, player: str | None = "Someone") -> Pick:
    return Pick(
        prop_bet_target=PropBetTarget(identifier=f"{player}-{team}", player_name=player, team_name=team),
        prop_type=PropBetType.REC_YDS,
        direction=PropBetDirection.OVER,
        line=50.5,
    )


def game_of(team: str, date: datetime.date):
    pick = pick_on(team)
    return game_for(pick.prop_bet_target, fetch_slate_games(date))


def test_a_finished_game_records_where_it_was_played_and_how_it_ended():
    pick = pick_on("LAC")
    assert apply_game_context(pick, game_of("LAC", FINAL))

    assert pick.game_event_id == "401872953"
    assert pick.game_is_home is False
    assert pick.game_opponent == "BUF"
    assert pick.game_kickoff_at == datetime.datetime(2026, 9, 27, 17, 0)
    assert pick.game_week == 3
    assert pick.game_neutral_site is False
    assert (pick.game_team_score, pick.game_opponent_score) == (16, 24)
    # Gone from the scoreboard once the game started, and never invented.
    assert pick.game_team_spread is None and pick.game_total is None


def test_an_upcoming_game_records_the_market_from_the_picks_side():
    # HOU @ TEN, HOU -6.5. ESPN states the spread from the home side, as +6.5.
    away_favourite = pick_on("HOU")
    apply_game_context(away_favourite, game_of("HOU", UPCOMING))
    assert away_favourite.game_team_spread == -6.5
    assert away_favourite.game_total == 39.5
    assert away_favourite.game_weather == "Cloudy, 62°F"

    home_dog = pick_on("TEN")
    apply_game_context(home_dog, game_of("TEN", UPCOMING))
    assert home_dog.game_team_spread == 6.5
    assert home_dog.game_is_home is True
    # Not yet played: ESPN's "0" is not a score.
    assert home_dog.game_team_score is None


def test_a_neutral_site_game_says_so():
    pick = pick_on("PHI")
    apply_game_context(pick, game_of("PHI", UPCOMING))
    assert pick.game_neutral_site is True


def test_a_team_target_is_matched_the_same_way():
    pick = pick_on("DET", player=None)
    apply_game_context(pick, game_of("DET", FINAL))
    assert pick.game_opponent == "NYJ"
    assert pick.game_team_score == 31


def test_applying_the_same_game_again_changes_nothing():
    # The property assessments depend on: filling in context before hashing must leave
    # nothing to fill the second time, or every request would look like a new input.
    for team, date in (("LAC", FINAL), ("HOU", UPCOMING)):
        pick = pick_on(team)
        game = game_of(team, date)
        assert apply_game_context(pick, game)
        assert not apply_game_context(pick, game)


def test_a_line_already_captured_survives_espn_dropping_it():
    pick = pick_on("HOU")
    game = game_of("HOU", UPCOMING)
    apply_game_context(pick, game)

    without_odds = dataclasses.replace(game, home_spread=None, total=None, weather=None)
    assert not apply_game_context(pick, without_odds)
    assert pick.game_team_spread == -6.5


def test_a_different_game_replaces_everything_including_the_market():
    pick = pick_on("HOU")
    apply_game_context(pick, game_of("HOU", UPCOMING))
    # The parlay's date was corrected to the week before.
    apply_game_context(pick, game_of("HOU", FINAL))

    assert pick.game_opponent == "IND"
    assert pick.game_team_spread is None
    assert pick.game_team_score == 17


def parlay_on(date: datetime.date, *picks: Pick) -> Parlay:
    return Parlay(
        competition_date=date, slate_type=SlateType.AFTERNOON_SLATE,
        state=ParlayState.BUILDING, wager_pp=10, order=1, picks=list(picks),
    )


@pytest.mark.asyncio
async def test_fill_reports_a_team_with_no_game_that_day():
    report = await fill_game_context([parlay_on(FINAL, pick_on("LAC"), pick_on("ATL", "Moved On"))])
    assert report.picks_changed == 1
    assert report.unmatched == ["Moved On (ATL), pick None"]


@pytest.mark.asyncio
async def test_fill_does_not_fetch_for_picks_that_are_already_final(monkeypatch):
    pick = pick_on("LAC")
    apply_game_context(pick, game_of("LAC", FINAL))

    def refuse(*args, **kwargs):
        raise AssertionError("fetched a slate with nothing left to learn from it")
    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr("services.espn.game_context.fetch_slate_games", refuse)

    report = await fill_game_context([parlay_on(FINAL, pick)])
    assert report.picks_seen == 0


def traded_pick() -> Pick:
    """Stored as KC, the team he is at now, but in this game he played for LAC."""
    pick = pick_on("KC", "Traded Player")
    pick.prop_bet_target.espn_athlete_id = "123"
    return pick


def test_history_follows_the_players_gamelog_not_his_current_team():
    # KC also played that day (@ MIA), so matching by team would quietly pick that game.
    from services.espn.game_context import GameContextReport, apply_slate
    pick = traded_pick()
    report = GameContextReport()
    apply_slate([pick], fetch_slate_games(FINAL), report, {"123": {"401872953": "LAC"}})

    assert pick.game_event_id == "401872953"
    assert pick.game_opponent == "BUF"
    assert (pick.game_team_score, pick.game_opponent_score) == (16, 24)


def test_a_finished_game_missing_from_the_gamelog_is_left_alone():
    # Inactive that day. His current team's game is not his, so nothing is written.
    from services.espn.game_context import GameContextReport, apply_slate
    pick = traded_pick()
    report = GameContextReport()
    apply_slate([pick], fetch_slate_games(FINAL), report, {"123": {}})

    assert pick.game_event_id is None
    assert report.unmatched == ["Traded Player (KC), pick None"]


def test_a_game_not_yet_played_falls_back_to_the_current_team():
    from services.espn.game_context import GameContextReport, apply_slate
    pick = pick_on("HOU", "Current Player")
    pick.prop_bet_target.espn_athlete_id = "456"
    apply_slate([pick], fetch_slate_games(UPCOMING), GameContextReport(), {"456": {}})

    assert pick.game_opponent == "TEN"
