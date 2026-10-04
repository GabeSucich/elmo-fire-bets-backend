"""Talking to ESPN.

All of these are undocumented endpoints — the same standing as the athlete search this app
already relies on in player_finder. They can change without notice, so callers should treat
a shape they do not recognise as "no answer" rather than as a zero.
"""
import datetime
import json
import logging
import os
import zoneinfo
from dataclasses import dataclass

import requests

from utils.env_vars import EnvVarName, load_optional_env_var

from .gamelog import Gamelog
from .stats import normalize_boxscore

logger = logging.getLogger(__name__)

# A slate is a day in the league's own reckoning, not in UTC — the same reasoning, and the
# same zone, as services/odds/client.py. Through the zone rather than a fixed offset
# because the season crosses out of daylight saving in November.
PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")


def _pacific_day(date: datetime.date) -> tuple[datetime.datetime, datetime.datetime]:
    start = datetime.datetime.combine(date, datetime.time.min, tzinfo=PACIFIC)
    return start, start + datetime.timedelta(days=1)


def _fixture(name: str) -> dict | None:
    """A captured ESPN response, read from disk instead of fetched.

    Not about cost — ESPN charges nothing — but about being able to test at all. The two
    things worth asserting against are a game in progress and a game that has just gone
    final, and neither can be summoned on demand: a live boxscore exists for about three
    hours a week and is different every time you look at it. A captured one holds still.

    Unset in production, where the whole point is the live number. Capture new ones with
    capture_espn_fixture.py.
    """
    directory = load_optional_env_var(EnvVarName.ESPN_FIXTURE_DIR)
    if not directory:
        return None
    path = os.path.join(directory, f"{name}.json")
    if not os.path.exists(path):
        # Absent is "nothing there", never a silent fall-through to the network: a test
        # that quietly started hitting ESPN would pass or fail on that week's real games.
        logger.info("no ESPN fixture %s in %s", name, directory)
        return {}
    with open(path) as f:
        return json.load(f)


def _parse_instant(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

GAMELOG_URL = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{athlete_id}/gamelog"
SCHEDULE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team}/schedule"
SEARCH_URL = "https://site.web.api.espn.com/apis/common/v3/search"
SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"
ATHLETE_URL = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{athlete_id}"

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


def fetch_athlete_teams(athlete_id: str, season: int) -> dict[str, str] | None:
    """Which team an athlete played for in each game of a season, by ESPN event id.

    Postseason included — unlike Gamelog, which keeps to the regular season because its
    week numbers restart. Here only the event id matters, and it does not.

    The only reliable answer to which game a past pick was on. PropBetTarget.team_name is
    the team a player is at *now*, so a traded player's old picks match the wrong game by
    team, and on a Sunday that is usually a real game rather than none at all.
    """
    try:
        response = requests.get(
            GAMELOG_URL.format(athlete_id=athlete_id),
            params={"season": season},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        events = response.json().get("events") or {}
        return {
            str(event_id): abbreviation
            for event_id, meta in events.items()
            if (abbreviation := ((meta or {}).get("team") or {}).get("abbreviation"))
        }
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


def fetch_athlete_team(athlete_id: str) -> str | None:
    """The team an athlete plays for right now.

    Deliberately its own call rather than something read off the gamelog. A gamelog says
    which teams an athlete has played games for, which is no help for the case that needs
    answering — a player who has changed teams and not yet played, whose gamelog comes
    back empty. This endpoint answers for them too.

    None on any failure, which callers must treat as "unchanged" rather than "no team":
    overwriting a good abbreviation with nothing would take the schedule lookup with it.
    """
    try:
        response = requests.get(ATHLETE_URL.format(athlete_id=athlete_id), timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        athlete = payload.get("athlete") or payload
        return ((athlete.get("team") or {}).get("abbreviation")) or None
    except Exception:
        logger.exception("athlete team lookup failed for %s", athlete_id)
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


@dataclass(frozen=True)
class GameSide:
    """One team's half of a game: where it played and, once there is one, its score."""
    abbreviation: str
    is_home: bool
    score: int | None


@dataclass(frozen=True)
class SlateGame:
    """One game on a slate, as far as a parlay needs to care."""
    event_id: str
    # ESPN's own reading: "pre" before kickoff, "in" while it is being played, "post" once
    # it is over. The only reliable way to tell a game that has not started from a player
    # who has done nothing yet.
    state: str
    # The human form of the same thing: "Final", "Q3 4:12", "9/13 - 1:00 PM EDT".
    detail: str
    # Both teams, so a pick can be matched to its game by the abbreviation already stored
    # on its target.
    teams: frozenset[str]
    # Everything below is context for pick assessments rather than for progress, and is
    # optional throughout: a scoreboard that leaves any of it out is still a usable slate.
    # Naive UTC, matching the timestamps the rest of the schema stores.
    kickoff_at: datetime.datetime | None = None
    week: int | None = None
    indoor: bool | None = None
    # London, Germany, Brazil and the like. One side is still listed as home there, and
    # that label means nothing, so anything reading home or away has to check this first.
    neutral_site: bool | None = None
    sides: tuple[GameSide, ...] = ()
    # Only published before kickoff — ESPN drops odds from a game once it is under way, so
    # these are None for anything already played and can never be backfilled.
    # From the home side's point of view: -3.0 means the home team is giving three.
    home_spread: float | None = None
    total: float | None = None
    # "Mostly sunny, 68°F". Forecast, so only ever present on games yet to be played.
    weather: str | None = None

    def side(self, abbreviation: str) -> GameSide | None:
        return next((s for s in self.sides if s.abbreviation == abbreviation), None)

    def opponent_of(self, abbreviation: str) -> GameSide | None:
        if self.side(abbreviation) is None:
            return None
        return next((s for s in self.sides if s.abbreviation != abbreviation), None)

    def spread_for(self, abbreviation: str) -> float | None:
        """The line from one team's point of view: negative when it is favoured."""
        side = self.side(abbreviation)
        if side is None or self.home_spread is None:
            return None
        return self.home_spread if side.is_home else -self.home_spread


def _int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _weather(event: dict) -> str | None:
    weather = event.get("weather") or {}
    described = weather.get("displayValue")
    temperature = weather.get("temperature")
    if described and temperature is not None:
        return f"{described}, {temperature}\u00b0F"
    return described or None


def fetch_slate_games(date: datetime.date) -> list[SlateGame] | None:
    """Every NFL game ESPN files under one calendar date.

    ESPN files a game under the date it kicks off *locally*, not in UTC — a Wednesday
    night opener at 00:20Z comes back under the 9th, not the 10th. That happens to be
    exactly what a parlay's competition_date means, so no conversion is needed; the
    window check below is what catches a game ESPN has filed somewhere unexpected.
    """
    try:
        fixture = _fixture(f"scoreboard-{date.isoformat()}")
        if fixture is None:
            response = requests.get(
                SCOREBOARD_URL,
                params={"dates": date.strftime("%Y%m%d")},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            fixture = response.json()

        start, end = _pacific_day(date)
        games: list[SlateGame] = []
        for event in fixture.get("events") or []:
            kickoff = _parse_instant(event.get("date"))
            if kickoff is None or not (start <= kickoff < end):
                continue
            competition = (event.get("competitions") or [{}])[0]
            status = (competition.get("status") or {}).get("type") or {}
            state = status.get("state") or "pre"
            sides = tuple(
                GameSide(
                    abbreviation=abbreviation,
                    is_home=c.get("homeAway") == "home",
                    # ESPN sends "0" for a game that has not started, which is not a score.
                    score=_int_or_none(c.get("score")) if state != "pre" else None,
                )
                for c in (competition.get("competitors") or [])
                if (abbreviation := (c.get("team") or {}).get("abbreviation"))
            )
            venue = competition.get("venue") or {}
            odds = (competition.get("odds") or [{}])[0]
            games.append(SlateGame(
                event_id=str(event.get("id")),
                state=state,
                detail=status.get("shortDetail") or status.get("detail") or "",
                teams=frozenset(s.abbreviation for s in sides),
                kickoff_at=kickoff.astimezone(datetime.timezone.utc).replace(tzinfo=None),
                week=_int_or_none((event.get("week") or {}).get("number")),
                indoor=venue.get("indoor"),
                neutral_site=competition.get("neutralSite"),
                # Without homeAway the sides cannot be told apart, and a spread read from
                # the wrong one is worse than none.
                sides=sides if all(c.get("homeAway") for c in competition.get("competitors") or []) else (),
                home_spread=_float_or_none(odds.get("spread")),
                total=_float_or_none(odds.get("overUnder")),
                weather=_weather(event),
            ))
        return games
    except Exception:
        logger.exception("scoreboard fetch failed for %s", date)
        return None


def fetch_boxscore(event_id: str) -> dict[str, dict[str, dict[str, str]]] | None:
    """One game's player stats, as {team: {player name: {stat key: value}}}.

    The same shape the gamelog produces, so services/espn/stats.py resolves against either
    without knowing which it was handed. The keys agree almost everywhere; where they do
    not it is because the boxscore joins a made-attempts pair with "/" where the gamelog
    uses "-", which GameStats.made_of accepts either way.
    """
    try:
        fixture = _fixture(f"summary-{event_id}")
        if fixture is None:
            response = requests.get(
                SUMMARY_URL, params={"event": event_id}, timeout=TIMEOUT_SECONDS
            )
            response.raise_for_status()
            fixture = response.json()

        by_team: dict[str, dict[str, dict[str, str]]] = {}
        for team in ((fixture.get("boxscore") or {}).get("players") or []):
            abbr = (team.get("team") or {}).get("abbreviation")
            if not abbr:
                continue
            players = by_team.setdefault(abbr, {})
            for category in team.get("statistics") or []:
                keys = category.get("keys") or []
                for entry in category.get("athletes") or []:
                    name = (entry.get("athlete") or {}).get("displayName")
                    athlete_id = str((entry.get("athlete") or {}).get("id") or "")
                    if not athlete_id:
                        continue
                    # Categories are per discipline, so one athlete appears in several —
                    # a receiver in receiving and rushing. Merging rather than replacing
                    # is what makes a combined prop like rush+rec yards resolvable.
                    stats = players.setdefault(athlete_id, {"__name__": name or ""})
                    stats.update(normalize_boxscore(dict(zip(keys, entry.get("stats") or []))))
        return by_team
    except Exception:
        logger.exception("boxscore fetch failed for event %s", event_id)
        return None
