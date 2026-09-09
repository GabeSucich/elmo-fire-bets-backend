"""Fetching slates from SportsGameOdds."""
import datetime
import json
import logging
import os
import zoneinfo

import requests

from utils.env_vars import EnvVarName, load_env_var, load_optional_env_var

logger = logging.getLogger(__name__)

EVENTS_URL = "https://api.sportsgameodds.com/v2/events"
USAGE_URL = "https://api.sportsgameodds.com/v2/account/usage"
# A Sunday is around 12 games and takes ~2s; a single-game night is well under one.
TIMEOUT_SECONDS = 45
# Comfortably above the biggest NFL day, so a slate never needs paging.
PAGE_LIMIT = 100

# A slate is a day in the league's own reckoning, not in UTC. This matters because UTC
# midnight falls at 5pm Pacific, in the middle of the evening kickoff: every primetime game
# starts 15 to 35 minutes after it. Filtering on the bare date therefore cut Sunday's slate
# off before Sunday Night Football and filed that game under Monday, so a Sunday lay showed
# no evening game at all and a Monday lay showed nothing but the night before's.
#
# Pacific rather than Eastern because the app already reads kickoffs in Pacific everywhere
# else, and because the later zone is the one that keeps a whole slate on one date.
PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")


def _key() -> str:
    return load_env_var(EnvVarName.SPORTSODDS_API_KEY)


def _day_bounds(date: datetime.date) -> tuple[str, str]:
    """The instants a Pacific day begins and ends, as the API wants them.

    Computed through the zone rather than by subtracting a fixed offset: the season runs
    from September into February and crosses out of daylight saving in November, so the
    offset is -7 for part of it and -8 for the rest.
    """
    start = datetime.datetime.combine(date, datetime.time.min, tzinfo=PACIFIC)
    end = start + datetime.timedelta(days=1)
    as_utc = lambda d: d.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return as_utc(start), as_utc(end)


def _fixture_for(date: datetime.date) -> list[dict] | None:
    """A slate read from disk instead of from the API.

    Every request to this provider is billed against a monthly allowance of whole events,
    and development burns it far faster than production does — a Sunday is twelve, and it
    is entirely normal to re-run something twenty times while building. Pointing
    SPORTSODDS_FIXTURE_DIR at captured responses makes that free.

    Unset in production, where the whole point is live numbers. Capture new ones with
    capture_odds_fixture.py, which is the one thing that deliberately does spend.
    """
    directory = load_optional_env_var(EnvVarName.SPORTSODDS_FIXTURE_DIR)
    if not directory:
        return None
    path = os.path.join(directory, f"{date.isoformat()}.json")
    if not os.path.exists(path):
        # A date with no fixture is an empty slate rather than a live call, so a dev
        # machine can never silently start spending because of a typo in a date.
        logger.info("no odds fixture for %s in %s — treating as an empty slate", date, directory)
        return []
    with open(path) as f:
        body = json.load(f)
    events = body.get("data") if isinstance(body, dict) else body
    logger.info("odds slate %s served from fixture (%d events)", date, len(events or []))
    return events or []


def fetch_slate(date: datetime.date) -> list[dict] | None:
    """Every NFL game starting on one date, with all its odds.

    Filtered by date range rather than by week: the `week` and `season` parameters are
    accepted and then silently ignored — they return unfiltered results going back to 2024
    — so startsAfter/startsBefore is the only filter that actually works.

    One date rather than one week, because billing is per event returned. A Thursday costs
    one entity where the surrounding week would cost fifteen.

    The date is a Pacific day, so an evening kickoff belongs to the day it is played on
    rather than to the following one — see PACIFIC.
    """
    fixture = _fixture_for(date)
    if fixture is not None:
        return fixture

    starts_after, starts_before = _day_bounds(date)
    try:
        response = requests.get(
            EVENTS_URL,
            params={
                "leagueID": "NFL",
                "startsAfter": starts_after,
                "startsBefore": starts_before,
                "limit": PAGE_LIMIT,
            },
            headers={"X-Api-Key": _key()},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
        if not body.get("success"):
            logger.warning("odds slate rejected for %s: %s", date, str(body)[:200])
            return None
        return body.get("data") or []
    except Exception:
        logger.exception("odds slate fetch failed for %s", date)
        return None


def fetch_usage() -> dict | None:
    """Where the month's entity budget stands.

    Worth checking occasionally: responses carry no rate-limit headers, so this is the only
    way to see the quota, and exceeding it would otherwise fail silently mid-slate.
    """
    try:
        response = requests.get(USAGE_URL, headers={"X-Api-Key": _key()}, timeout=15)
        response.raise_for_status()
        return response.json().get("data")
    except Exception:
        logger.exception("odds usage fetch failed")
        return None
