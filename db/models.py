"""
SQLAlchemy models matching docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 5.1.

Polymorphic entity references (roster/lineup/fantasy_score/transfer_history/price_history
slots that can point at either a Player or a Coach) use an (entity_type, entity_id) pair
instead of two nullable FKs, per the original v1 architecture decision (Section 6.2 of the
v1 document). PostgreSQL cannot enforce referential integrity across the polymorphic
boundary — orphan prevention is the application's responsibility.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


# --- Enums --------------------------------------------------------------

class Position(str, enum.Enum):
    GK = "GK"
    OT = "OT"
    CF = "CF"
    CB = "CB"


class SeasonStatus(str, enum.Enum):
    UPCOMING = "UPCOMING"
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"


class MatchdayStatus(str, enum.Enum):
    UPCOMING = "UPCOMING"
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"


class MatchStatus(str, enum.Enum):
    UPCOMING = "UPCOMING"
    LIVE = "LIVE"
    FINISHED = "FINISHED"


class LeagueVisibility(str, enum.Enum):
    PRIVATE = "PRIVATE"
    PUBLIC = "PUBLIC"


class Formation(str, enum.Enum):
    THREE_THREE = "THREE_THREE"
    FOUR_TWO = "FOUR_TWO"
    TWO_FOUR = "TWO_FOUR"


class EntityType(str, enum.Enum):
    PLAYER = "PLAYER"
    COACH = "COACH"


class Slot(str, enum.Enum):
    ACTIVE = "ACTIVE"
    BENCH = "BENCH"


class SlotRole(str, enum.Enum):
    GK = "GK"
    OT = "OT"
    CF = "CF"
    CB = "CB"
    CF_CB = "CF_CB"


class CoachResult(str, enum.Enum):
    WIN = "WIN"
    DRAW = "DRAW"
    LOSS = "LOSS"


class TransferAction(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


# --- Core entities --------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String)
    google_id: Mapped[str | None] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Competition(Base):
    """One of the three real-world leagues: Regionalna liga, Super liga Srbije, Prva liga Srbije."""

    __tablename__ = "competitions"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    source_slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    # The competition's schedule page on totalwaterpolo.com, discovered from
    # any of its matches' `tw-competition-url` attribute (see
    # scraper/parsers/match_page.py). Nullable because a competition can be
    # created from a match box score before its schedule page has ever been
    # visited.
    schedule_url: Mapped[str | None] = mapped_column(String)


class Season(Base):
    __tablename__ = "seasons"

    id: Mapped[uuid.UUID] = uuid_pk()
    competition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("competitions.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[SeasonStatus] = mapped_column(Enum(SeasonStatus, name="season_status"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)


class Matchday(Base):
    __tablename__ = "matchdays"

    id: Mapped[uuid.UUID] = uuid_pk()
    season_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seasons.id"), nullable=False, index=True)
    # The site's own round label (e.g. "Round 7", but also non-numeric playoff
    # rounds like "Semifinal" / "Bronze medal" / "Final" -- confirmed on a real
    # season). This, not `number`, is the actual identity of a matchday within
    # a season -- `number` alone can't distinguish two differently-named
    # rounds that both lack digits.
    label: Mapped[str] = mapped_column(String, nullable=False)
    # Best-effort sort key derived from `label` (see scraper/db_writer.py);
    # not guaranteed unique for non-numeric labels.
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Nullable: lineup-deadline policy isn't implemented yet (see docs Section
    # 7, Next Steps) — the scraper creates a Matchday as soon as it discovers a
    # round, before any deadline has been computed.
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[MatchdayStatus] = mapped_column(Enum(MatchdayStatus, name="matchday_status"), nullable=False)


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = uuid_pk()
    matchday_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("matchdays.id"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    home_club: Mapped[str] = mapped_column(String, nullable=False)
    away_club: Mapped[str] = mapped_column(String, nullable=False)
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[MatchStatus] = mapped_column(Enum(MatchStatus, name="match_status"), nullable=False)
    # Nullable: the scraper discovers a match from the fixture-list page (teams,
    # score, no kickoff time) before it ever fetches that match's own page,
    # which is the only place kickoff time is exposed. Backfilled once the box
    # score is fetched. See docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 4.1a.
    kickoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Player(Base):
    __tablename__ = "players"

    id: Mapped[uuid.UUID] = uuid_pk()
    competition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("competitions.id"), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(String)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Nullable: the match box score distinguishes goalkeepers from field
    # players (separate DOM section) but does not expose OT/CF/CB for field
    # players anywhere — confirmed absent from a real sampled match page. Left
    # null until a team-squad page (also needed for goalkeeper id resolution,
    # see scraper/player_resolver.py) is found to expose it.
    # external_id is nullable for the same reason a goalkeeper has no id on
    # the match page (see player_resolver.py) — a field player's is always
    # populated at creation time; a goalkeeper's is filled in once resolved.
    position: Mapped[Position | None] = mapped_column(Enum(Position, name="player_position"))
    real_club: Mapped[str] = mapped_column(String, nullable=False)
    current_cost: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=7)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Coach(Base):
    __tablename__ = "coaches"

    id: Mapped[uuid.UUID] = uuid_pk()
    competition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("competitions.id"), nullable=False, index=True)
    # Nullable: no coach data source has been scraped yet (see docs, Section
    # 7). Coaches are currently generic placeholders created directly in the
    # database (one per club, name suffixed "— trener TBD"), with no external
    # site id to attach until a real source/mapping is provided.
    external_id: Mapped[str | None] = mapped_column(String)
    name: Mapped[str] = mapped_column(String, nullable=False)
    real_club: Mapped[str] = mapped_column(String, nullable=False)
    current_cost: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=7)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class League(Base):
    """
    Fantasy league (not to be confused with Competition, the real-world league).
    In v1, exactly one row per (season_id) is created by the platform: admin_id
    is NULL and visibility is PUBLIC. The schema already supports user-created
    leagues (per v1 doc) for a future version — no migration needed to enable it.
    """

    __tablename__ = "leagues"

    id: Mapped[uuid.UUID] = uuid_pk()
    season_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seasons.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    visibility: Mapped[LeagueVisibility] = mapped_column(
        Enum(LeagueVisibility, name="league_visibility"), nullable=False, default=LeagueVisibility.PUBLIC
    )
    invite_code: Mapped[str | None] = mapped_column(String, unique=True)
    admin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class FantasyTeam(Base):
    __tablename__ = "fantasy_teams"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    league_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leagues.id"), nullable=False, index=True)
    season_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("seasons.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    credit_balance: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=100)
    total_points: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    wildcard_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Roster(Base):
    """A player or coach slot on a fantasy team. Polymorphic entity reference."""

    __tablename__ = "rosters"

    id: Mapped[uuid.UUID] = uuid_pk()
    fantasy_team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fantasy_teams.id"), nullable=False, index=True
    )
    entity_type: Mapped[EntityType] = mapped_column(Enum(EntityType, name="entity_type"), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    purchase_price: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Lineup(Base):
    """One slot in a fantasy team's lineup for a specific matchday. Polymorphic entity reference."""

    __tablename__ = "lineups"

    id: Mapped[uuid.UUID] = uuid_pk()
    fantasy_team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fantasy_teams.id"), nullable=False, index=True
    )
    matchday_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("matchdays.id"), nullable=False, index=True)
    formation: Mapped[Formation] = mapped_column(Enum(Formation, name="formation"), nullable=False)
    entity_type: Mapped[EntityType] = mapped_column(Enum(EntityType, name="entity_type"), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    slot: Mapped[Slot] = mapped_column(Enum(Slot, name="slot"), nullable=False)
    slot_role: Mapped[SlotRole] = mapped_column(Enum(SlotRole, name="slot_role"), nullable=False)
    is_captain: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PlayerStat(Base):
    """Raw per-player statistics per match, scraped from totalwaterpolo.com."""

    __tablename__ = "player_stats"

    id: Mapped[uuid.UUID] = uuid_pk()
    match_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("players.id"), nullable=False, index=True)
    goals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assists: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fouls_drawn: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    steals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    swimoffs_won: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    misses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    personal_fouls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    turnovers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    offensive_fouls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    saves: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    goals_conceded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class CoachStat(Base):
    """Pre-calculated per-coach statistics per match."""

    __tablename__ = "coach_stats"

    id: Mapped[uuid.UUID] = uuid_pk()
    match_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    coach_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("coaches.id"), nullable=False, index=True)
    goals_for: Mapped[int] = mapped_column(Integer, nullable=False)
    goals_against: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[CoachResult] = mapped_column(Enum(CoachResult, name="coach_result"), nullable=False)
    fantasy_points: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class FantasyScore(Base):
    """Calculated fantasy points per player or coach per matchday. Polymorphic entity reference."""

    __tablename__ = "fantasy_scores"
    __table_args__ = (
        # The natural lookup key for every query this table actually gets
        # (recompute upsert, a player's season total, top-performers) --
        # without it each of those is a full scan once this table is large.
        Index("ix_fantasy_scores_matchday_entity", "matchday_id", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    matchday_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("matchdays.id"), nullable=False)
    entity_type: Mapped[EntityType] = mapped_column(Enum(EntityType, name="entity_type"), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    raw_points: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    final_points: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    is_finalized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class TransferHistoryEntry(Base):
    """Append-only audit log of every transfer. Never updated or deleted. Polymorphic entity reference."""

    __tablename__ = "transfer_history"

    id: Mapped[uuid.UUID] = uuid_pk()
    fantasy_team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fantasy_teams.id"), nullable=False, index=True
    )
    matchday_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("matchdays.id"), nullable=False)
    action: Mapped[TransferAction] = mapped_column(Enum(TransferAction, name="transfer_action"), nullable=False)
    entity_type: Mapped[EntityType] = mapped_column(Enum(EntityType, name="entity_type"), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    credit_balance_after: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    is_wildcard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PriceHistoryEntry(Base):
    """Log of player/coach credit cost changes between matchdays. Polymorphic entity reference."""

    __tablename__ = "price_history"
    __table_args__ = (
        # A player's full price history is the only query pattern this table
        # serves today (get_player detail) -- filtered by entity, then joined
        # to matchdays for ordering.
        Index("ix_price_history_entity", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    entity_type: Mapped[EntityType] = mapped_column(Enum(EntityType, name="entity_type"), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    matchday_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("matchdays.id"), nullable=False)
    old_cost: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    new_cost: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ScrapeRun(Base):
    """Operational log for the scraper (docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 4.2)."""

    __tablename__ = "scrape_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    matches_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)


class IdempotencyKey(Base):
    """
    Lets a client safely retry a write (e.g. after a network timeout) without
    risking a duplicate team/transfer -- proposed by the frontend session's
    performance review (docs/FRONTEND_BACKEND_HANDOFF.md): a client-supplied
    `Idempotency-Key` header, scoped per (user, endpoint, key). A repeated
    request with the same key returns the original response instead of
    re-running the operation.

    Two-phase, not single-write (the frontend session's second review caught
    both bugs a naive single-write version has -- see scraper.../teams.py's
    _claim_idempotency_key docstring for the full reasoning): a row is
    inserted as `response_status=0` ("pending") in its own committed
    transaction to atomically claim the key via the unique index below, THEN
    updated with the real response in the same transaction as the business
    write it guards. `response_status=0` should never be visible to a
    replay reader for long -- if it is, either the operation is still
    genuinely in flight (caller gets a 409, retries shortly) or a process
    crashed mid-request and left an orphaned claim (needs a background sweep
    to clean up; not implemented yet).
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        Index("ix_idempotency_keys_lookup", "user_id", "endpoint", "key", unique=True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
