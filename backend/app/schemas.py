"""
Response models for the read-only sports-data API (Section: no fantasy-team
layer yet -- users/leagues/rosters/lineups don't exist. This exposes the real
data the scraper has already produced: competitions, standings, players,
matches, matchdays. See docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 7.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from typing import Literal


class UserRegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    display_name: str = Field(min_length=1, max_length=60)

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value):
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 UTF-8 bytes")
        return value


class UserLoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=72)

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value):
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 UTF-8 bytes")
        return value


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CompetitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source_slug: str
    schedule_url: str | None


class StandingsRow(BaseModel):
    club: str
    played: int
    won: int
    lost: int
    goals_for: int
    goals_against: int
    goal_difference: int
    points: int


class PlayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: str | None
    name: str
    position: str | None
    real_club: str
    current_cost: float


class PlayerSeasonStats(BaseModel):
    total_raw_points: float
    matchdays_played: int


class PriceHistoryPoint(BaseModel):
    matchday_number: int
    matchday_label: str
    old_cost: float
    new_cost: float


class PlayerDetailOut(PlayerOut):
    season: PlayerSeasonStats
    price_history: list[PriceHistoryPoint]


class MatchdayOut(BaseModel):
    deadline: datetime | None = None
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    number: int
    status: str


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: str
    home_club: str
    away_club: str
    home_score: int | None
    away_score: int | None
    status: str
    kickoff_at: datetime | None


class PlayerStatOut(BaseModel):
    player_id: uuid.UUID
    player_name: str
    club: str
    goals: int
    assists: int
    fouls_drawn: int
    steals: int
    blocks: int
    swimoffs_won: int
    misses: int
    personal_fouls: int
    turnovers: int
    offensive_fouls: int
    saves: int
    goals_conceded: int
    raw_points: float


class MatchDetailOut(MatchOut):
    player_stats: list[PlayerStatOut]


class TopPerformerOut(BaseModel):
    player_id: uuid.UUID
    player_name: str
    real_club: str
    raw_points: float


class PlayerCatalogOut(BaseModel):
    items: list[PlayerOut]
    total: int
    limit: int
    offset: int


class PlayerFacetsOut(BaseModel):
    clubs: list[str]
    positions: list[str]


Formation = Literal["THREE_THREE", "FOUR_TWO", "TWO_FOUR"]


class LineupValidationIn(BaseModel):
    formation: Formation
    active_player_ids: list[uuid.UUID] = Field(min_length=7, max_length=7)
    captain_id: uuid.UUID
    competition_id: uuid.UUID | None = None


class LineupValidationOut(BaseModel):
    valid: Literal[True] = True
    formation: Formation
    counts: dict[str, int]


class TeamCreateIn(BaseModel):
    competition_id: uuid.UUID
    name: str = Field(min_length=1, max_length=40)
    player_ids: list[uuid.UUID] = Field(min_length=11, max_length=11)
    coach_id: uuid.UUID


class RosterEntryOut(BaseModel):
    entity_type: str
    entity_id: uuid.UUID
    name: str
    real_club: str
    purchase_price: float
    position: str | None
    current_cost: float


class TeamOut(BaseModel):
    competition_id: uuid.UUID
    version: int
    id: uuid.UUID
    league_id: uuid.UUID
    season_id: uuid.UUID
    name: str
    credit_balance: float
    total_points: float
    wildcard_used: bool
    roster: list[RosterEntryOut]


class TransferIn(BaseModel):
    drop_entity_type: str
    drop_entity_id: uuid.UUID
    add_entity_type: str
    add_entity_id: uuid.UUID




class CoachOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    real_club: str
    current_cost: float


class SavedLineupIn(BaseModel):
    formation: Formation
    active_player_ids: list[uuid.UUID] = Field(min_length=7, max_length=7)
    captain_id: uuid.UUID
    expected_version: int = Field(ge=0)


class SavedLineupOut(BaseModel):
    team_id: uuid.UUID
    matchday_id: uuid.UUID
    formation: Formation | None
    active_player_ids: list[uuid.UUID]
    bench_player_ids: list[uuid.UUID]
    captain_id: uuid.UUID | None
    coach_id: uuid.UUID | None
    version: int
