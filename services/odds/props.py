"""What a sportsbook line means in this app's terms.

SportsGameOdds returns one event with every market on it — 1,255 odds for a single game,
of which only a few hundred are the kind of bet this league makes. This module is the
filter and the translation; nothing else needs to know their vocabulary.
"""
from dataclasses import dataclass

from models.constants import PropBetDirection, PropBetType

# Their statID to ours. Verified against a real 2026 Week 1 slate rather than their docs,
# whose examples are soccer.
STAT_TO_PROP: dict[str, PropBetType] = {
    "receiving_receptions": PropBetType.RECEPTIONS,
    "receiving_yards": PropBetType.REC_YDS,
    "receiving_longestReception": PropBetType.LONGEST_RECEPTION,
    "rushing_yards": PropBetType.RUSH_YDS,
    "rushing_attempts": PropBetType.RUSH_ATTEMPTS,
    "rushing_longestRush": PropBetType.LONGEST_RUSH,
    "rushing+receiving_yards": PropBetType.RUSH_REC_YDS,
    "passing_yards": PropBetType.PASSING_YDS,
    "passing_touchdowns": PropBetType.PASSING_TDS,
    "passing_interceptions": PropBetType.PASSING_INTS,
    "passing_attempts": PropBetType.PASS_ATTEMPTS,
    "passing_completions": PropBetType.PASS_COMPLETIONS,
    "passing_longestCompletion": PropBetType.LONGEST_COMPLETION,
    "defense_sacks": PropBetType.SACKS,
    "defense_combinedTackles": PropBetType.TACKLES_ASSISTS,
    "fieldGoals_made": PropBetType.FGS,
}

# Deliberately unmapped, so the absence is a decision rather than an oversight:
#
#   fantasyScore, firstTouchdown, lastTouchdown, kicking_totalPoints,
#   extraPoints_kicksMade, defense_soloTackles, defense_assistedTackles,
#   defense_interceptions, passing+rushing_yards
#
# None of them correspond to a PropBetType. Going the other way, TARGETS, RUSHING_TDS and
# RECEIVING_TDS have no line here — books price a combined `touchdowns` rather than
# splitting it, and rarely price targets at all — and LONGEST_TD is published by nobody,
# ESPN included. Those stay manual.

# Yes/no markets that are really a half-line in disguise. "Any touchdowns: yes" is exactly
# "over 0.5 touchdowns", which is the anytime-TD market everyone actually bets.
#
# Touchdowns come only from here, and deliberately not from the over/under above: that
# market carries alternate lines — over 1.5 at +1334, over 2.5 at longer — which are not
# bets this league makes and which crowded the real one off the row.
#
# Only touchdowns for now. rushing_touchdowns and receiving_touchdowns exist as yes/no
# markets too but are priced for a handful of players, so they would appear and vanish.
YES_NO_HALF_LINE: dict[str, PropBetType] = {
    "touchdowns": PropBetType.TDS,
}
HALF_LINE = 0.5

# Anything but a full-game over/under is not a bet this app can hold. Without these two
# filters a first-quarter passing line would prefill as though it were the whole game.
FULL_GAME = "game"
OVER_UNDER = "ou"
YES_NO = "yn"
# statEntityID takes these for team markets; anything else is a player id.
TEAM_ENTITIES = frozenset({"all", "home", "away"})


@dataclass(frozen=True)
class Line:
    """One priced number, in the shape a pick is made from."""
    prop_type: PropBetType
    line: float
    over_odds: str | None
    under_odds: str | None

    def direction_odds(self, direction: PropBetDirection) -> str | None:
        return self.over_odds if direction is PropBetDirection.OVER else self.under_odds


@dataclass(frozen=True)
class PlayerLines:
    """Everything one player is priced for on one slate."""
    name: str
    team: str | None
    provider_id: str
    # Which game, and when it starts. A slate spans a whole day of kickoffs, so knowing
    # both is how you tell an early game from a late one when picking.
    matchup: str | None
    starts_at: str | None
    lines: list[Line]


def parse_event(event: dict) -> list[PlayerLines]:
    """Pull the usable player props out of one game."""
    odds = event.get("odds") or {}
    players = event.get("players") or {}

    # teamID is long form ("TENNESSEE_TITANS_NFL"); the abbreviation on the event is what
    # PropBetTarget stores, and is what lets a name match be double-checked against a team.
    teams = event.get("teams") or {}
    team_abbr = {
        t.get("teamID"): (t.get("names") or {}).get("short")
        for t in teams.values()
    }
    # Conventionally away first, which is how a matchup is read everywhere else.
    away = ((teams.get("away") or {}).get("names") or {}).get("short")
    home = ((teams.get("home") or {}).get("names") or {}).get("short")
    matchup = f"{away} @ {home}" if away and home else None
    starts_at = (event.get("status") or {}).get("startsAt")

    # oddID carries the side, so the two halves of a market arrive as separate entries and
    # have to be rejoined before either means anything. Keyed on the bet type as well as the
    # stat, because a player can have both an over/under and a yes/no on touchdowns and they
    # are different bets at different numbers.
    by_market: dict[tuple[str, str, str], dict] = {}
    for odd in odds.values():
        entity = odd.get("statEntityID")
        stat_id = odd.get("statID")
        bet_type = odd.get("betTypeID")
        if entity in TEAM_ENTITIES or entity is None:
            continue
        if odd.get("periodID") != FULL_GAME:
            continue
        usable = (
            (bet_type == OVER_UNDER and stat_id in STAT_TO_PROP)
            or (bet_type == YES_NO and stat_id in YES_NO_HALF_LINE)
        )
        if not usable:
            continue
        by_market.setdefault((entity, stat_id, bet_type), {})[odd.get("sideID")] = odd

    # Keyed by what the bet actually is, so the same wager published under two market names
    # appears once. A book often lists an anytime touchdown both as "Any Touchdowns Yes/No"
    # and as an over/under at 0.5 — identical prices, same bet — and showing both reads as a
    # bug. Over/unders are inserted first and win, because their number comes from the book
    # rather than being inferred from the question.
    grouped: dict[str, dict[tuple[PropBetType, float], Line]] = {}
    ordered = sorted(by_market.items(), key=lambda kv: kv[0][2] != OVER_UNDER)
    for (entity, stat_id, bet_type), sides in ordered:
        if bet_type == YES_NO:
            # "yes" is the over on a half line, "no" the under. There is no number on the
            # market itself because the number is implied by the question.
            yes, no = sides.get("yes"), sides.get("no")
            if yes is None and no is None:
                continue
            line = Line(
                prop_type=YES_NO_HALF_LINE[stat_id],
                line=HALF_LINE,
                over_odds=(yes or {}).get("bookOdds"),
                under_odds=(no or {}).get("bookOdds"),
            )
            grouped.setdefault(entity, {}).setdefault((line.prop_type, line.line), line)
            continue

        over, under = sides.get("over"), sides.get("under")
        source = over or under
        raw = (source or {}).get("bookOverUnder")
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        line = Line(
            prop_type=STAT_TO_PROP[stat_id],
            line=value,
            over_odds=(over or {}).get("bookOdds"),
            under_odds=(under or {}).get("bookOdds"),
        )
        grouped.setdefault(entity, {}).setdefault((line.prop_type, line.line), line)

    result: list[PlayerLines] = []
    for entity, lines in grouped.items():
        player = players.get(entity) or {}
        name = player.get("name")
        if not name:
            # No name means nothing to resolve against a target, so the line is unusable
            # however well priced it is.
            continue
        result.append(PlayerLines(
            name=name,
            team=team_abbr.get(player.get("teamID")),
            provider_id=entity,
            matchup=matchup,
            starts_at=starts_at,
            # Stable order so the same player's lines do not shuffle between refreshes.
            # By prop then by line, so a player's two touchdown markets read 0.5 before 1.5.
            lines=sorted(lines.values(), key=lambda l: (l.prop_type.value, l.line)),
        ))
    return sorted(result, key=lambda p: p.name)
