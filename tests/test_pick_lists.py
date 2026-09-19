"""What counts as a pick being on somebody's list.

The arithmetic is trivial; all of the behaviour is in how an entry's optional narrowings
match — an unset field means "any", and a set one has to agree. The direction case is the
one that would be quietly wrong forever: banning MHJ's overs must say nothing at all about
somebody taking his under.
"""
import pytest

from models import (
    Pick,
    PickList,
    PickListItem,
    PickListType,
    PropBetDirection,
    PropBetType,
)
from routers.common import PickListIndex

BAN_LIST = PickList(id=1, gambling_season_id=1, list_type=PickListType.BAN, display_name="Ban List")

CHASE = 10
MHJ = 11


def entry(gambler_id, target_id, prop_type=None, direction=None, item_id=1, pick_list=BAN_LIST):
    item = PickListItem(
        id=item_id,
        pick_list_id=pick_list.id,
        gambler_id=gambler_id,
        prop_bet_target_id=target_id,
        prop_type=prop_type,
        direction=direction,
    )
    item.pick_list = pick_list
    return item


def bet(target_id, prop_type=PropBetType.REC_YDS, direction=PropBetDirection.OVER):
    return Pick(prop_bet_target_id=target_id, prop_type=prop_type, direction=direction)


def placements(items, pick):
    return PickListIndex(items).placements_for(pick)


def test_a_bare_player_entry_catches_every_bet_on_him():
    item = entry(1, CHASE)
    assert item.matches(CHASE, PropBetType.REC_YDS, PropBetDirection.OVER)
    assert item.matches(CHASE, PropBetType.TDS, PropBetDirection.UNDER)


def test_an_entry_says_nothing_about_a_different_player():
    assert not entry(1, CHASE).matches(MHJ, PropBetType.REC_YDS, PropBetDirection.OVER)


def test_a_market_entry_catches_both_sides_of_that_market_only():
    item = entry(1, CHASE, prop_type=PropBetType.REC_YDS)
    assert item.matches(CHASE, PropBetType.REC_YDS, PropBetDirection.OVER)
    assert item.matches(CHASE, PropBetType.REC_YDS, PropBetDirection.UNDER)
    assert not item.matches(CHASE, PropBetType.TDS, PropBetDirection.OVER)


def test_banning_the_over_does_not_ban_the_under():
    """The case the whole optional-direction field exists for."""
    item = entry(1, MHJ, direction=PropBetDirection.OVER)
    assert item.matches(MHJ, PropBetType.REC_YDS, PropBetDirection.OVER)
    assert not item.matches(MHJ, PropBetType.REC_YDS, PropBetDirection.UNDER)


def test_both_narrowings_have_to_agree():
    item = entry(1, MHJ, prop_type=PropBetType.REC_YDS, direction=PropBetDirection.OVER)
    assert item.matches(MHJ, PropBetType.REC_YDS, PropBetDirection.OVER)
    assert not item.matches(MHJ, PropBetType.REC_YDS, PropBetDirection.UNDER)
    assert not item.matches(MHJ, PropBetType.TDS, PropBetDirection.OVER)


def test_a_pick_nobody_listed_has_no_placements():
    assert placements([entry(1, CHASE)], bet(MHJ)) == []


def test_a_placement_names_the_list_and_everyone_on_it():
    found = placements(
        [entry(1, CHASE, item_id=1), entry(2, CHASE, item_id=2)],
        bet(CHASE),
    )
    assert len(found) == 1
    assert found[0].pick_list_id == BAN_LIST.id
    assert found[0].list_type == PickListType.BAN
    assert found[0].display_name == "Ban List"
    assert [e.gambler_id for e in found[0].entries] == [1, 2]


def test_one_gambler_is_named_once_however_many_of_their_entries_match():
    """Otherwise the badge's count reads as two people when it is one person twice."""
    found = placements(
        [
            entry(1, CHASE, item_id=1),
            entry(1, CHASE, prop_type=PropBetType.REC_YDS, direction=PropBetDirection.OVER, item_id=2),
        ],
        bet(CHASE),
    )
    assert [e.gambler_id for e in found[0].entries] == [1]


def test_the_narrowest_matching_entry_is_the_one_reported():
    """The drawer has to say why, and "Rec Yards / Over" describes this bet where the bare
    player entry only describes the player."""
    found = placements(
        [
            entry(1, CHASE, item_id=1),
            entry(1, CHASE, prop_type=PropBetType.REC_YDS, direction=PropBetDirection.OVER, item_id=2),
        ],
        bet(CHASE),
    )
    reported = found[0].entries[0]
    assert reported.prop_type == PropBetType.REC_YDS
    assert reported.direction == PropBetDirection.OVER


def test_entries_that_do_not_match_are_left_out_of_the_placement():
    found = placements(
        [
            entry(1, MHJ, direction=PropBetDirection.OVER, item_id=1),
            entry(2, MHJ, item_id=2),
        ],
        bet(MHJ, direction=PropBetDirection.UNDER),
    )
    assert [e.gambler_id for e in found[0].entries] == [2]


def test_a_pick_can_land_on_more_than_one_list():
    other = PickList(id=2, gambling_season_id=1, list_type=PickListType.BAN, display_name="Watch List")
    found = placements(
        [entry(1, CHASE, item_id=1), entry(1, CHASE, item_id=2, pick_list=other)],
        bet(CHASE),
    )
    assert [p.pick_list_id for p in found] == [1, 2]


def parlay_with(state, pick):
    from models import Parlay, SlateType
    import datetime
    parlay = Parlay(
        id=1, owner_id=1, slate_type=SlateType.SNF, wager_pp=5.0, payout_pp=None,
        competition_date=datetime.date(2026, 9, 13), state=state, result=None, order=1,
    )
    parlay.picks = [pick]
    return parlay


def loaded_pick(target_id):
    """A pick with the collections a response needs, none of which this is about."""
    from models import PropBetTarget
    pick = Pick(
        id=1, gambler_id=1, prop_bet_target_id=target_id, prop_type=PropBetType.REC_YDS,
        line=50.5, corrected_line=None, direction=PropBetDirection.OVER, sauce_factor=None,
        result=None, live_value=None, live_state=None, live_detail=None, live_synced_at=None,
    )
    pick.prop_bet_target = PropBetTarget(id=target_id, identifier="x", team_name="cin", player_name="Ja'Marr Chase")
    pick.vetoes = []
    pick.reactions = []
    pick.comments = []
    return pick


@pytest.mark.parametrize("state", ["BUILDING", "OPEN"])
def test_a_live_parlay_carries_its_badges(state):
    from models import ParlayState
    from routers.common import ParlayResponseData

    parlay = parlay_with(getattr(ParlayState, state), loaded_pick(CHASE))
    response = ParlayResponseData.from_model(parlay, PickListIndex([entry(1, CHASE)]))
    assert len(response.picks[0].list_placements) == 1


def test_a_closed_parlay_carries_none_even_when_handed_an_index():
    """The rule lives in from_model rather than at each call site, so no endpoint can leak
    them onto a lay nobody can act on."""
    from models import ParlayState
    from routers.common import ParlayResponseData

    parlay = parlay_with(ParlayState.CLOSED, loaded_pick(CHASE))
    response = ParlayResponseData.from_model(parlay, PickListIndex([entry(1, CHASE)]))
    assert response.picks[0].list_placements == []
