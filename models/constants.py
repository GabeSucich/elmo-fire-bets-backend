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
    RECEPTIONS = "Receptions"
    LONGEST_COMPLETION = "Longest Completion"
    PASS_COMPLETIONS = "Pass Completions"
    SACKS = "Sacks"

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