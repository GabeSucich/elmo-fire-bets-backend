"""Holding a slate so it is fetched once rather than once per person looking at it.

Keyed by date, which is both how the API filters and how a parlay is scheduled, so a
Thursday lay never pulls the surrounding Sunday.

In memory rather than in the database: the data is worthless within the hour, the process
is single and long-lived, and a restart costs one refetch. The monthly entity budget is
what this exists to protect — five people opening the same slate is one fetch, not five.
"""
import datetime
import logging
import threading
import time

from .client import fetch_slate
from .props import PlayerLines, parse_event

logger = logging.getLogger(__name__)

# The free tier only refreshes its own data every 10 minutes, so anything shorter would
# spend entities to receive the same numbers back.
TTL_SECONDS = 15 * 60

_cache: dict[datetime.date, tuple[float, list[PlayerLines]]] = {}
# Serialises the fetch itself. The endpoint runs this on a worker thread, so five people
# opening the same lay at once genuinely arrive together — without this they would each
# find an empty cache and each spend a slate's worth of the monthly entity budget on
# identical numbers. Held across the request so the others wait and then read the result.
_fetch_lock = threading.Lock()


def cached_at(date: datetime.date) -> float | None:
    entry = _cache.get(date)
    return entry[0] if entry else None


def get_slate(date: datetime.date, force: bool = False) -> tuple[list[PlayerLines], float, bool]:
    """The slate for one date, refetched only once it has gone stale.

    Returns the lines, when they were fetched, and whether this call did the fetching.

    A failed refresh keeps whatever was already held rather than emptying the cache: stale
    lines are far more useful than none, and the next request will try again.
    """
    now = time.time()
    entry = _cache.get(date)
    if entry and not force and now - entry[0] < TTL_SECONDS:
        return entry[1], entry[0], False

    with _fetch_lock:
        # Checked again inside the lock: whoever was ahead in the queue has by now filled
        # the cache, and the wait was to read their answer rather than to repeat it.
        now = time.time()
        entry = _cache.get(date)
        if entry and not force and now - entry[0] < TTL_SECONDS:
            return entry[1], entry[0], False
        return _refresh(date, entry, now)


def _refresh(
    date: datetime.date,
    entry: tuple[float, list[PlayerLines]] | None,
    now: float,
) -> tuple[list[PlayerLines], float, bool]:
    """Fetches and parses one slate. Only ever called holding the fetch lock."""
    events = fetch_slate(date)
    if events is None:
        if entry:
            logger.warning("odds refresh failed for %s, serving cached copy", date)
            return entry[1], entry[0], False
        return [], now, True

    players: list[PlayerLines] = []
    for event in events:
        players.extend(parse_event(event))
    # One player can appear once per game only, so no merging is needed — but sorting here
    # keeps the order stable for the client across refreshes.
    players.sort(key=lambda p: p.name)

    _cache[date] = (now, players)
    logger.info("odds slate %s: %d games, %d players with lines", date, len(events), len(players))
    return players, now, True
