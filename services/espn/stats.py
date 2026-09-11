"""Turning one game's ESPN line into the number a prop bet is settled against.

Resolution is by stat *name*, never by position in the array: the columns differ entirely
between a quarterback, a running back, a kicker and a linebacker, so an index that is
rushing yards for one athlete is something else for the next.

Every rule returns None rather than a zero when it cannot answer. That distinction is the
whole point of this module — a missing week is recoverable, a wrong 0 silently settles a
bet against someone.
"""
from models.constants import PropBetType
from .gamelog import GameStats

# Straight lookups: one prop, one ESPN key.
DIRECT: dict[PropBetType, str] = {
    PropBetType.TARGETS: "receivingTargets",
    PropBetType.RECEPTIONS: "receptions",
    PropBetType.REC_YDS: "receivingYards",
    PropBetType.RECEIVING_TDS: "receivingTouchdowns",
    PropBetType.LONGEST_RECEPTION: "longReception",
    PropBetType.RUSH_YDS: "rushingYards",
    PropBetType.RUSH_ATTEMPTS: "rushingAttempts",
    PropBetType.RUSHING_TDS: "rushingTouchdowns",
    PropBetType.LONGEST_RUSH: "longRushing",
    PropBetType.PASSING_YDS: "passingYards",
    PropBetType.PASSING_TDS: "passingTouchdowns",
    PropBetType.PASS_ATTEMPTS: "passingAttempts",
    PropBetType.PASS_COMPLETIONS: "completions",
    PropBetType.LONGEST_COMPLETION: "longPassing",
    # ESPN's totalTackles is solo + assisted, which is exactly what this prop means.
    # Verified against four Parsons games in 2025: total always equalled solo + assist.
    PropBetType.TACKLES_ASSISTS: "totalTackles",
}

# Sums across categories. A skill player's "TDs" is rushing plus receiving; passing
# touchdowns are deliberately excluded, so a quarterback's TDs prop settles on what they
# ran and caught rather than what they threw. If that is ever the wrong reading for this
# league it is a one-line change, but it must be a decision rather than a default.
SUMS: dict[PropBetType, tuple[str, ...]] = {
    PropBetType.RUSH_REC_YDS: ("rushingYards", "receivingYards"),
    PropBetType.TDS: ("rushingTouchdowns", "receivingTouchdowns"),
}

# Stat names that mean opposite things depending on who the athlete is. ESPN uses one key
# for both, so each needs a sibling key present to prove which sense applies:
#
#   sacks         a quarterback's sacks TAKEN, or a defender's sacks MADE
#   interceptions a quarterback's picks THROWN, or a defender's picks CAUGHT
#
# Resolving these blind is how a defensive player's interceptions get settled as though
# they were a quarterback's.
GUARDED: dict[PropBetType, tuple[str, str]] = {
    # (stat to read, key that must also be present for it to mean what we want)
    PropBetType.SACKS: ("sacks", "totalTackles"),
    PropBetType.PASSING_INTS: ("interceptions", "passingAttempts"),
}

# Kicking arrives as "made-attempts" in a single string, so it needs splitting.
MADE_ATTEMPTS: dict[PropBetType, str] = {
    PropBetType.FGS: "fieldGoalsMade-fieldGoalAttempts",
}

# Stats the live boxscore names differently from the gamelog. Checked key by key against a
# real summary response rather than assumed: of the twenty markets this league bets, only
# these three disagree, and one more has no boxscore equivalent at all.
#
#   completions/passingAttempts   one field where the gamelog keeps two
#   fieldGoalsMade/…              the same pair the gamelog joins with a hyphen
#   longPassing                   absent from the boxscore entirely, so LONGEST_COMPLETION
#                                 cannot be read live at all — one pick in league history
# Markets the live boxscore cannot express at all, however much of the game has been
# played. Kept apart from "the player recorded none of it", because the two look identical
# in the data and mean opposite things: one is a zero, the other is no answer.
NOT_IN_BOXSCORE: frozenset[PropBetType] = frozenset({PropBetType.LONGEST_COMPLETION})


def normalize_boxscore(values: dict[str, str]) -> dict[str, str]:
    """A boxscore stat line, renamed to the vocabulary `resolve` already speaks.

    Done here rather than in the fetcher so that every assumption about ESPN's naming
    lives in one file, which is what this module is for.
    """
    out = dict(values)

    pair = values.get("completions/passingAttempts")
    if pair and "/" in pair:
        made, _, attempts = pair.partition("/")
        out.setdefault("completions", made)
        out.setdefault("passingAttempts", attempts)

    kicking = values.get("fieldGoalsMade/fieldGoalAttempts")
    if kicking:
        # made_of splits on either separator, so the value carries across unchanged.
        out.setdefault("fieldGoalsMade-fieldGoalAttempts", kicking)

    return out

# ESPN publishes longest rush, longest reception and longest pass, but nothing for the
# longest play that was a touchdown. There is no key to map this to at any position, so it
# stays a manual entry rather than being approximated from something adjacent.
UNSUPPORTED: frozenset[PropBetType] = frozenset({PropBetType.LONGEST_TD})


def resolve(prop_type: PropBetType, game: GameStats) -> float | None:
    """The value this prop settles on for this game, or None if it cannot be known."""
    if prop_type in UNSUPPORTED:
        return None

    key = DIRECT.get(prop_type)
    if key is not None:
        return game.number(key)

    key = MADE_ATTEMPTS.get(prop_type)
    if key is not None:
        return game.made_of(key)

    guard = GUARDED.get(prop_type)
    if guard is not None:
        stat, required = guard
        return game.number(stat) if game.has(required) else None

    keys = SUMS.get(prop_type)
    if keys is not None:
        parts = [game.number(k) for k in keys]
        present = [p for p in parts if p is not None]
        # A player with rushing but no receiving line still has a real combined total; a
        # player with neither has no line at all and must not come back as 0.
        return sum(present) if present else None

    return None


def supported(prop_type: PropBetType) -> bool:
    """Whether the sync can settle this prop at all, without needing a game to check."""
    return prop_type not in UNSUPPORTED and (
        prop_type in DIRECT or prop_type in SUMS
        or prop_type in GUARDED or prop_type in MADE_ATTEMPTS
    )
