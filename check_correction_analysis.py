"""Checks for the image-driven pick correction pipeline.

    uv run python check_correction_analysis.py           # offline, no API calls
    uv run python check_correction_analysis.py --live    # also calls OpenAI

The offline checks cover the deterministic layer that decides what the reviewer
actually sees, and they are the ones worth running after any change to
services/correction_analysis.

The live check runs extraction against fixtures/synthetic_slip.png, which is built
to exercise the cases that have actually bitten: an alternate line ("2+", "42+"),
a team target rather than a player, bet-type vocabulary that differs from our enum,
and a header that repeats every leg's number as a summary.

Drop real screenshots into fixtures/ and add them to LIVE_FIXTURES to widen it.
"""

import asyncio
import base64
import pathlib
import sys

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env")

from models import Pick, PickVeto, PropBetDirection, PropBetTarget, PropBetType, VetoApprovalStatus
from services.correction_analysis import models as analysis_models
from services.correction_analysis import pipeline
from services.correction_analysis.picks import effective_direction

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

OVER, UNDER = PropBetDirection.OVER, PropBetDirection.UNDER

failures: list[str] = []


def check(name, actual, expected):
    ok = actual == expected
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        failures.append(name)
        print(f"      expected {expected!r}")
        print(f"      actual   {actual!r}")


def make_leg(index, player, prop, direction, number, team=None):
    return analysis_models.ExtractedLeg(
        leg_index=index, raw_text=f"{player or team} - {prop}", player_name=player,
        team_name=team, prop_type=prop, direction=direction, number=number,
    )


def make_pick(pick_id, player, prop, direction, line, veto=None):
    pick = Pick(prop_type=prop, direction=direction, line=line, corrected_line=None)
    pick.id = pick_id
    pick.prop_bet_target = PropBetTarget(identifier=str(pick_id), player_name=player, team_name="KC")
    pick.vetoes = [PickVeto(approval_status=veto)] if veto else []
    return pick


def stub_matcher(suggestions):
    async def _fake(legs, picks):
        return analysis_models.MatchingResult(suggestions=suggestions)
    pipeline.match_legs = _fake


def make_suggestion(pick_id, leg_index, number=None, mismatch=False, loose=False):
    return analysis_models.CorrectionSuggestion(
        pick_id=pick_id, matched_leg_index=leg_index, suggested_number=number,
        direction_mismatch=mismatch, loose_target_match=loose, note=None,
    )


def run_offline_checks():
    print("== offline ==")

    REC, RUSH = PropBetType.REC_YDS, PropBetType.RUSH_YDS

    raw = [
        make_leg(0, "Travis Kelce", REC, OVER, 49.5),
        make_leg(1, "Travis Kelce", REC, OVER, 49.5),
        make_leg(2, "Isiah Pacheco", RUSH, OVER, 40.5),
    ]
    check("overlapping screenshots collapse to one leg",
          [leg.leg_index for leg in pipeline._dedupe_legs(raw)], [0, 2])

    legs = pipeline._dedupe_legs(raw)

    picks = [make_pick(10, "Travis Kelce", REC, OVER, 45.5),
             make_pick(11, "Travis Kelce", REC, OVER, 47.5)]
    stub_matcher([make_suggestion(10, 0, 49.5), make_suggestion(11, 0, 49.5)])
    out = asyncio.run(pipeline.match_legs_to_picks(legs, picks))
    check("one leg claimed twice clears both",
          [(s.pick_id, s.matched_leg_index) for s in out], [(10, None), (11, None)])
    check("...and says why", out[0].note, pipeline.MULTI_MATCH_NOTE)

    picks = [make_pick(10, "Travis Kelce", REC, OVER, 45.5)]
    stub_matcher([make_suggestion(10, 0, 999.5)])
    out = asyncio.run(pipeline.match_legs_to_picks(legs, picks))
    check("number comes from extraction, never from the matcher", out[0].suggested_number, 49.5)

    picks = [make_pick(10, "Travis Kelce", REC, OVER, 45.5),
             make_pick(11, "Isiah Pacheco", RUSH, OVER, 38.5)]
    stub_matcher([make_suggestion(10, 0, 49.5)])
    out = asyncio.run(pipeline.match_legs_to_picks(legs, picks))
    check("a pick the matcher skipped still gets a row",
          [(s.pick_id, s.matched_leg_index) for s in out], [(10, 0), (11, None)])

    stub_matcher([make_suggestion(10, 47, 12.5), make_suggestion(11, None)])
    out = asyncio.run(pipeline.match_legs_to_picks(legs, picks))
    check("a leg_index that does not exist is dropped",
          (out[0].matched_leg_index, out[0].suggested_number), (None, None))

    picks = [make_pick(10, "Travis Kelce", REC, UNDER, 45.5)]
    stub_matcher([make_suggestion(10, 0, 49.5, mismatch=False)])
    out = asyncio.run(pipeline.match_legs_to_picks(legs, picks))
    check("direction mismatch is recomputed, not trusted", out[0].direction_mismatch, True)

    check("an approved veto flips the effective direction",
          effective_direction(make_pick(1, "X", REC, OVER, 1, VetoApprovalStatus.APPROVED)), UNDER)
    check("a pending veto does not",
          effective_direction(make_pick(1, "X", REC, OVER, 1, VetoApprovalStatus.PENDING)), OVER)

    picks = [make_pick(10, "Travis Kelce", REC, UNDER, 45.5, VetoApprovalStatus.APPROVED)]
    stub_matcher([make_suggestion(10, 0, 49.5)])
    out = asyncio.run(pipeline.match_legs_to_picks(legs, picks))
    check("a vetoed pick does not raise a false mismatch", out[0].direction_mismatch, False)

    stub_matcher([])
    out = asyncio.run(pipeline.match_legs_to_picks([], picks))
    check("no legs read still returns one row per pick", [s.pick_id for s in out], [10])

    # A pick recorded on a team, matched to a leg naming a player. Legitimate for a kicker's
    # field goals, wrong for anything a team accumulates across several players.
    kicker_leg = make_leg(0, "Harrison Mevis", PropBetType.FGS, OVER, 1.5, team="LAR")
    back_leg = make_leg(1, "Isiah Pacheco", RUSH, OVER, 40.5, team="KC")

    team_fgs = make_pick(20, None, PropBetType.FGS, OVER, 1.5)
    stub_matcher([make_suggestion(20, 0, 1.5, loose=True)])
    out = asyncio.run(pipeline.match_legs_to_picks([kicker_leg], [team_fgs]))
    check("team field goals accepts the kicker's line",
          (out[0].matched_leg_index, out[0].suggested_number, out[0].loose_target_match),
          (0, 1.5, True))

    team_rush = make_pick(21, None, RUSH, OVER, 95.5)
    stub_matcher([make_suggestion(21, 1, 40.5, loose=True)])
    out = asyncio.run(pipeline.match_legs_to_picks([back_leg], [team_rush]))
    check("team rushing yards refuses a single back's line",
          (out[0].matched_leg_index, out[0].note), (None, pipeline.CROSS_TARGET_NOTE))

    player_fgs = make_pick(22, "Harrison Mevis", PropBetType.FGS, OVER, 1.5)
    stub_matcher([make_suggestion(22, 0, 1.5)])
    out = asyncio.run(pipeline.match_legs_to_picks([kicker_leg], [player_fgs]))
    check("a plain player-to-player match is not flagged loose",
          (out[0].matched_leg_index, out[0].loose_target_match), (0, False))

    # Slips show the team as a logo, so a kicker's leg arrives with no team attached and
    # the model cannot line it up against a team-recorded pick. Resolved without a roster.
    lone_kicker = make_leg(0, "Harrison Mevis", PropBetType.FGS, OVER, 1.5)
    team_fgs = make_pick(30, None, PropBetType.FGS, OVER, 2.5)
    stub_matcher([make_suggestion(30, None)])
    out = asyncio.run(pipeline.match_legs_to_picks([lone_kicker], [team_fgs]))
    check("a team field-goal pick takes the only kicker on the slip",
          (out[0].matched_leg_index, out[0].suggested_number, out[0].loose_target_match),
          (0, 1.5, True))

    two_kickers = [lone_kicker, make_leg(1, "Cairo Santos", PropBetType.FGS, OVER, 0.5)]
    stub_matcher([make_suggestion(30, None)])
    out = asyncio.run(pipeline.match_legs_to_picks(two_kickers, [team_fgs]))
    check("two kickers on the slip is a real choice, so neither is taken",
          out[0].matched_leg_index, None)

    lone_back = make_leg(0, "Kyren Williams", RUSH, OVER, 60.5)
    team_rush_pick = make_pick(31, None, RUSH, OVER, 95.5)
    stub_matcher([make_suggestion(31, None)])
    out = asyncio.run(pipeline.match_legs_to_picks([lone_back], [team_rush_pick]))
    check("a team rushing pick does not take a lone running back",
          out[0].matched_leg_index, None)


# (fixture, expected legs as (target, prop_type, direction, number), stated leg count)
LIVE_FIXTURES = [
    (
        "synthetic_slip.png",
        [
            ("Travis Kelce", PropBetType.TDS, OVER, 0.5),
            ("LAC", PropBetType.FGS, OVER, 1.5),
            ("Isiah Pacheco", PropBetType.REC_YDS, OVER, 11.5),
            ("Rashee Rice", PropBetType.RUSH_YDS, OVER, 41.5),
            ("Patrick Mahomes", PropBetType.PASSING_YDS, OVER, 216.5),
        ],
        5,
    ),
    # A real FanDuel slip. Every team appears only as a helmet icon, which is what forces
    # the team to be read off the logo — and what broke the LAR field-goal pick when it
    # was not. Also carries two different players on the same market.
    (
        "real_slip_lar_chi.png",
        [
            ("Caleb Williams", PropBetType.PASSING_INTS, OVER, 0.5),
            ("Harrison Mevis", PropBetType.FGS, OVER, 1.5),
            ("Kyren Williams", PropBetType.REC_YDS, OVER, 11.5),
            ("Luther Burden III", PropBetType.REC_YDS, OVER, 41.5),
            ("Caleb Williams", PropBetType.PASSING_YDS, OVER, 216.5),
        ],
        5,
    ),
]


async def run_live_checks():
    print("\n== live ==")
    for filename, expected, stated in LIVE_FIXTURES:
        path = FIXTURES / filename
        if not path.exists():
            print(f"SKIP  {filename} (not found)")
            continue

        image = base64.b64encode(path.read_bytes()).decode()
        result = await pipeline.extract_legs_from_images([image])

        print(f"\n  {filename}")
        for leg in result.legs:
            print(f"    {leg.leg_index}  {leg.player_name or leg.team_name} / {leg.prop_type} / "
                  f"{leg.direction} {leg.number}")
            print(f"        raw: {leg.raw_text}")
        print()

        check(f"{filename}: leg count", len(result.legs), len(expected))
        check(f"{filename}: stated leg count", result.stated_leg_count, stated)

        for index, (target, prop_type, direction, number) in enumerate(expected):
            if index >= len(result.legs):
                check(f"{filename}: leg {index} ({target})", None, target)
                continue
            leg = result.legs[index]
            got = (leg.player_name or leg.team_name or "").strip()
            check(
                f"{filename}: leg {index} ({target})",
                (got.lower(), leg.prop_type, leg.direction, leg.number),
                (target.lower(), prop_type, direction, number),
            )


if __name__ == "__main__":
    run_offline_checks()
    if "--live" in sys.argv:
        asyncio.run(run_live_checks())

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        sys.exit(1)
    print("all checks passed")
