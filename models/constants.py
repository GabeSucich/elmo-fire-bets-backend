from enum import StrEnum

class PropBetType(StrEnum):
    TARGETS = "Targets"
    FGS = "FGs"
    LONGEST_RUSH = "Longest Rush"
    PASS_ATTEMPTS = "Pass Attempts"
    RUSH_YDS = "Rush Yards"
    REC_YDS = "Rec Yards"
    RUSH_ATTEMPTS = "Rush Attempts"
    TACKLES_ASSISTS = "Tackles + Assists"
    RUSH_REC_YDS = "Rush + Rec yds"
    LONGEST_RECEPTION = "Longest Reception"
    LONGEST_TD = "Longest TD"
    PASSING_TDS = "Passing TDs"
    PASSING_INTS = "Passing Ints"
    PASSING_YDS = "Passing Yds"
    TDS = "TDs"
    RUSHING_TDS = "Rush TDs"
    RECEIVING_TDS = "Rec TDs"
    RECEPTIONS = "Receptions"
    LONGEST_COMPLETION = "Longest Completion"
    PASS_COMPLETIONS = "Pass Completions"
    SACKS = "Sacks"

class SeasonPickKind(StrEnum):
    """Season-long picks come in two shapes. Team win totals deliberately have no
    PropBetType member, which is what keeps them out of the parlay pick picker."""
    PLAYER_PROP = "Player prop"
    TEAM_WINS = "Team wins"

class SauceFactor(StrEnum):
    BITCH = "Bitch"
    SPICY = "Spicy"

class PickResult(StrEnum):
    WIN = "Win"
    LOSS = "Loss"
    VOID = "Void"
    BOZO = "BOZO"
    PUSH = "Push"
    
class PropBetDirection(StrEnum):
    OVER = "Over"
    UNDER = "Under"

class VetoApprovalStatus(StrEnum):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    UNDECIDED = "Undecided"

class VetoResult(StrEnum):
    GOOD = "Good"
    BAD = "Bad"
    VOID = "Void"
    PUSH = "Push"
    BOZO_SAVER = "BOZO Saver"
    BOZO = "BOZO"

class ParlayState(StrEnum):
    BUILDING = "Building"
    OPEN = "Open"
    CLOSED = "Closed"

class ParlayResult(StrEnum):
    WIN = "Win"
    LOSS = "Loss"
    VOID = "Void"
    BOZO = "BOZO"
    PUSH = "Push"

class SlateType(StrEnum):
    TNF = "TNF"
    FNF = "FNF"
    WNF = "WNF"
    MORNING_SLATE = "Morning slate"
    AFTERNOON_SLATE = "Afternoon slate"
    TD = "TD"
    SNF = "SNF"
    MNF = "MNF"
    INTERNATIONAL_GAME = "International Game"
    SATURDAY = "Saturday"
    XMAS = "Xmas"
    WILDCARD = "Wildcard"
    DIVISIONAL = "Divisional"
    CONFERENCE = "Conference"

# The emoji that can be dropped on a pick.
#
# A tuple rather than a StrEnum, and stored in a String column rather than a SQLEnum:
# growing this set should be a code change, not an ALTER TYPE against production, and an
# emoji-valued enum generates unusable member names in the TypeScript client (the same
# problem the feedback vote enum has, where the members come out as `_1` and `_-1`).
#
# Shipped to the client on the season response so the picker and the validation below can
# never disagree about what the palette is.
PICK_REACTION_EMOJI = (
    "\U0001F525",  # fire
    "\u2764\uFE0F",  # heart
    "\U0001F3AF",  # bullseye
    "\U0001FAE1",  # saluting
    "\U0001F64F",  # praying
    "\U0001F602",  # crying laughing
    "\U0001F440",  # eyes
    "\U0001F336\uFE0F",  # hot pepper
    "\U0001F9CA",  # ice
    "\U0001F921",  # clown
    "\U0001F4A9",  # pile of poo
    "\U0001F92E",  # vomiting
    "\U0001F480",  # skull
    "\U0001F410",  # goat
    "\U0001F4B0",  # money bag
    "\U0001F62C",  # grimacing
    "\U0001F3A3",  # fishing pole
    # Last, deliberately: a verdict rather than a reaction, and the two people reach for
    # without thinking. Kept off the front so they do not crowd out everything else.
    "\U0001F44D",  # thumbs up
    "\U0001F44E",  # thumbs down
)
