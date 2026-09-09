"""Sportsbook lines for a slate, for prefilling a pick."""
import asyncio
import datetime

from pydantic import BaseModel
from fastapi import APIRouter, Depends

from models import PropBetType
from services.odds import get_slate

from .auth import manager

router = APIRouter(
    prefix="/odds",
    dependencies=[Depends(manager)],
    tags=["Odds"],
)


class LineResponseData(BaseModel):
    prop_type: PropBetType
    line: float
    over_odds: str | None
    under_odds: str | None


class PlayerLinesResponseData(BaseModel):
    name: str
    team: str | None
    # "SF @ LA" — which game this player's lines belong to.
    matchup: str | None
    # Kickoff, in UTC. Sent as an instant rather than a formatted string so the client can
    # show it in the league's own timezone.
    starts_at: datetime.datetime | None
    lines: list[LineResponseData]


class SlateResponseData(BaseModel):
    date: datetime.date
    # When the numbers were pulled, so the client can say how old they are rather than
    # implying they are live. The free tier only moves every 10 minutes anyway.
    fetched_at: datetime.datetime
    players: list[PlayerLinesResponseData]


@router.get("/slate/{date}", operation_id="get_slate_lines", response_model=SlateResponseData)
async def get_slate_lines(date: datetime.date) -> SlateResponseData:
    """Every player priced for the games on one date.

    Served from a cache that refetches only once it is a quarter of an hour old, so five
    people opening the same slate costs one call rather than five — which is what keeps the
    monthly budget intact.

    An empty players list is a real answer, not a failure: a date with no games, one too
    far ahead to be priced, or a slate already played all look like this.
    """
    # Handed to a thread because the fetch underneath is `requests`, which blocks. This
    # process runs one uvicorn worker and therefore one event loop, so a blocking call here
    # would not merely make this request slow — it would stop every other request in the app
    # for as long as it took, which on a provider hang is the full 45-second timeout.
    #
    # No database session is taken either: nothing here touches it, and acquiring a
    # connection it would not use is precisely the per-request cost we went looking for when
    # production felt slow. Authentication still applies, from the router's own dependency.
    players, fetched_at, _ = await asyncio.to_thread(get_slate, date)

    return SlateResponseData(
        date=date,
        fetched_at=datetime.datetime.fromtimestamp(fetched_at, datetime.timezone.utc),
        players=[
            PlayerLinesResponseData(
                name=p.name,
                team=p.team,
                matchup=p.matchup,
                starts_at=p.starts_at,
                lines=[
                    LineResponseData(
                        prop_type=l.prop_type,
                        line=l.line,
                        over_odds=l.over_odds,
                        under_odds=l.under_odds,
                    ) for l in p.lines
                ],
            ) for p in players
        ],
    )
