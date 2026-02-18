import datetime
from enum import StrEnum

from sqlalchemy import Float, ForeignKey, Enum as SQLEnum, Integer, String, null
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

    vetoes: Mapped[list["PickVeto"]] = relationship(back_populates="gambler")
    owned_parlays: Mapped[list["Parlay"]] = relationship(back_populates="owner")
    picks: Mapped[list["Pick"]] = relationship(back_populates="gambler")

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

    identifier: Mapped[str] = mapped_column(String, unique=True, index=True)
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

    gambler: Mapped["Gambler"] = relationship(back_populates="picks")
    veto: Mapped["PickVeto | None"] = relationship(back_populates="pick", cascade="all, delete-orphan")
    parlay: Mapped["Parlay"] = relationship(back_populates="picks")
    prop_bet_target: Mapped["PropBetTarget"] = relationship(back_populates="picks")

class PickVeto(Base):
    __tablename__ = "pick_vetoes"

    pick_id: Mapped[int] = mapped_column(ForeignKey("picks.id"))
    gambler_id: Mapped[int] = mapped_column(ForeignKey("gamblers.id"))
    approval_status: Mapped[VetoApprovalStatus] = mapped_column(SQLEnum(VetoApprovalStatus), default=VetoApprovalStatus.PENDING)
    result: Mapped[VetoResult | None] = mapped_column(SQLEnum(VetoResult), nullable=True, default=None)

    gambler: Mapped[Gambler] = relationship(back_populates="vetoes")
    pick: Mapped["Pick"] = relationship(back_populates="veto")
    votes: Mapped[list["VetoVote"]] = relationship(back_populates="veto", cascade="all, delete-orphan")

class VetoVote(Base):
    __tablename__ = "veto_votes"

    veto_id: Mapped[int] = mapped_column(ForeignKey("pick_vetoes.id"))
    gambler_id: Mapped[int] = mapped_column(ForeignKey("gamblers.id"))
    affirmative: Mapped[bool]

    veto: Mapped[PickVeto] = relationship(back_populates="votes")

    

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

