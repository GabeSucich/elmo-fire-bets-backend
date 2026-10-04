"""Generating pick assessments and reporting which ones still apply.

One assessment per pick plus one for the parlay as a whole — a "slot" each. A slot is
regenerated only when no stored assessment matches its current input hash, and shown only
while its subject hash still matches the pick on screen. See models.Assessment for why the
two are separate.
"""
import asyncio
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from models import Assessment, Gambler, Parlay, Pick
from services.espn.game_context import fill_game_context

from . import payload as p
from .hashing import content_hash
from .llm import ASSESSMENT_MODEL, Suggestion, assess_parlay, assess_pick
from .prompts import PROMPT_VERSION

logger = logging.getLogger(__name__)

# A parlay can be assessed once it has this many picks — fewer is not much of a slate.
MIN_PICKS = 3


@dataclass
class Slot:
    pick: Pick | None
    subject: dict[str, Any]
    subject_hash: str
    input: dict[str, Any]
    input_hash: str

    @property
    def pick_id(self) -> int | None:
        return self.pick.id if self.pick else None


def _input_hash(model_input: dict[str, Any], *volatile_paths: tuple[str, ...]) -> str:
    return content_hash({
        "input": p.without_volatile(model_input, *volatile_paths),
        "model": ASSESSMENT_MODEL,
        "prompt_version": PROMPT_VERSION,
    })


def build_slots(parlay: Parlay, season_parlays: list[Parlay]) -> list[Slot]:
    """Every slot for a parlay with its hashes, in pick order with the parlay's own last."""
    slots = []
    for pick in sorted(parlay.picks, key=lambda x: x.id):
        subject = p.pick_subject(pick)
        model_input = p.pick_input(pick, parlay, season_parlays)
        slots.append(Slot(
            pick=pick, subject=subject, subject_hash=content_hash(subject),
            input=model_input, input_hash=_input_hash(model_input, ("pick",)),
        ))
    subject = p.parlay_subject(parlay)
    model_input = p.parlay_input(parlay, season_parlays)
    slots.append(Slot(
        pick=None, subject=subject, subject_hash=content_hash(subject),
        input=model_input, input_hash=_input_hash(model_input, ("slate", "picks")),
    ))
    return slots


async def load_season(parlay_id: int, db: AsyncSession) -> tuple[Parlay, list[Parlay]]:
    """The parlay and every parlay in its season, with all an assessment reads.

    Two round trips — the season id, then the season — rather than one per parlay: the
    app and the database sit in different regions, so trips are the whole cost.
    """
    season_id = (await db.execute(
        select(Parlay.gambling_season_id).where(Parlay.id == parlay_id)
    )).scalar_one()
    parlays = list((await db.execute(
        select(Parlay)
        .where(Parlay.gambling_season_id == season_id)
        .options(selectinload(Parlay.picks).joinedload(Pick.prop_bet_target))
        .options(selectinload(Parlay.picks).selectinload(Pick.vetoes))
        .options(selectinload(Parlay.picks).joinedload(Pick.gambler).joinedload(Gambler.user))
    )).scalars().unique())
    parlay = next(x for x in parlays if x.id == parlay_id)
    return parlay, parlays


class SlotStatus(StrEnum):
    # Assessed against exactly what would be sent now.
    FRESH = "fresh"
    # The pick is unchanged, but there are results since — another parlay settled. Still
    # about this pick, so still shown; requesting again would refresh it.
    OUTDATED = "outdated"
    # About a pick that has since been changed. Not shown as advice, only as what it was.
    STALE = "stale"
    MISSING = "missing"


@dataclass
class SlotReport:
    pick_id: int | None
    status: SlotStatus
    assessment: Assessment | None


def report_slots(slots: list[Slot], stored: list[Assessment]) -> list[SlotReport]:
    newest_first = sorted(stored, key=lambda a: (a.created_at, a.id), reverse=True)
    reports = []
    for slot in slots:
        mine = [a for a in newest_first if a.pick_id == slot.pick_id]
        exact = next((a for a in mine if a.input_hash == slot.input_hash), None)
        same_subject = next((a for a in mine if a.subject_hash == slot.subject_hash), None)
        if exact is not None:
            reports.append(SlotReport(slot.pick_id, SlotStatus.FRESH, exact))
        elif same_subject is not None:
            reports.append(SlotReport(slot.pick_id, SlotStatus.OUTDATED, same_subject))
        elif mine:
            reports.append(SlotReport(slot.pick_id, SlotStatus.STALE, mine[0]))
        else:
            reports.append(SlotReport(slot.pick_id, SlotStatus.MISSING, None))
    return reports


async def stored_assessments(parlay_id: int, db: AsyncSession) -> list[Assessment]:
    return list((await db.execute(
        select(Assessment).where(Assessment.parlay_id == parlay_id)
    )).scalars())


async def current_report(parlay_id: int, db: AsyncSession) -> tuple[Parlay, list[SlotReport]]:
    parlay, season = await load_season(parlay_id, db)
    return parlay, report_slots(build_slots(parlay, season), await stored_assessments(parlay_id, db))


async def generate(parlay_id: int, db: AsyncSession) -> tuple[Parlay, list[SlotReport]]:
    """Assess every slot whose input has no stored assessment yet. Returns the new report.

    Game context is filled in before anything is hashed, so a second request sees exactly
    the input the first one stored and asks the model nothing.
    """
    parlay, season = await load_season(parlay_id, db)
    # Writes onto the loaded picks themselves, so the slots below are built from the
    # filled values without loading anything again.
    await fill_game_context([parlay])
    await db.commit()

    slots = build_slots(parlay, season)
    have = {(a.pick_id, a.input_hash) for a in await stored_assessments(parlay_id, db)}
    needed = [s for s in slots if (s.pick_id, s.input_hash) not in have]
    # Nothing is held open across the model calls, which take seconds each.
    await db.commit()

    if needed:
        results = await asyncio.gather(
            *[assess_pick(s.input) if s.pick else assess_parlay(s.input) for s in needed],
            return_exceptions=True,
        )
        failures = []
        for slot, result in zip(needed, results):
            if isinstance(result, BaseException):
                failures.append(result)
                logger.error("assessment failed for parlay %s pick %s: %r", parlay_id, slot.pick_id, result)
                continue
            db.add(_row(parlay_id, slot, result))
        try:
            await db.commit()
        except IntegrityError:
            # A second press got there first with the same inputs. Its rows are just as good.
            await db.rollback()
        if failures:
            raise failures[0]

    return parlay, report_slots(slots, await stored_assessments(parlay_id, db))


def _row(parlay_id: int, slot: Slot, suggestions: list[Suggestion]) -> Assessment:
    return Assessment(
        parlay_id=parlay_id,
        pick_id=slot.pick_id,
        subject_hash=slot.subject_hash,
        input_hash=slot.input_hash,
        subject_snapshot=slot.subject,
        input_json=slot.input,
        suggestions=[s.model_dump() for s in suggestions],
        model=ASSESSMENT_MODEL,
        prompt_version=PROMPT_VERSION,
    )
