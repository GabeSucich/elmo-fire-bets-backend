EXTRACTION_PROMPT = """\
You are reading screenshots of a sports betting parlay slip. Extract every individual \
bet leg that appears in the slip.

TARGET
- If the leg is on a named player, set player_name to the player's full name as printed, \
and team_name to their team abbreviation if one is shown, otherwise null.
- If the leg is on a team rather than a player (for example "LAC Total Field Goals"), set \
player_name to null and team_name to the team alone.
- player_name and team_name must contain only the name of the player or team. Strip any market \
words that share the line with it: "LAC Total Field Goals" has team_name "LAC", not \
"LAC Total Field Goals". The verbatim version of the line belongs in raw_text, not here.
- Sportsbooks very often show a leg's team only as a logo or helmet icon beside it, with no team \
text at all. Read the team off that icon and set team_name to its standard abbreviation \
(for example the Rams are "LAR", the Bears "CHI"). Always fill team_name in when the icon or the \
matchup makes the team clear — it is what lets a player leg be lined up against a pick recorded \
on the team. Only leave it null if you genuinely cannot tell.

BET TYPE
- Map each leg's bet type to exactly one of the allowed prop_type values.
- Common mappings: "Receiving Yards" -> "Rec Yards"; "Rushing Yards" -> "Rush Yards"; \
"Rush + Rec Yards" -> "Rush + Rec yds"; "Passing Yards" -> "Passing Yds"; \
"Interceptions Thrown" -> "Passing Ints"; "Field Goals Made" and "Total Field Goals" -> "FGs"; \
"Anytime Touchdown Scorer" and "Total Touchdowns" -> "TDs"; "Pass Completions" -> "Pass Completions".
- If no allowed value clearly corresponds to the printed bet type, set prop_type to null. \
Do not guess. A null prop_type is a correct answer when nothing fits.

NUMBER AND DIRECTION
- A standard line is printed as "Over 49.5" or "Under 6.5". Use that direction and that number.
- An alternate line is printed as a threshold with a plus or minus and means "at least" or \
"at most". Convert it to the equivalent half-point line:
    "2+"                 -> direction "Over",  number 1.5
    "42+"                -> direction "Over",  number 41.5
    "3-" or "3 or fewer" -> direction "Under", number 3.5
- number must always be the half-point line, never the raw threshold.

RAW TEXT
- raw_text must reproduce every line of text the slip prints for that leg — the player or team, \
the market name, and the line — joined with " - ", each exactly as printed. For example a leg \
printed as "Travis Kelce" / "Anytime Touchdown Scorer" / "Over 0.5" becomes \
"Travis Kelce - Anytime Touchdown Scorer - Over 0.5".
- Never normalize, correct, abbreviate, or omit any of it. In particular keep the market name \
and keep the line in its printed form, including alternate lines such as "2+". A reviewer uses \
this text to catch a wrong bet type or a wrong conversion, so it has to be verbatim.

WHAT TO IGNORE
- Some slips repeat a compact summary of every leg near the top or in a header, for example a \
single line reading "Over 0.5, 2+, Over 11.5, 42+, Over 216.5". That is a summary of legs \
listed in full elsewhere, not a set of additional legs. Ignore it.
- Ignore odds, payouts, wager amounts, boosts, and promotional text.

MULTIPLE IMAGES
- The images may be overlapping scrolls of the same slip. If the same leg appears in more than \
one image, return it only once.
- leg_index must be a unique sequential integer starting at 0 across all returned legs.

LEG COUNT
- If the slip states how many legs it contains (for example "5 Leg Parlay"), set \
stated_leg_count to that number. Otherwise set it to null.
"""


MATCHING_PROMPT = """\
Picks in this league are recorded before the bet is actually placed, so the number on a recorded \
pick very often differs from the number that ended up on the slip. Fixing exactly that is the \
point of this task.

Your only job is to work out which line on the slip corresponds to which recorded pick. You are \
resolving identity — who the bet is on, and what kind of bet it is. Nothing else.

You will receive PICKS (each with a pick_id) and LEGS (each with a leg_index).
Return exactly one suggestion object for every pick in PICKS, in the same order.

MATCHING RULE
A pick matches a leg when BOTH of these hold:
1. Same target. For player picks that means the same person — ignore capitalization, \
punctuation, suffixes such as "Jr.", and shortened or nickname forms of the first name. For \
team picks it means the same team.
2. Identical bet type (prop_type).

That is the entire rule. Nothing else can create a match, and nothing else can block one.

TEAM AND PLAYER FORMS OF THE SAME BET
A pick may be recorded against a team while the slip names an individual player, or the other \
way round. Treat those as the same target when the team's total for that market is, in practice, \
produced by that one player. Field goals are the standard case: "LA Rams - Total Field Goals" \
and "Harrison Mevis - Field Goals Made" are the same bet, because Mevis is the Rams' placekicker.

Do NOT do this for markets that a team accumulates across many players — rushing yards, \
receiving yards, passing yards, receptions, targets, tackles and the like. A team total and one \
player's total are different bets there, so they never match.

When you do match a team form to a player form, set loose_target_match to true so a human \
confirms it. Set it to false for every ordinary match.

The picks are given to you without their numbers, deliberately. A leg's raw_text will show the \
line that was actually placed; it is not evidence for or against a match, and you must never \
withhold a match because a number looks unexpected. Same person, same bet type means match it.

The one thing to be strict about is identity: two different people are never a match, however \
similar the rest of the leg looks.

ASSIGNMENT
Each leg may be used by at most one pick, and each pick may match at most one leg. Some picks \
may have no match and some legs may go unused — that is expected.

OUTPUT PER PICK
- matched_leg_index: the leg_index of the matched leg, or null when no leg has both the same \
target and the same bet type.
- suggested_number: always null. The number is filled in afterwards, straight from the slip.
- direction_mismatch: always false. It is worked out afterwards.
- loose_target_match: true only when a team form was matched to a player form, as described \
above. False otherwise.
- note: when there is no match, one short sentence naming what was missing — the player, the \
bet type, or both. When loose_target_match is true, name the player and the team instead. \
Otherwise null.
"""
