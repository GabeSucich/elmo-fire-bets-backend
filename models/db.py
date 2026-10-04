import datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Enum as SQLEnum, Index, Integer, String, Text, UniqueConstraint, null, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .constants import *

class User(Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(unique=True)
    password: Mapped[str]
    first_name: Mapped[str]
    last_name: Mapped[str]

    gamblers: Mapped[list["Gambler"]] = relationship(back_populates="user")

class Gambler(Base):
    __tablename__ = "gamblers"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    user: Mapped["User"] = relationship(back_populates="gamblers")
    gambling_season_id: Mapped[int] = mapped_column(ForeignKey("gambling_seasons.id"))
    gambling_season: Mapped["GamblingSeason"] = relationship(back_populates="gamblers")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    vetoes: Mapped[list["PickVeto"]] = relationship(back_populates="gambler")
    owned_parlays: Mapped[list["Parlay"]] = relationship(back_populates="owner")
    picks: Mapped[list["Pick"]] = relationship(back_populates="gambler")
    season_picks: Mapped[list["SeasonPick"]] = relationship(back_populates="gambler", cascade="all, delete-orphan")

class GamblingSeasonState(StrEnum):
    IN_PROGRESS = "In Progress"
    COMPLETE = "Complete"

class GamblingSeason(Base):
    __tablename__ = "gambling_seasons"
    
    year: Mapped[int]
    name: Mapped[str]
    state: Mapped[GamblingSeasonState] = mapped_column(SQLEnum(GamblingSeasonState))

    gamblers: Mapped[list["Gambler"]] = relationship(back_populates="gambling_season")
    parlays: Mapped[list["Parlay"]] = relationship(back_populates="gambling_season")


class PropBetTarget(Base):
    __tablename__ = "prop_bet_targets"

    # ESPN's uuid, from the search that created this row. Opaque: it cannot be searched on
    # and the stats endpoints reject it, so it identifies the target for us but is no use
    # for fetching anything.
    identifier: Mapped[str] = mapped_column(String, unique=True, index=True)
    # ESPN's numeric athlete id, which is what every stats endpoint actually wants. It
    # arrives in the same search response the identifier does. Nullable because rows
    # created before this existed have to be filled in by name, which the sync does the
    # first time it needs one.
    espn_athlete_id: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    player_name: Mapped[str] = mapped_column(String, nullable=True, default=None)
    team_name: Mapped[str]
    picks: Mapped[list["Pick"]] = relationship(back_populates="prop_bet_target")

class Pick(Base):
    __tablename__ = "picks"

    gambler_id: Mapped[int] = mapped_column(ForeignKey("gamblers.id"))
    prop_bet_target_id: Mapped[int] = mapped_column(ForeignKey("prop_bet_targets.id"))
    prop_type: Mapped[PropBetType] = mapped_column(SQLEnum(PropBetType))
    parlay_id: Mapped[int] = mapped_column(ForeignKey("parlays.id"))
    line: Mapped[float] = mapped_column(Float)
    corrected_line: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    direction: Mapped[PropBetDirection] = mapped_column(SQLEnum(PropBetDirection))
    sauce_factor: Mapped[SauceFactor | None] = mapped_column(SQLEnum(SauceFactor), nullable=True, default=None)
    result: Mapped[PickResult | None] = mapped_column(SQLEnum(PickResult), nullable=True, default=None)
    # What the stat actually is, pulled from the live boxscore by an explicit sync. Never
    # written by anything that settles a bet: `result` stays hand-entered, because a void,
    # a push and a bozo are all judgements no feed can make.
    live_value: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    # ESPN's own reading of the game: "pre", "in" or "post". Distinct from having no
    # value — a game that has not kicked off and a player who recorded nothing look the
    # same in the numbers and should not look the same on the card.
    live_state: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    # The human half of the same thing: "Final", "Q3 4:12", "9/13 - 1:00 PM EDT".
    live_detail: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    live_synced_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True, default=None)

    # The game this pick's player is playing in, from the ESPN scoreboard. Context for pick
    # assessments, filled by services/espn/game_context. Every one is written once and then
    # left alone — the schedule does not change, and an assessment hashes these, so a value
    # that kept moving would keep invalidating it.
    game_event_id: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    # The side the player was on in that game. Not the same as the target's team_name,
    # which the player sync moves to wherever he plays now.
    game_team: Mapped[str | None] = mapped_column(String(8), nullable=True, default=None)
    game_kickoff_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    game_week: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    game_is_home: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    game_opponent: Mapped[str | None] = mapped_column(String(8), nullable=True, default=None)
    game_indoor: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    # A neutral site still lists one side as home. Anything reading game_is_home checks this.
    game_neutral_site: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    # Written once the game is final.
    game_team_score: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    game_opponent_score: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # The market around the game. ESPN publishes these only before kickoff, so they are
    # refreshed until then and frozen after — the last value written is close to the
    # closing line. Null on anything nobody touched before it was played: these cannot be
    # backfilled. From this pick's team's side: negative means favoured.
    game_team_spread: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    game_total: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    game_weather: Mapped[str | None] = mapped_column(String, nullable=True, default=None)

    gambler: Mapped["Gambler"] = relationship(back_populates="picks")
    vetoes: Mapped[list["PickVeto"]] = relationship(back_populates="pick", cascade="all, delete-orphan")
    parlay: Mapped["Parlay"] = relationship(back_populates="picks")
    prop_bet_target: Mapped["PropBetTarget"] = relationship(back_populates="picks")
    # Cascaded rather than left to the database: deleting a parlay cascades to its picks,
    # and async SQLAlchemy cannot lazy-load a collection mid-cascade — which is why both
    # of these have to stay in the parlay query's eager loads.
    reactions: Mapped[list["PickReaction"]] = relationship(
        back_populates="pick", cascade="all, delete-orphan"
    )
    comments: Mapped[list["PickComment"]] = relationship(
        back_populates="pick", cascade="all, delete-orphan"
    )
    # Left to the database rather than cascaded here, so it does not have to join the
    # eager loads above: passive_deletes means the ORM never loads these to delete them.
    assessments: Mapped[list["Assessment"]] = relationship(
        back_populates="pick", passive_deletes=True
    )

class PickVeto(Base):
    __tablename__ = "pick_vetoes"

    pick_id: Mapped[int] = mapped_column(ForeignKey("picks.id"))
    gambler_id: Mapped[int] = mapped_column(ForeignKey("gamblers.id"))
    approval_status: Mapped[VetoApprovalStatus] = mapped_column(SQLEnum(VetoApprovalStatus), default=VetoApprovalStatus.PENDING)
    result: Mapped[VetoResult | None] = mapped_column(SQLEnum(VetoResult), nullable=True, default=None)

    gambler: Mapped[Gambler] = relationship(back_populates="vetoes")
    pick: Mapped["Pick"] = relationship(back_populates="vetoes")
    votes: Mapped[list["VetoVote"]] = relationship(back_populates="veto", cascade="all, delete-orphan")

class VetoVote(Base):
    __tablename__ = "veto_votes"

    veto_id: Mapped[int] = mapped_column(ForeignKey("pick_vetoes.id"))
    gambler_id: Mapped[int] = mapped_column(ForeignKey("gamblers.id"))
    affirmative: Mapped[bool]

    veto: Mapped[PickVeto] = relationship(back_populates="votes")

    

class PickReaction(Base):
    """One gambler's emoji on one pick.

    Unique on the emoji as well as the gambler, which is what separates this from the
    single up-or-down FeedbackRating it is modelled on: several different reactions may sit
    on the same pick from the same person, and tapping one you already left takes it back.
    """
    __tablename__ = "pick_reactions"
    __table_args__ = (
        UniqueConstraint("pick_id", "gambler_id", "emoji", name="uq_pick_reaction_gambler_emoji"),
    )

    pick_id: Mapped[int] = mapped_column(ForeignKey("picks.id"))
    gambler_id: Mapped[int] = mapped_column(ForeignKey("gamblers.id"))
    # A plain string, deliberately not an enum. See PICK_REACTION_EMOJI: the palette is
    # validated on write but stored loosely, so retiring an emoji never orphans old rows.
    emoji: Mapped[str] = mapped_column(String(16))

    pick: Mapped["Pick"] = relationship(back_populates="reactions")


class PickComment(Base):
    """A reply on one pick. The same shape as FeedbackComment, on a different parent."""
    __tablename__ = "pick_comments"

    pick_id: Mapped[int] = mapped_column(ForeignKey("picks.id"))
    gambler_id: Mapped[int] = mapped_column(ForeignKey("gamblers.id"))
    comment: Mapped[str] = mapped_column(Text)
    # Deleted by its author. Kept rather than removed so the thread around it is not
    # renumbered, and left out of reply counts.
    archived_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True, default=None)

    pick: Mapped["Pick"] = relationship(back_populates="comments")
    gambler: Mapped["Gambler"] = relationship()


class Parlay(Base):
    __tablename__ = "parlays"

    gambling_season_id: Mapped[int] = mapped_column(ForeignKey("gambling_seasons.id"))
    owner_id: Mapped[int] = mapped_column(ForeignKey("gamblers.id"))
    slate_type: Mapped[SlateType] = mapped_column(SQLEnum(SlateType))
    competition_date: Mapped[datetime.date]
    state: Mapped[ParlayState] = mapped_column(SQLEnum(ParlayState))
    wager_pp: Mapped[float]
    payout_pp: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    result: Mapped[ParlayResult | None] = mapped_column(SQLEnum(ParlayResult), nullable=True, default=None)
    order: Mapped[int] = mapped_column(Integer, nullable=False)

    picks: Mapped[list[Pick]] = relationship(back_populates="parlay", cascade="all, delete-orphan")
    gambling_season: Mapped[GamblingSeason] = relationship(back_populates="parlays")
    owner: Mapped[Gambler] = relationship(back_populates="owned_parlays")
    assessments: Mapped[list["Assessment"]] = relationship(
        back_populates="parlay", passive_deletes=True
    )


# JSONB in Postgres, plain JSON wherever the tests build the schema in SQLite.
JSONDocument = JSON().with_variant(JSONB(), "postgresql")


class Assessment(Base):
    """What the model had to say against one pick, or against a whole parlay.

    A pick assessment has pick_id set; the parlay's own has it null. Rows are never
    updated: each is the answer to one exact input, identified by input_hash, so a pick
    changed and then changed back finds its old assessment again rather than paying for
    a new one.

    Two hashes, because they answer different questions. input_hash covers everything
    the model was shown — the pick, the gambler's history, their trends — and decides
    whether to call the model again. subject_hash covers only what was chosen (player,
    prop, line, direction, sauce, veto) and decides whether to show it: another parlay
    settling changes the history but not the pick, and should not hide an assessment of
    a pick nobody touched.
    """
    __tablename__ = "assessments"
    # Two partial indexes rather than one constraint, because a plain unique constraint
    # treats every null pick_id as distinct and would never stop a duplicate parlay row.
    __table_args__ = (
        Index(
            "uq_assessment_pick_input", "parlay_id", "pick_id", "input_hash",
            unique=True, postgresql_where=text("pick_id IS NOT NULL"),
        ),
        Index(
            "uq_assessment_parlay_input", "parlay_id", "input_hash",
            unique=True, postgresql_where=text("pick_id IS NULL"),
        ),
    )

    parlay_id: Mapped[int] = mapped_column(ForeignKey("parlays.id", ondelete="CASCADE"), index=True)
    pick_id: Mapped[int | None] = mapped_column(
        ForeignKey("picks.id", ondelete="CASCADE"), nullable=True, default=None
    )
    subject_hash: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    # What the pick or slate looked like when assessed, so a stale assessment can say what
    # it was about rather than simply vanishing.
    subject_snapshot: Mapped[dict] = mapped_column(JSONDocument)
    # Exactly what the model was sent. For working out why it said what it said.
    input_json: Mapped[dict] = mapped_column(JSONDocument)
    # [{"title": ..., "description": ...}]
    suggestions: Mapped[list] = mapped_column(JSONDocument)
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))

    parlay: Mapped["Parlay"] = relationship(back_populates="assessments")
    pick: Mapped["Pick | None"] = relationship(back_populates="assessments")



class SeasonPick(Base):
    """A pick that runs the whole season rather than sitting inside a parlay.

    Kept separate from Pick: there is no parlay, no veto, and no sauce factor, and
    team win totals have no prop type at all.
    """
    __tablename__ = "season_picks"

    gambling_season_id: Mapped[int] = mapped_column(ForeignKey("gambling_seasons.id"))
    gambler_id: Mapped[int] = mapped_column(ForeignKey("gamblers.id"))
    kind: Mapped[SeasonPickKind] = mapped_column(SQLEnum(SeasonPickKind))
    prop_bet_target_id: Mapped[int] = mapped_column(ForeignKey("prop_bet_targets.id"))
    # Null for TEAM_WINS, which is a win count rather than a stat line.
    prop_type: Mapped[PropBetType | None] = mapped_column(SQLEnum(PropBetType), nullable=True, default=None)
    line: Mapped[float] = mapped_column(Float)
    direction: Mapped[PropBetDirection] = mapped_column(SQLEnum(PropBetDirection))
    # Gamblers enter their own picks; the admin locks them in. A finalized pick is
    # editable only by the admin.
    is_finalized: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    gambler: Mapped["Gambler"] = relationship(back_populates="season_picks")
    gambling_season: Mapped["GamblingSeason"] = relationship()
    prop_bet_target: Mapped["PropBetTarget"] = relationship()
    weeks: Mapped[list["SeasonPickWeek"]] = relationship(
        back_populates="season_pick", cascade="all, delete-orphan"
    )


class SeasonPickWeek(Base):
    """One week's result for a season pick.

    Rows are sparse on purpose: a row existing means the week was entered, so a bye
    (played=False) is never confused with a week nobody has filled in yet. Season
    totals are summed from these on read rather than carried as a running value.
    """
    __tablename__ = "season_pick_weeks"
    __table_args__ = (UniqueConstraint("season_pick_id", "week", name="uq_season_pick_week"),)

    season_pick_id: Mapped[int] = mapped_column(ForeignKey("season_picks.id"))
    week: Mapped[int] = mapped_column(Integer)
    # False for a bye or any week the player or team did not have a game.
    played: Mapped[bool] = mapped_column(Boolean, default=True)
    # Whether the team had a game that week at all, which `played` cannot say on its own:
    # a player who sat out injured and a player on a bye both record played=False, and
    # only one of them used up a game. Null where it is not known — rows entered by hand,
    # and anything written before the sync started asking for the schedule.
    team_played: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    # PLAYER_PROP: the stat recorded that week. TEAM_WINS: 1 win, 0 loss, 0.5 tie.
    value: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)

    season_pick: Mapped["SeasonPick"] = relationship(back_populates="weeks")


class FeedbackStatus(StrEnum):
    OPEN = "Open"
    # Dealt with. The suggestion was built, or the problem it named is gone.
    RESOLVED = "Resolved"
    # Considered and declined. Kept rather than deleted so the same one does not come
    # back round every season with nobody remembering it was already answered.
    RETIRED = "Retired"


class Feedback(Base):
    """A suggestion or piece of feedback, raised within a season.

    Keyed to a gambler, which is a user within one season — so the season it belongs to
    comes for free, and so does the question of who may resolve it.
    """
    __tablename__ = "feedback"

    gambler_id: Mapped[int] = mapped_column(ForeignKey("gamblers.id"))
    # Written from the description on submission and editable afterwards, so the list can
    # be scanned without reading every suggestion in full.
    title: Mapped[str] = mapped_column(String(80))
    comment: Mapped[str] = mapped_column(Text)
    # Set by an admin. Anything other than OPEN is settled: it moves to its own tab and
    # stops taking votes and replies.
    status: Mapped[FeedbackStatus] = mapped_column(
        SQLEnum(FeedbackStatus), default=FeedbackStatus.OPEN, server_default=FeedbackStatus.OPEN.name
    )
    # Deleted by its author. Kept rather than removed so replies and votes are not orphaned.
    archived_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True, default=None)

    gambler: Mapped["Gambler"] = relationship()
    comments: Mapped[list["FeedbackComment"]] = relationship(
        back_populates="feedback", cascade="all, delete-orphan"
    )
    ratings: Mapped[list["FeedbackRating"]] = relationship(
        back_populates="feedback", cascade="all, delete-orphan"
    )


class FeedbackComment(Base):
    __tablename__ = "feedback_comments"

    feedback_id: Mapped[int] = mapped_column(ForeignKey("feedback.id"))
    gambler_id: Mapped[int] = mapped_column(ForeignKey("gamblers.id"))
    comment: Mapped[str] = mapped_column(Text)
    # Deleted by its author. Archived comments are hidden and left out of reply counts.
    archived_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True, default=None)

    feedback: Mapped["Feedback"] = relationship(back_populates="comments")
    gambler: Mapped["Gambler"] = relationship()


class FeedbackRating(Base):
    """One gambler's vote on one suggestion, up or down.

    A vote is a row, so there is at most one per gambler per suggestion and taking it back is a
    delete. The backlog is ranked on the sum of these, which is why the direction lives in
    the row rather than in two separate tallies.
    """
    __tablename__ = "feedback_ratings"
    __table_args__ = (UniqueConstraint("feedback_id", "gambler_id", name="uq_feedback_rating_gambler"),)

    feedback_id: Mapped[int] = mapped_column(ForeignKey("feedback.id"))
    gambler_id: Mapped[int] = mapped_column(ForeignKey("gamblers.id"))
    # +1 or -1. Rows predating downvotes were all upvotes, hence the server default.
    value: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    feedback: Mapped["Feedback"] = relationship(back_populates="ratings")


class PickList(Base):
    """A named list of picks a season keeps opinions on — today only the ban list.

    The list is per season rather than per gambler, and it is the *items* that carry whose
    entry they are. That is what lets one screen show everybody's bans side by side without
    a list row per person, and what makes a second list type a row rather than a table.
    """
    __tablename__ = "pick_lists"
    __table_args__ = (
        UniqueConstraint("gambling_season_id", "list_type", name="uq_pick_list_season_type"),
    )

    gambling_season_id: Mapped[int] = mapped_column(ForeignKey("gambling_seasons.id"))
    list_type: Mapped[PickListType] = mapped_column(SQLEnum(PickListType))
    # The name shown on the chip. Stored rather than derived from the type so a season can
    # call its ban list something else without the type meaning anything different.
    display_name: Mapped[str] = mapped_column(String)

    gambling_season: Mapped["GamblingSeason"] = relationship()
    items: Mapped[list["PickListItem"]] = relationship(
        back_populates="pick_list", cascade="all, delete-orphan"
    )


class PickListItem(Base):
    """One gambler's entry on one list: a player, optionally narrowed to a market and a side.

    Both narrowings are independently optional, which is the whole expressiveness of the
    thing: "Jamarr Chase" bans him outright, "Jamarr Chase / Rec Yards" bans that market
    either way, and "MHJ / Over" bans every over on him and no under. An entry is one
    banned bet — wanting MHJ's rec yards over *and* his TDs under is two rows, not one row
    with two markets on it.
    """
    __tablename__ = "pick_list_items"

    pick_list_id: Mapped[int] = mapped_column(ForeignKey("pick_lists.id"))
    gambler_id: Mapped[int] = mapped_column(ForeignKey("gamblers.id"))
    prop_bet_target_id: Mapped[int] = mapped_column(ForeignKey("prop_bet_targets.id"))
    # Null means every market on this target.
    prop_type: Mapped[PropBetType | None] = mapped_column(SQLEnum(PropBetType), nullable=True, default=None)
    # Null means both sides. Set, it matches only that side — an entry on the over says
    # nothing about somebody taking the under.
    direction: Mapped[PropBetDirection | None] = mapped_column(SQLEnum(PropBetDirection), nullable=True, default=None)

    pick_list: Mapped["PickList"] = relationship(back_populates="items")
    gambler: Mapped["Gambler"] = relationship()
    prop_bet_target: Mapped["PropBetTarget"] = relationship()

    def matches(self, prop_bet_target_id: int, prop_type: PropBetType | None, direction: PropBetDirection | None) -> bool:
        """Whether a bet falls under this entry.

        The one place the narrowing rules live: an unset field on the entry matches
        anything, a set one has to agree. Everything that decides whether a pick is on
        somebody's list goes through here, so the badge on a parlay and any later list
        type can never drift apart on what "on the list" means.
        """
        if self.prop_bet_target_id != prop_bet_target_id:
            return False
        if self.prop_type is not None and self.prop_type != prop_type:
            return False
        if self.direction is not None and self.direction != direction:
            return False
        return True
