"""ESPN as a data source for settling picks.

Split three ways on purpose: client.py knows how to talk to ESPN, gamelog.py knows the
shape of what comes back, and stats.py knows what any of it means for a given prop. A
change to their API should only ever land in the first two.
"""
from .client import fetch_gamelog, fetch_team_results, find_athlete_id
from .gamelog import Gamelog, GameStats
from .stats import resolve, supported

__all__ = [
    "fetch_gamelog", "fetch_team_results", "find_athlete_id",
    "Gamelog", "GameStats", "resolve", "supported",
]
