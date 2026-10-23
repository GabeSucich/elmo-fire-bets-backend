"""Slang handed to the model a few at a time, so cards on one slate don't all sound alike.

Each card is written in its own call and never sees the others, so any phrase in the prompt
itself ends up on every card. Instead each call gets a small sample from this bank, picked
from the subject of the card: the same pick always gets the same sample, and different
picks get different ones. Edit freely — bump PROMPT_VERSION in prompts.py when you do.
"""
import hashlib
import json
import random
from typing import Any

PHRASES = [
    "cooked",
    "fumbling the bag",
    "down bad",
    "it's giving desperation",
    "delulu",
    "no shot",
    "caught in 4K",
    "certified bozo behavior",
    "clown behavior",
    "the audacity",
    "negative aura",
    "skill issue",
    "mid",
    "bro really thinks",
    "crash out",
    "living rent free",
    "it's so over",
    "this ain't it",
    "copium",
    "fraud watch",
    "washed",
    "bricked",
    "cap",
    "glazing",
    "dog water",
    "shit the bed",
    "piss-poor",
    "dumbass move",
    "hell no",
    "bullshit",
    "ass",
    "what the hell",
    "sit this one out",
    "pure vibes, zero receipts",
    "hold this L",
]

# The group's own sayings, each with what it means. Inside jokes rather than slang: a few
# cards per parlay get one each, with leave to rework the words. Add to this as the group
# coins new ones.
GROUP_SAYINGS = [
    ("Veto that shit", "the pick is bad and the group should veto it"),
    ("a bum", "a gambler who is bad at picking in some way"),
    ("throwing out meatball subs", "a gambler who has been picking poorly"),
    ("his picks are dih", "his picks are bad"),
    ("not that YN", "he is not good at picking — said of the gambler himself, never of his picks"),
    ("a goomba", "he is bad at picking"),
    ("robbing Miles of a college fund", "he is costing the group money"),
    ("finger is in his ass", "he can't make good picks"),
    ("gooning too hard to think straight", "he can't make picks"),
    ("needs to be guardian capped", "he needs to be stopped from making bad picks"),
    ("picks are worse than his FG kicks", "he can't kick a field goal, and his picks are even worse"),
    ("get his ass eaten by Benny", "he is really bad at making picks"),
    ("getting pegged", "doing a bad job of picking"),
]
# How many cards in a parlay get a saying — each a different one, so none repeats.
SAYINGS_PER_PARLAY = 3

SAMPLE_SIZE = 3
# Share of cards told they must swear. The rest are told nothing, and may swear anyway:
# left wholly to itself the model swore on under a fifth of cards.
SWEAR_SHARE = 0.5


def assign_sayings(parlay_id: int, parlay_order: int, pick_ids: list[int | None]) -> dict[int | None, tuple[str, str]]:
    """Which cards in a parlay get a saying, and which one: distinct sayings, distinct cards.

    Decided across the whole parlay because each card is written in its own call and could
    not otherwise know what the others used. The sayings rotate through the catalog by the
    parlay's place in the season, so back-to-back parlays don't reuse them; the cards that
    get them are keyed by pick id (None for the slate), so a card keeps its saying when the
    rest of the parlay changes.
    """
    count = min(SAYINGS_PER_PARLAY, len(GROUP_SAYINGS), len(pick_ids))
    start = parlay_order * count
    sayings = [GROUP_SAYINGS[(start + i) % len(GROUP_SAYINGS)] for i in range(count)]
    cards = sorted(pick_ids, key=lambda pick_id: hashlib.sha256(f"{parlay_id}:{pick_id}".encode()).hexdigest())
    return dict(zip(cards, sayings))


def flavor_for(payload: dict[str, Any], saying: tuple[str, str] | None = None) -> str:
    """The voice note for one card, fixed by what the card is about."""
    subject = payload.get("pick") or payload.get("slate")
    seed = hashlib.sha256(json.dumps(subject, sort_keys=True, default=str).encode()).hexdigest()
    rng = random.Random(seed)
    swear = rng.random() < SWEAR_SHARE
    phrases = ", ".join(rng.sample(PHRASES, SAMPLE_SIZE))
    return (
        "THIS CARD\n"
        + ("Swearing required: every suggestion on this card swears at least once.\n" if swear else "")
        + f"Slang to riff on (one at most, reworded, or none): {phrases}"
        + (f'\nGroup saying to work in: "{saying[0]}" — {saying[1]}' if saying else "")
    )
