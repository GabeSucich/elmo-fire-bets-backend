"""Seed a season's Suggestions tab with feedback, votes and replies.

Local only, and never destructive unless asked: every suggestion is matched on its text, so
re-running adds nothing. `--reset` clears the season's feedback first.

Timestamps are written by hand and spread across a fortnight, because the screen splits
the list on age — anything from the last three days leads under a NEW flag, and the rest
is ranked on score. Seeding it all at `now()` would collapse that into one section.
"""

import argparse
import asyncio
import datetime
import sys

from dotenv import load_dotenv
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

load_dotenv(".env")

from database import async_session
from models import Feedback, FeedbackComment, FeedbackRating, FeedbackStatus, Gambler, GamblingSeason
from services.feedback_titles import generate_title

DEFAULT_YEAR = 2026

# (author, days ago, comment, votes, replies, status)
#
# Votes are (voter, +1/-1) and never include the author, who cannot vote for their own.
# Days are floats so two suggestions rarely share a timestamp, and the first four sit inside the
# three-day window the client flags as new.
IDEAS: list[dict] = [
    dict(
        author="Nate", days=0.2, status=FeedbackStatus.OPEN,
        comment="we should get a push notification when someone vetoes one of my picks",
        votes=[("Mark", 1), ("Keith", 1), ("Gabe", 1)],
        replies=[("Keith", 0.1, "yes, I found out three days late last week")],
    ),
    dict(
        author="Mark", days=0.9, status=FeedbackStatus.OPEN,
        comment="Can the leaderboard show how many bozos each person has taken this year",
        votes=[("Nate", 1), ("Jason", 1)],
        replies=[],
    ),
    dict(
        author="Keith", days=1.6, status=FeedbackStatus.OPEN,
        comment="dark mode is too dark on the analytics charts, hard to read the lines against the background",
        votes=[("Gabe", 1)],
        replies=[("Gabe", 0.4, "agreed, the time series is the worst one")],
    ),
    dict(
        author="Jason", days=2.6, status=FeedbackStatus.OPEN,
        comment="Let me sort parlays by week instead of just newest first",
        votes=[("Mark", -1)],
        replies=[("Mark", 1.0, "newest first is what I want 95% of the time though")],
    ),
    dict(
        author="Gabe", days=3.5, status=FeedbackStatus.OPEN,
        comment="It would be great if the slip reader could handle DraftKings screenshots too, not just FanDuel",
        votes=[("Nate", 1), ("Mark", 1), ("Keith", 1), ("Jason", 1)],
        replies=[
            ("Nate", 2.0, "this is the big one for me, I'm on DK for everything"),
            ("Jason", 1.2, "same, I've been typing them in by hand all season"),
        ],
    ),
    dict(
        author="Mark", days=4.2, status=FeedbackStatus.OPEN,
        comment="I want to see how someone did on all their Josh Allen picks over the whole season",
        votes=[("Keith", 1), ("Gabe", 1)],
        replies=[],
    ),
    dict(
        author="Nate", days=5.1, status=FeedbackStatus.OPEN,
        comment="Add a weekly recap feature to track individual betting performance",
        votes=[("Mark", 1), ("Jason", 1), ("Gabe", 1), ("Keith", -1)],
        replies=[("Keith", 3.0, "we already have the analytics tab for this?")],
    ),
    dict(
        author="Keith", days=6.0, status=FeedbackStatus.OPEN,
        comment="There should be a running tally of who owes what at the end of the season",
        votes=[("Nate", 1), ("Jason", 1), ("Mark", 1)],
        replies=[("Gabe", 2.5, "I've been keeping this in a note on my phone, would love it in here")],
    ),
    dict(
        author="Jason", days=6.8, status=FeedbackStatus.OPEN,
        comment="Can we get a reminder on Sunday morning if I haven't locked my picks yet",
        votes=[("Nate", 1), ("Keith", 1)],
        replies=[],
    ),
    dict(
        author="Gabe", days=7.5, status=FeedbackStatus.OPEN,
        comment="Show the closing line next to each pick so we can see whether someone actually got value",
        votes=[("Mark", 1)],
        replies=[],
    ),
    dict(
        author="Mark", days=8.3, status=FeedbackStatus.OPEN,
        comment="the veto flow needs a way to say why you're vetoing, right now it's a total mystery",
        votes=[("Keith", 1), ("Jason", -1)],
        replies=[("Jason", 4.0, "the mystery is the fun part")],
    ),
    dict(
        author="Nate", days=9.1, status=FeedbackStatus.OPEN,
        comment="I'd like to export the season results to a spreadsheet when it's over",
        votes=[("Jason", -1), ("Keith", -1)],
        replies=[],
    ),
    dict(
        author="Mark", days=11.0, status=FeedbackStatus.RETIRED,
        comment="can we bet on college games too, there's way more of them on Saturdays",
        votes=[("Nate", 1), ("Keith", -1), ("Jason", -1)],
        replies=[("Gabe", 10.2, "not doing this one — the whole league is built around the NFL slate")],
    ),
    dict(
        author="Jason", days=13.5, status=FeedbackStatus.RETIRED,
        comment="let people change a pick up until kickoff instead of locking on Thursday",
        votes=[("Keith", 1), ("Mark", -1), ("Nate", -1), ("Gabe", -1)],
        replies=[("Nate", 12.8, "the lock is the whole game, otherwise everyone just waits")],
    ),
    dict(
        author="Keith", days=10.4, status=FeedbackStatus.RESOLVED,
        comment="the lock button is too easy to hit by accident on the parlay card",
        votes=[("Nate", 1), ("Mark", 1), ("Gabe", 1), ("Jason", 1)],
        replies=[("Gabe", 9.0, "fixed — it's behind a confirm now")],
    ),
    dict(
        author="Jason", days=12.2, status=FeedbackStatus.RESOLVED,
        comment="team logos next to each pick would make the cards way easier to scan",
        votes=[("Mark", 1), ("Nate", 1)],
        replies=[],
    ),
]


async def load_gamblers(db: AsyncSession, year: int) -> tuple[int, dict[str, Gambler]]:
    season = (await db.execute(
        select(GamblingSeason).where(GamblingSeason.year == year)
        .options(selectinload(GamblingSeason.gamblers).selectinload(Gambler.user))
    )).scalar_one_or_none()
    if season is None:
        sys.exit(f"No gambling season for {year}. Run seed_season.py first.")

    by_name = {g.user.first_name: g for g in season.gamblers}
    missing = {
        name
        for suggestion in IDEAS
        for name in [suggestion["author"], *(v for v, _ in suggestion["votes"]), *(a for a, _, _ in suggestion["replies"])]
        if name not in by_name
    }
    if missing:
        sys.exit(f"Season {year} has no gambler named: {', '.join(sorted(missing))}")

    return season.id, by_name


async def clear_season_feedback(db: AsyncSession, season_id: int) -> int:
    """Remove every piece of feedback in the season, votes and replies included."""
    ids = list((await db.execute(
        select(Feedback.id).join(Gambler, Gambler.id == Feedback.gambler_id)
        .where(Gambler.gambling_season_id == season_id)
    )).scalars())
    if ids:
        await db.execute(delete(FeedbackRating).where(FeedbackRating.feedback_id.in_(ids)))
        await db.execute(delete(FeedbackComment).where(FeedbackComment.feedback_id.in_(ids)))
        await db.execute(delete(Feedback).where(Feedback.id.in_(ids)))
        await db.commit()
    return len(ids)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--reset", action="store_true", help="delete the season's existing feedback first")
    args = parser.parse_args()

    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)

    async with async_session() as db:
        season_id, gamblers = await load_gamblers(db, args.year)

        if args.reset:
            print(f"Cleared {await clear_season_feedback(db, season_id)} existing suggestions")

        existing = set((await db.execute(
            select(Feedback.comment).join(Gambler, Gambler.id == Feedback.gambler_id)
            .where(Gambler.gambling_season_id == season_id)
        )).scalars())

        pending = [suggestion for suggestion in IDEAS if suggestion["comment"] not in existing]
        if not pending:
            print("Nothing to add — every suggestion is already there.")
            return

        # Through the real titling path, so the seeded list reads exactly like a live one.
        # Concurrently, because otherwise this is fourteen round trips in a row.
        print(f"Titling {len(pending)} suggestions...")
        titles = await asyncio.gather(*(generate_title(i["comment"]) for i in pending))

        for suggestion, title in zip(pending, titles):
            created = now - datetime.timedelta(days=suggestion["days"])
            feedback = Feedback(
                gambler_id=gamblers[suggestion["author"]].id,
                title=title,
                comment=suggestion["comment"],
                status=suggestion["status"],
                created_at=created,
                updated_at=created,
            )
            db.add(feedback)
            await db.flush()

            for voter, value in suggestion["votes"]:
                db.add(FeedbackRating(
                    feedback_id=feedback.id, gambler_id=gamblers[voter].id, value=value,
                    created_at=created, updated_at=created,
                ))
            for author, days, text in suggestion["replies"]:
                # Replies are dated from now, like the suggestion, so one never lands before the
                # thing it is replying to.
                replied = now - datetime.timedelta(days=days)
                db.add(FeedbackComment(
                    feedback_id=feedback.id, gambler_id=gamblers[author].id, comment=text,
                    created_at=replied, updated_at=replied,
                ))

            score = sum(v for _, v in suggestion["votes"])
            flag = "NEW " if suggestion["days"] < 3 else suggestion["status"].value[:4].lower().ljust(4)
            print(f"  {flag} {score:+3}  {suggestion['days']:>4.1f}d  {suggestion['author']:<6} {title}")

        await db.commit()
        print(f"\nSeeded {len(pending)} suggestions into {args.year}.")


if __name__ == "__main__":
    asyncio.run(main())
