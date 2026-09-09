"""Save a real slate to disk so development can stop paying for it.

The one script here that deliberately spends the monthly allowance. Each date costs one
entity per game on it — a Thursday is 1, a Sunday around 12 — so capture what you need and
then work offline against it.

    uv run capture_odds_fixture.py 2026-09-13 2026-09-10

Writes <SPORTSODDS_FIXTURE_DIR>/<date>.json. With that variable set, services/odds reads
these instead of calling the API at all.
"""
import argparse
import datetime
import json
import os
import sys

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env")

import requests

from services.odds.client import EVENTS_URL, PAGE_LIMIT, TIMEOUT_SECONDS, fetch_usage
from utils.env_vars import EnvVarName, load_env_var, load_optional_env_var


def capture(date: datetime.date, directory: str) -> int:
    """Fetch one date live and write it. Returns how many events it cost."""
    response = requests.get(
        EVENTS_URL,
        params={
            "leagueID": "NFL",
            "startsAfter": date.isoformat(),
            "startsBefore": (date + datetime.timedelta(days=1)).isoformat(),
            "limit": PAGE_LIMIT,
        },
        headers={"X-Api-Key": load_env_var(EnvVarName.SPORTSODDS_API_KEY)},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    body = response.json()
    events = body.get("data") or []

    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{date.isoformat()}.json")
    with open(path, "w") as f:
        json.dump(body, f)
    size = os.path.getsize(path) / 1e6
    print(f"  {date}: {len(events)} events -> {path} ({size:.1f}MB)")
    return len(events)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dates", nargs="+", help="dates to capture, YYYY-MM-DD")
    args = parser.parse_args()

    directory = load_optional_env_var(EnvVarName.SPORTSODDS_FIXTURE_DIR)
    if not directory:
        print("SPORTSODDS_FIXTURE_DIR is not set — nowhere to write to.")
        return 1

    before = (fetch_usage() or {}).get("rateLimits", {}).get("per-month", {})
    print(f"  entities used before: {before.get('current-entities')} of {before.get('max-entities')}\n")

    spent = 0
    for raw in args.dates:
        spent += capture(datetime.date.fromisoformat(raw), directory)

    after = (fetch_usage() or {}).get("rateLimits", {}).get("per-month", {})
    print(f"\n  spent {spent} entities; now {after.get('current-entities')} of {after.get('max-entities')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
