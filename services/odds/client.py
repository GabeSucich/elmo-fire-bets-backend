"""Fetching slates from SportsGameOdds."""
import datetime
import json
import logging
import os

import requests

from utils.env_vars import EnvVarName, load_env_var, load_optional_env_var

logger = logging.getLogger(__name__)

EVENTS_URL = "https://api.sportsgameodds.com/v2/events"
USAGE_URL = "https://api.sportsgameodds.com/v2/account/usage"
# A Sunday is around 12 games and takes ~2s; a single-game night is well under one.
TIMEOUT_SECONDS = 45
# Comfortably above the biggest NFL day, so a slate never needs paging.
PAGE_LIMIT = 100


def _key() -> str:
    return load_env_var(EnvVarName.SPORTSODDS_API_KEY)


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
    """
    fixture = _fixture_for(date)
    if fixture is not None:
        return fixture

    try:
        response = requests.get(
            EVENTS_URL,
            params={
                "leagueID": "NFL",
                "startsAfter": date.isoformat(),
                "startsBefore": (date + datetime.timedelta(days=1)).isoformat(),
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
