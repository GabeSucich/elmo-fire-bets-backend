"""Talking to ESPN.

All of these are undocumented endpoints — the same standing as the athlete search this app
already relies on in player_finder. They can change without notice, so callers should treat
a shape they do not recognise as "no answer" rather than as a zero.
"""
import logging

import requests

from .gamelog import Gamelog

logger = logging.getLogger(__name__)

GAMELOG_URL = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{athlete_id}/gamelog"
SCHEDULE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team}/schedule"
SEARCH_URL = "https://site.web.api.espn.com/apis/common/v3/search"

TIMEOUT_SECONDS = 20
# Deliberately no User-Agent override. site.api.espn.com answers 403 to a browser-looking
# agent while accepting the default one requests sends, and site.web.api.espn.com accepts
# either — so the "helpful" Mozilla string breaks exactly one of the two hosts.


def fetch_gamelog(athlete_id: str, season: int) -> Gamelog | None:
    try:
        response = requests.get(
            GAMELOG_URL.format(athlete_id=athlete_id),
            params={"season": season},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return Gamelog.parse(response.json(), athlete_id=athlete_id, season=season)
    except Exception:
        logger.exception("gamelog fetch failed for athlete %s season %s", athlete_id, season)
        return None


def find_athlete_id(name: str) -> str | None:
    """ESPN's numeric athlete id, which the stats endpoints need.

    PropBetTarget stores ESPN's uuid, which the search returns alongside this but which the
    stats endpoints will not accept. Until every target carries its numeric id, this is how
    the gap is bridged.
    """
    try:
        response = requests.get(
            SEARCH_URL,
            params={
                "query": name, "limit": 5, "mode": "prefix", "type": "player",
                "sport": "football", "league": "nfl",
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        items = response.json().get("items") or []
        for item in items:
            if (item.get("displayName") or "").lower() == name.lower():
                return str(item["id"])
        return str(items[0]["id"]) if items else None
    except Exception:
        logger.exception("athlete search failed for %r", name)
        return None


def fetch_team_results(team_abbr: str, season: int) -> dict[int, float] | None:
    """Week to result for one team: 1 a win, 0 a loss, 0.5 a tie.

    Keyed on the abbreviation, which PropBetTarget already stores as team_name — so unlike
    player props, team picks need no new identifier at all.

    Only games that have actually finished are returned. A scheduled or in-progress game is
    left out entirely rather than reported as a loss.
    """
    try:
        response = requests.get(
            SCHEDULE_URL.format(team=team_abbr),
            params={"season": season},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        results: dict[int, float] = {}
        for event in response.json().get("events") or []:
            week = (event.get("week") or {}).get("number")
            competition = (event.get("competitions") or [{}])[0]
            status = ((competition.get("status") or {}).get("type") or {}).get("name")
            if week is None or status != "STATUS_FINAL":
                continue
            competitors = competition.get("competitors") or []
            mine = next((c for c in competitors if (c.get("team") or {}).get("abbreviation") == team_abbr), None)
            if mine is None:
                continue
            if mine.get("winner") is True:
                results[int(week)] = 1.0
            elif any(c.get("winner") is True for c in competitors):
                results[int(week)] = 0.0
            else:
                # Nobody marked a winner on a finished game — a tie.
                results[int(week)] = 0.5
        return results
    except Exception:
        logger.exception("schedule fetch failed for %s season %s", team_abbr, season)
        return None
