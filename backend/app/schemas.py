"""
Response models for the read-only sports-data API (Section: no fantasy-team
layer yet -- users/leagues/rosters/lineups don't exist. This exposes the real
data the scraper has already produced: competitions, standings, players,
matches, matchdays. See docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 7.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserRegisterIn(BaseModel):
    email: EmailStr
    password: str
    display_name: str


class UserLoginIn(BaseModel):
    email: EmailStr
    password: str


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
