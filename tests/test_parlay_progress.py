"""What the progress sync reads off a slate.

Against captured responses, so the numbers below are the real ones ESPN reported for
NE @ SEA on 2026-09-09 — and the in-progress case is that same game with its counting
stats halved and a clock on it, which is the only way to have one at all.
"""
import datetime

import pytest

from services.espn.client import fetch_boxscore, fetch_slate_games
from services.espn.gamelog import GameStats
from services.espn.stats import resolve
from models import PropBetType

FINAL = datetime.date(2026, 9, 9)
SCHEDULED = datetime.date(2026, 9, 13)
IN_PLAY = datetime.date(2026, 9, 20)

JSN = "4430878"
BROWN = "4047646"


def only_game(date):
    games = fetch_slate_games(date)
    assert games, f"no game on {date}"
    return games[0]


def line_for(event_id, team, athlete_id):
    box = fetch_boxscore(event_id)
    return GameStats(week=0, event_id=event_id, values=box[team][athlete_id])


def test_a_finished_game_reports_itself_finished():
    game = only_game(FINAL)
    assert game.state == "post"
    assert game.detail == "Final"
    assert game.teams == frozenset({"NE", "SEA"})


def test_a_scheduled_game_reports_its_kickoff_rather_than_a_score():
    game = only_game(SCHEDULED)
    assert game.state == "pre"
    assert "1:00 PM EDT" in game.detail


def test_a_game_in_play_reports_the_clock():
    game = only_game(IN_PLAY)
    assert game.state == "in"
    assert game.detail == "Q3 4:12"


def test_a_primetime_kickoff_belongs_to_the_day_it_started_pacific():
    """00:20 UTC on the 10th is 17:20 on the 9th where the league lives.

    The slate this app files that game under is the 9th. Reading the bare UTC date would
    put it on the 10th, which is the bug this window check exists to prevent.
    """
    assert only_game(FINAL).event_id == "401872656"

    # The 10th's fixture deliberately contains that same 00:20Z kickoff, so this asserts
    # the window actually rejects it rather than there merely being nothing to find.
    misfiled = fetch_slate_games(datetime.date(2026, 9, 10))
    assert misfiled == [], f"a game from the 9th was accepted onto the 10th: {misfiled}"


@pytest.mark.parametrize("prop, expected", [
    (PropBetType.REC_YDS, 122.0),
    (PropBetType.RECEPTIONS, 8.0),
    (PropBetType.TARGETS, 11.0),
    (PropBetType.TDS, 1.0),
    (PropBetType.RECEIVING_TDS, 1.0),
    (PropBetType.LONGEST_RECEPTION, 45.0),
    (PropBetType.RUSH_REC_YDS, 122.0),
])
def test_a_receivers_markets_resolve_from_the_boxscore(prop, expected):
    assert resolve(prop, line_for("401872656", "SEA", JSN)) == expected


@pytest.mark.parametrize("prop, expected", [
    (PropBetType.PASSING_YDS, 178.0),
    (PropBetType.PASSING_TDS, 1.0),
    (PropBetType.PASSING_INTS, 3.0),
    (PropBetType.PASS_COMPLETIONS, 23.0),
    (PropBetType.PASS_ATTEMPTS, 33.0),
])
def test_a_quarterbacks_markets_resolve_despite_the_combined_key(prop, expected):
    """The boxscore reports "23/33" in one field where the gamelog keeps two.

    normalize_boxscore splits it, which is the only reason completions and attempts are
    readable live at all.
    """
    maye = line_for("401872656", "NE", "4431452")
    assert resolve(prop, maye) == expected


def test_longest_completion_cannot_be_read_live():
    """longPassing is simply absent from a boxscore.

    Asserted rather than left to be discovered: the leg renders nothing, and the day ESPN
    starts publishing it this test is what says so.
    """
    maye = line_for("401872656", "NE", "4431452")
    assert resolve(PropBetType.LONGEST_COMPLETION, maye) is None


def test_a_quarterbacks_interceptions_are_the_ones_he_threw():
    """The same key means opposite things by position, and the guard is what tells them
    apart — a defender has no passing attempts, so his catches never read as picks thrown."""
    box = fetch_boxscore("401872656")
    defenders = [
        aid for aid, vals in box["SEA"].items()
        if "totalTackles" in vals and "passingYards" not in vals
    ]
    assert defenders, "fixture has no defensive players to check against"
    for aid in defenders:
        stats = GameStats(week=0, event_id="x", values=box["SEA"][aid])
        assert resolve(PropBetType.PASSING_INTS, stats) is None


def test_field_goals_come_off_the_kicking_category():
    """A slash-joined pair where the gamelog uses a hyphen; made_of accepts either."""
    myers = line_for("401872656", "SEA", "2473037")  # Jason Myers, 2/2 on the night
    assert resolve(PropBetType.FGS, myers) == 2.0


def test_a_game_in_play_reports_partial_numbers():
    """The same receiver, mid-game: fewer yards than he finished with, same keys."""
    game = only_game(IN_PLAY)
    stats = line_for(game.event_id, "SEA", JSN)
    assert resolve(PropBetType.REC_YDS, stats) == 61.0
    assert resolve(PropBetType.RECEPTIONS, stats) == 4.0


def test_a_missing_fixture_is_empty_rather_than_a_live_call():
    """A date nobody captured must not quietly reach ESPN.

    That is what would make a test pass or fail on whatever the real NFL did that week.
    """
    assert fetch_slate_games(datetime.date(1999, 1, 1)) == []


def test_a_receiver_who_played_simply_has_no_rushing_line():
    """The precondition for treating a missing stat as a zero.

    A.J. Brown is in this boxscore and ran nowhere, so ESPN gives him no rushing entry at
    all. The sync reads that as nought rushing yards rather than as no answer, because he
    was out there — the same reading the season sync takes.
    """
    brown = line_for("401872656", "NE", BROWN)
    assert resolve(PropBetType.REC_YDS, brown) == 26.0, "he is in the boxscore"
    assert resolve(PropBetType.RUSH_YDS, brown) is None, "with nothing under rushing"


def test_the_markets_a_boxscore_cannot_express_are_named():
    """A zero and an unreadable market look identical in the data and mean opposite things.

    Everything a player who took the field has none of is a zero. This set is the
    exception, and it exists so that exception is a decision rather than an accident.
    """
    from services.espn.stats import NOT_IN_BOXSCORE
    assert PropBetType.LONGEST_COMPLETION in NOT_IN_BOXSCORE
    # If any of these ever joins it, a leg silently stops reporting and this says so.
    for readable in (PropBetType.REC_YDS, PropBetType.RUSH_YDS, PropBetType.TDS,
                     PropBetType.FGS, PropBetType.PASSING_INTS, PropBetType.SACKS):
        assert readable not in NOT_IN_BOXSCORE
