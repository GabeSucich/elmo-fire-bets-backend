"""Save real ESPN responses to disk so the progress sync can be tested at all.

Unlike capture_odds_fixture.py this costs nothing — ESPN is free. What it buys is a thing
that holds still. A live boxscore exists for about three hours a week and reads differently
every time you look at it, so the only way to assert anything about a game in progress is
to keep one.

    uv run capture_espn_fixture.py 2026-09-09
    uv run capture_espn_fixture.py 2026-09-13 --event 401872656

Writes <ESPN_FIXTURE_DIR>/scoreboard-<date>.json and summary-<event>.json for every game
on the slate. With that variable set, services/espn reads these instead of calling out.
"""
import argparse
import datetime
import json
import os
import sys

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env")

import requests

from services.espn.client import SCOREBOARD_URL, SUMMARY_URL, TIMEOUT_SECONDS
from utils.env_vars import EnvVarName, load_optional_env_var


def prune_scoreboard(body: dict) -> dict:
    """Only the fields fetch_slate_games reads.

    A full scoreboard is a third of a megabyte of broadcast listings, records and odds,
    none of which this app looks at. Keeping the shape but dropping the bulk makes the
    fixture something a person can open and check against, and makes the dependency
    explicit: if the client ever starts reading something else, the fixture stops
    supplying it and the test says so.
    """
    return {"events": [
        {
            "id": e.get("id"),
            "shortName": e.get("shortName"),
            "date": e.get("date"),
            "competitions": [{
                "status": {"type": ((c.get("status") or {}).get("type") or {})},
                "competitors": [
                    {"team": {"abbreviation": (comp.get("team") or {}).get("abbreviation")}}
                    for comp in (c.get("competitors") or [])
                ],
            } for c in (e.get("competitions") or [])],
        }
        for e in (body.get("events") or [])
    ]}


def prune_summary(body: dict) -> dict:
    """Only boxscore.players, which is all fetch_boxscore reads."""
    return {"boxscore": {"players": [
        {
            "team": {"abbreviation": (t.get("team") or {}).get("abbreviation")},
            "statistics": [
                {
                    "name": c.get("name"),
                    "keys": c.get("keys"),
                    "athletes": [
                        {
                            "athlete": {
                                "id": (a.get("athlete") or {}).get("id"),
                                "displayName": (a.get("athlete") or {}).get("displayName"),
                            },
                            "stats": a.get("stats"),
                        }
                        for a in (c.get("athletes") or [])
                    ],
                }
                for c in (t.get("statistics") or [])
            ],
        }
        for t in ((body.get("boxscore") or {}).get("players") or [])
    ]}}


def _write(directory: str, name: str, body: dict) -> None:
    path = os.path.join(directory, f"{name}.json")
    with open(path, "w") as f:
        json.dump(body, f, indent=2)
    print(f"  wrote {path} ({os.path.getsize(path) // 1024} KB)")


def capture(date: datetime.date, directory: str, only: str | None) -> None:
    board = requests.get(
        SCOREBOARD_URL, params={"dates": date.strftime("%Y%m%d")}, timeout=TIMEOUT_SECONDS
    )
    board.raise_for_status()
    body = board.json()
    _write(directory, f"scoreboard-{date.isoformat()}", prune_scoreboard(body))

    for event in body.get("events") or []:
        event_id = str(event.get("id"))
        if only and event_id != only:
            continue
        status = (((event.get("competitions") or [{}])[0].get("status") or {}).get("type") or {})
        summary = requests.get(
            SUMMARY_URL, params={"event": event_id}, timeout=TIMEOUT_SECONDS
        )
        summary.raise_for_status()
        print(f"  {event.get('shortName')} — {status.get('state')} / {status.get('shortDetail')}")
        _write(directory, f"summary-{event_id}", prune_summary(summary.json()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dates", nargs="+", help="slate dates, YYYY-MM-DD")
    parser.add_argument("--event", help="only capture this event's boxscore")
    args = parser.parse_args()

    directory = load_optional_env_var(EnvVarName.ESPN_FIXTURE_DIR)
    if not directory:
        print("ESPN_FIXTURE_DIR is not set — nowhere to write to.", file=sys.stderr)
        return 1
    os.makedirs(directory, exist_ok=True)

    for raw in args.dates:
        date = datetime.date.fromisoformat(raw)
        print(f"{date}:")
        capture(date, directory, args.event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
