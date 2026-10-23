"""What the model is shown, built from a season already loaded into memory.

Every function here is pure: the same season in gives the same dicts out, which is the
whole basis of the hashing in `hashing.py`. Nothing reads the clock, and every list is put
in a fixed order before it is returned.

Two shapes come out per assessment. The *subject* is only what was chosen — the pick, or
the slate — and decides whether a stored assessment is still about the pick on screen. The
*input* is everything the model sees, and decides whether it has to be asked again.
"""
import copy
import datetime
import zoneinfo
from typing import Any

from models import Parlay, ParlayState, Pick, PickResult, PropBetDirection, SlateType
from services.metric_calculator import GamblerMetricsCalculator, SetMetrics
from utils.parlays import approved_veto, leg_lost

# How far back the recent windows look. Current season only, by decision. Everything else
# the model sees — same-prop-type picks, trends, the group's records — is the whole season,
# and the payload keys and the prompt both say which is which.
PICK_HISTORY_SIZE = 15
PARLAY_HISTORY_SIZE = 15
RECENT_PICKS_KEY = f"last_{PICK_HISTORY_SIZE}_picks"
RECENT_PARLAYS_KEY = f"last_{PARLAY_HISTORY_SIZE}_parlays"

EASTERN = zoneinfo.ZoneInfo("America/New_York")

# The fields of the pick being assessed that move until kickoff. They go to the model but
# are kept out of both hashes, or a line moving half a point would invalidate the
# assessment of a pick nobody touched.
VOLATILE_GAME_FIELDS = ("spread", "game_total", "weather", "total_bucket", "spread_bucket")

# How past games are grouped when the model is shown a record by game situation. Fixed
# buckets rather than ranges around this game's numbers, so the records depend on history
# alone and a line moving before kickoff changes nothing the model is shown about the past.
LOW_TOTAL_MAX = 42.5
HIGH_TOTAL_MIN = 48.0
CLOSE_SPREAD_MAX = 3.0


def total_bucket(total: float | None) -> str | None:
    if total is None:
        return None
    if total <= LOW_TOTAL_MAX:
        return "low"
    return "high" if total >= HIGH_TOTAL_MIN else "mid"


def spread_bucket(team_spread: float | None) -> str | None:
    if team_spread is None:
        return None
    if abs(team_spread) <= CLOSE_SPREAD_MAX:
        return "close"
    return "favorite" if team_spread < 0 else "underdog"


def played_direction(pick: Pick) -> PropBetDirection:
    """The side that actually went on the slip: an approved veto flips it.

    Same rule as correction_analysis.effective_direction, without needing it imported.
    """
    if approved_veto(pick) is None:
        return pick.direction
    return PropBetDirection.UNDER if pick.direction == PropBetDirection.OVER else PropBetDirection.OVER


def leg_hit(pick: Pick) -> bool | None:
    """Whether the leg on the slip won, as distinct from whether the gambler's call did.

    pick.result is always the gambler's own call; see utils.parlays.leg_lost for how an
    approved veto turns that around. Void and push are neither.
    """
    if pick.result in (None, PickResult.VOID, PickResult.PUSH):
        return None
    return not leg_lost(pick, pick.result)


def effective_line(pick: Pick) -> float:
    return pick.corrected_line if pick.corrected_line is not None else pick.line


def gambler_name(pick: Pick) -> str:
    return pick.gambler.user.first_name


def _kickoff(kickoff_at: datetime.datetime | None) -> str | None:
    """'Sun 1:00 PM ET' — the thing a person means by morning or afternoon game."""
    if kickoff_at is None:
        return None
    local = kickoff_at.replace(tzinfo=datetime.timezone.utc).astimezone(EASTERN)
    return local.strftime("%a %-I:%M %p ET")


def _points(value: float) -> str:
    return f"{value:g}"


def spread_text(team: str | None, opponent: str | None, team_spread: float | None) -> str | None:
    """'JAX +7.5: JAX are 7.5-point underdogs, PHI favored by 7.5'.

    Spelled out because the model, given the bare number from the pick's own side, kept
    getting the sign backwards — and two legs in one game carry opposite signs, so it
    called both teams the favorite on the same slate.
    """
    if team_spread is None or team is None:
        return None
    if team_spread == 0:
        return f"{team} pick'em: neither side favored"
    points = _points(abs(team_spread))
    signed = f"{team} {'-' if team_spread < 0 else '+'}{points}"
    other = opponent or "the opponent"
    if team_spread < 0:
        return f"{signed}: {team} favored by {points} over {other}"
    return f"{signed}: {team} are {points}-point underdogs, {other} favored by {points}"


def game_context(pick: Pick) -> dict[str, Any] | None:
    if pick.game_event_id is None:
        return None
    if pick.game_neutral_site:
        venue = "neutral"
    elif pick.game_is_home is None:
        venue = None
    else:
        venue = "home" if pick.game_is_home else "away"
    final = None
    if pick.game_team_score is not None and pick.game_opponent_score is not None:
        outcome = (
            "W" if pick.game_team_score > pick.game_opponent_score
            else "L" if pick.game_team_score < pick.game_opponent_score
            else "T"
        )
        final = f"{outcome} {pick.game_team_score}-{pick.game_opponent_score}"
    team = pick.game_team or pick.prop_bet_target.team_name
    opponent = pick.game_opponent
    # Spelled out because the model otherwise has to infer from two fields that two legs
    # share a game — and, worse, guessed that two players in one game were on one team.
    matchup = None
    if team and opponent and venue is not None:
        if venue == "neutral":
            matchup = f"{team} vs {opponent}"
        else:
            matchup = f"{opponent} @ {team}" if venue == "home" else f"{team} @ {opponent}"
    return {
        "matchup": matchup,
        "week": pick.game_week,
        "kickoff": _kickoff(pick.game_kickoff_at),
        "venue": venue,
        "opponent": pick.game_opponent,
        "indoor": pick.game_indoor,
        "spread": spread_text(team, opponent, pick.game_team_spread),
        "game_total": pick.game_total,
        # Which of the by-game-situation buckets this game is in, so the model reads the
        # right record instead of placing 41.5 itself — it called that "mid".
        "total_bucket": total_bucket(pick.game_total),
        "spread_bucket": spread_bucket(pick.game_team_spread),
        "weather": pick.game_weather,
        "final_score": final,
    }


def pick_row(pick: Pick, parlay: Parlay, with_outcome: bool) -> dict[str, Any]:
    """One pick, as the model sees it — the same shape in history and on the slate."""
    target = pick.prop_bet_target
    veto = approved_veto(pick)
    row: dict[str, Any] = {
        "gambler": gambler_name(pick),
        "player": target.player_name,
        # Who he played for in that game where known, which for a traded player is not
        # who his target says he plays for now.
        "team": pick.game_team or target.team_name,
        "is_team_bet": target.player_name is None,
        "prop_type": pick.prop_type.value,
        "line": effective_line(pick),
        "called_direction": pick.direction.value,
        "sauce_factor": pick.sauce_factor.value if pick.sauce_factor else None,
        "vetoed": veto is not None,
        "played_direction": played_direction(pick).value,
        "slate_type": parlay.slate_type.value,
        "date": parlay.competition_date.isoformat(),
        "game": game_context(pick),
    }
    if with_outcome:
        row["call_result"] = pick.result.value if pick.result else None
        row["leg_hit"] = leg_hit(pick)
        row["actual_value"] = pick.live_value
        row["veto_result"] = veto.result.value if veto and veto.result else None
    return row


def pick_subject(pick: Pick) -> dict[str, Any]:
    """What the gambler chose, and nothing that changes without them choosing again.

    The target by id rather than by name or team: the player sync relabels teams, and that
    should not make an assessment look stale.
    """
    veto = approved_veto(pick)
    return {
        "pick_id": pick.id,
        "target_id": pick.prop_bet_target_id,
        "player": pick.prop_bet_target.player_name,
        "prop_type": pick.prop_type.value,
        "line": effective_line(pick),
        "direction": pick.direction.value,
        "sauce_factor": pick.sauce_factor.value if pick.sauce_factor else None,
        "vetoed": veto is not None,
    }


def settled(parlays: list[Parlay], current: Parlay) -> list[Parlay]:
    """The season's finished parlays from before this one, newest first.

    Before by the league's own ordering rather than merely other than: for a parlay being
    built the two are the same, and only this way can a past parlay be assessed as it stood.
    """
    done = [
        p for p in parlays
        if p.order < current.order and p.state == ParlayState.CLOSED and p.result is not None
    ]
    return sorted(done, key=lambda p: p.order, reverse=True)


def _record(metrics: SetMetrics | None) -> dict[str, Any] | None:
    if metrics is None or metrics.total == 0:
        return None
    record = metrics.model_dump(include={
        "total", "wins", "losses", "pushes", "voids", "bozos", "win_rate",
        "curr_win_streak", "curr_loss_streak", "curr_bozo_streak",
    })
    # Worked out here rather than left to the model, which divided by total — voids and
    # pushes included — and once wrote wins over losses as if it were a record.
    record["decided"] = metrics.total - metrics.pushes - metrics.voids
    record["record"] = f"{metrics.wins}/{record['decided']}"
    return record


def _situations(rows: list[tuple[Pick, bool]]) -> dict[str, dict[str, str]] | None:
    """Hits over decided picks in each kind of game: by total, by spread and by venue.

    Each row is a past pick with whether it hit. Every bucket that has a decided pick is
    listed, not only the one this game falls in, so the model reads which applies from the
    game it is shown — see total_bucket for why.
    """
    groups: dict[str, dict[str, list[int]]] = {}
    for pick, hit in rows:
        for name, bucket in (
            ("by_game_total", total_bucket(pick.game_total)),
            ("by_spread", spread_bucket(pick.game_team_spread)),
            ("by_venue", None if pick.game_neutral_site or pick.game_is_home is None
                else "home" if pick.game_is_home else "away"),
        ):
            if bucket is None:
                continue
            hits, decided = groups.setdefault(name, {}).setdefault(bucket, [0, 0])
            groups[name][bucket] = [hits + int(hit), decided + 1]
    if not groups:
        return None
    return {
        name: {bucket: f"{hits}/{decided}" for bucket, (hits, decided) in sorted(buckets.items())}
        for name, buckets in sorted(groups.items())
    }


def call_hit(pick: Pick) -> bool | None:
    """Whether the gambler's own call was right. Void and push are neither."""
    if pick.result == PickResult.WIN:
        return True
    if pick.result in (PickResult.LOSS, PickResult.BOZO):
        return False
    return None


def gambler_situations(pick: Pick, parlay: Parlay, season_parlays: list[Parlay]) -> dict[str, Any]:
    """This gambler's calls on this pick's side, by game situation, this season.

    Both within this prop type and across every prop type — "Jason's overs in low-total
    games" is the history the model should weigh, rather than reasoning that a low total
    is bad for an over on its own.
    """
    side = pick.direction
    calls = [
        (p, hit)
        for prior in settled(season_parlays, parlay)
        for p in prior.picks
        if p.gambler_id == pick.gambler_id and p.direction == side and (hit := call_hit(p)) is not None
    ]
    label = side.value.lower() + "s"
    return {
        f"this_prop_type_{label}": _situations([(p, h) for p, h in calls if p.prop_type == pick.prop_type]),
        f"all_{label}": _situations(calls),
    }


def trends(pick: Pick, parlay: Parlay, season_parlays: list[Parlay]) -> dict[str, Any]:
    """The slice of the Trends tab that bears on this pick.

    From the same calculator the Trends tab is built on, so the two can never disagree.
    Only the slices that could say something about this particular pick — the rest of a
    gambler's metrics is noise to the model and bulk to the prompt.
    """
    history = settled(season_parlays, parlay)
    metrics = GamblerMetricsCalculator.calculator_from_parlays(pick.gambler_id, history).get_advanced_metrics()
    prop = metrics.bet_types.bet_types.get(pick.prop_type)
    player = metrics.prop_target_metrics.prop_targets.get(pick.prop_bet_target_id)

    def split(m) -> dict[str, Any] | None:
        if m is None:
            return None
        return {
            "overall": _record(m.overall),
            "overs": _record(m.direction_metrics.overs),
            "unders": _record(m.direction_metrics.unders),
        }

    # No all-overs or all-unders record: this group takes overs almost exclusively, so for
    # most gamblers it is their season record again, and the model read it as a concern
    # about every pick. The over-under split that matters is the one within this prop type.
    slice_: dict[str, Any] = {
        "season_overall": _record(metrics.overall),
        "this_prop_type": split(prop),
        "this_player": split(player),
    }
    if pick.sauce_factor:
        sauce = metrics.sauce_factor.spicy if pick.sauce_factor.value == "Spicy" else metrics.sauce_factor.bitch
        slice_[f"{pick.sauce_factor.value.lower()}_picks"] = _record(sauce)
    if parlay.slate_type == SlateType.TD:
        slice_["td_slates"] = _record(metrics.TD_slate.overall)
    return slice_


def pick_input(pick: Pick, parlay: Parlay, season_parlays: list[Parlay]) -> dict[str, Any]:
    """Everything the model sees for one pick's assessment."""
    gambler_picks = [
        (p, prior)
        for prior in settled(season_parlays, parlay)
        for p in prior.picks
        if p.gambler_id == pick.gambler_id and p.result is not None
    ]
    return {
        "pick": pick_row(pick, parlay, with_outcome=False),
        RECENT_PICKS_KEY: [pick_row(p, prior, True) for p, prior in gambler_picks[:PICK_HISTORY_SIZE]],
        # A recent window cannot say anything about one market, so every one this season.
        "same_prop_type_this_season": [
            pick_row(p, prior, True) for p, prior in gambler_picks if p.prop_type == pick.prop_type
        ],
        "trends": trends(pick, parlay, season_parlays),
        "by_game_situation_this_season": gambler_situations(pick, parlay, season_parlays),
    }


def _ordered(picks: list[Pick]) -> list[Pick]:
    return sorted(picks, key=lambda p: p.id)


def parlay_subject(parlay: Parlay) -> dict[str, Any]:
    return {
        "parlay_id": parlay.id,
        "slate_type": parlay.slate_type.value,
        "date": parlay.competition_date.isoformat(),
        "picks": [pick_subject(p) for p in _ordered(parlay.picks)],
    }


def group_season_records(parlay: Parlay, season_parlays: list[Parlay]) -> dict[str, Any]:
    """How the group's legs have done this season, by prop type and side.

    Judged on leg_hit — the leg that actually went on the slip — since this is about what
    sinks parlays, not who called what. Lets a claim about a market be checked against the
    season rather than resting on the last few parlays alone.
    """
    tallies: dict[str, dict[str, list[int]]] = {}
    for prior in settled(season_parlays, parlay):
        for pick in prior.picks:
            hit = leg_hit(pick)
            if hit is None:
                continue
            sides = tallies.setdefault(pick.prop_type.value, {})
            for side in ("all", played_direction(pick).value.lower() + "s"):
                hits, decided = sides.setdefault(side, [0, 0])
                sides[side] = [hits + int(hit), decided + 1]
    return {
        prop_type: {side: f"{hits}/{decided}" for side, (hits, decided) in sorted(sides.items())}
        for prop_type, sides in sorted(tallies.items())
    }


def group_season_situations(parlay: Parlay, season_parlays: list[Parlay]) -> dict[str, Any]:
    """How the group's legs have done this season by game situation, overs and unders apart."""
    legs: dict[str, list[tuple[Pick, bool]]] = {}
    for prior in settled(season_parlays, parlay):
        for pick in prior.picks:
            hit = leg_hit(pick)
            if hit is None:
                continue
            legs.setdefault(played_direction(pick).value.lower() + "s", []).append((pick, hit))
    return {side: _situations(rows) for side, rows in sorted(legs.items())}


def parlay_input(parlay: Parlay, season_parlays: list[Parlay]) -> dict[str, Any]:
    return {
        "slate": {
            "slate_type": parlay.slate_type.value,
            "date": parlay.competition_date.isoformat(),
            "picks": [pick_row(p, parlay, with_outcome=False) for p in _ordered(parlay.picks)],
        },
        RECENT_PARLAYS_KEY: [
            {
                "slate_type": prior.slate_type.value,
                "date": prior.competition_date.isoformat(),
                "result": prior.result.value,
                "legs": [pick_row(p, prior, with_outcome=True) for p in _ordered(prior.picks)],
            }
            for prior in settled(season_parlays, parlay)[:PARLAY_HISTORY_SIZE]
        ],
        "group_season_legs_by_prop_type": group_season_records(parlay, season_parlays),
        "group_season_legs_by_game_situation": group_season_situations(parlay, season_parlays),
    }


def without_volatile(payload: dict[str, Any], *paths: tuple[str, ...]) -> dict[str, Any]:
    """A copy of a payload with the moving market fields stripped from the given games.

    Each path leads to a pick row; its game's volatile fields are dropped. Used only for
    hashing — the model still sees them.
    """
    stripped = copy.deepcopy(payload)
    for path in paths:
        node: Any = stripped
        for key in path:
            node = node[key]
        rows = node if isinstance(node, list) else [node]
        for row in rows:
            if row.get("game"):
                for name in VOLATILE_GAME_FIELDS:
                    row["game"].pop(name, None)
    return stripped
