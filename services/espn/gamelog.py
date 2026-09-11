"""Typed reading of ESPN's athlete gamelog.

The endpoint is undocumented, so this module exists to keep every assumption about its
shape in one place. Everything observed against the 2025 season is written down here
rather than spread through the sync.

The response is three loosely-joined pieces:

  names        a positional list of machine stat keys, e.g. ["rushingYards", ...]
  seasonTypes  [{displayName, categories: [{events: [{eventId, stats: [...]}]}]}]
  events       {eventId: {week, gameDate, score, ...}}

`stats` lines up with `names` by index, and the week is only reachable by looking the
eventId back up in `events`. So reading one week is a two-step join, not a field access.
"""
import re
from dataclasses import dataclass
from typing import Iterator

# The stat columns depend on the athlete's position — a quarterback's gamelog and a
# kicker's share almost no keys — so nothing here may assume a fixed set or a fixed order.
# Missing is normal; absence is expressed by the key simply not being present.
ABSENT = "-"

# seasonTypes carries no numeric type, only a display name, and the postseason is not
# reliably last — for a player who reached the playoffs it comes FIRST. Postseason week
# numbers also restart at 1, so mixing them in would collide with the unique constraint on
# (season_pick_id, week). Filtering by this string is therefore load-bearing, not tidiness.
REGULAR_SEASON = "Regular Season"


@dataclass(frozen=True)
class GameStats:
    """One game's line for one athlete, keyed by ESPN's machine stat names."""
    week: int
    event_id: str
    values: dict[str, str]

    def raw(self, key: str) -> str | None:
        value = self.values.get(key)
        return None if value in (None, "", ABSENT) else value

    def number(self, key: str) -> float | None:
        """A stat as a number, or None if the athlete has no such stat this week."""
        value = self.raw(key)
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def made_of(self, key: str) -> float | None:
        """The left half of a made-attempts pair.

        Kicking stats arrive as one string — fieldGoalsMade-fieldGoalAttempts is "1-2" —
        so they cannot be read as a number without splitting first. The live boxscore
        writes the same pair with a slash instead of a hyphen, so both are accepted.
        """
        value = self.raw(key)
        if value is None:
            return None
        try:
            return float(re.split(r"[-/]", value)[0])
        except (ValueError, IndexError):
            return None

    def has(self, key: str) -> bool:
        return self.raw(key) is not None


@dataclass(frozen=True)
class Gamelog:
    """An athlete's regular season, week by week."""
    athlete_id: str
    season: int
    weeks: dict[int, GameStats]

    def __iter__(self) -> Iterator[GameStats]:
        return iter(self.weeks[w] for w in sorted(self.weeks))

    def week(self, number: int) -> GameStats | None:
        """Absent means the athlete did not appear — a bye, or inactive.

        The two are the same thing to us: SeasonPickWeek records played=False for either,
        so no second call to a schedule endpoint is needed to tell them apart.
        """
        return self.weeks.get(number)

    @classmethod
    def parse(cls, payload: dict, athlete_id: str, season: int) -> "Gamelog":
        names: list[str] = payload.get("names") or []
        # week lives here, not on the stat line
        events: dict = payload.get("events") or {}

        weeks: dict[int, GameStats] = {}
        for season_type in payload.get("seasonTypes") or []:
            if REGULAR_SEASON not in (season_type.get("displayName") or ""):
                continue
            for category in season_type.get("categories") or []:
                for event in category.get("events") or []:
                    event_id = str(event.get("eventId"))
                    meta = events.get(event_id) or {}
                    week = meta.get("week")
                    if week is None:
                        continue
                    stats = event.get("stats") or []
                    weeks[int(week)] = GameStats(
                        week=int(week),
                        event_id=event_id,
                        # zip truncates to the shorter of the two, which is the behaviour
                        # wanted if ESPN ever sends a stats row that disagrees with names.
                        values=dict(zip(names, stats)),
                    )
        return cls(athlete_id=str(athlete_id), season=season, weeks=weeks)
