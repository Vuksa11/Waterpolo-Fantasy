"""
Response models for the read-only sports-data API (Section: no fantasy-team
layer yet -- users/leagues/rosters/lineups don't exist. This exposes the real
data the scraper has already produced: competitions, standings, players,
matches, matchdays. See docs/Fantasy_Waterpolo_Arhitektura_v2.md, Section 7.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, computed_field, field_validator

# bcrypt hashes only the first 72 bytes of its input and raises ValueError on
# anything longer (confirmed: this is a hard C-library limit, not something
# truncating silently) -- both bcrypt.hashpw (register) and bcrypt.checkpw
# (login) throw, which without this check surfaces as an unhandled 500 for a
# password a user could reasonably type. Validating here turns it into a
# clean 422 instead. Bug found by the frontend session's test suite
# (test_auth_rejects_password_over_bcrypt_byte_limit) against the auth
# endpoints added in commit 4044304.
_MAX_PASSWORD_BYTES = 72


def _validate_password_length(password: str) -> str:
    if len(password.encode("utf-8")) > _MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {_MAX_PASSWORD_BYTES} bytes (UTF-8 encoded)")
    return password


class UserRegisterIn(BaseModel):
    email: EmailStr
    password: str
    display_name: str

    _validate_password = field_validator("password")(_validate_password_length)


class UserLoginIn(BaseModel):
    email: EmailStr
    password: str

    _validate_password = field_validator("password")(_validate_password_length)


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


class CoachOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: str | None
    name: str
    real_club: str
    current_cost: float


class PlayerCatalogOut(BaseModel):
    items: list[PlayerOut]
    total: int
    limit: int
    offset: int


class PlayerFacetsOut(BaseModel):
    clubs: list[str]
    positions: list[str]


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


class _MatchdayDisplayLabelMixin:
    """
    Shared by every schema that exposes a Matchday's `label`/`number`, so the
    "what should a user see" rule lives in exactly one place. See
    MatchdaySummary.display_label's docstring below for the full story
    (problemV13 caught that this was originally added only there, but
    /api/competitions/{id}/matchdays -- MatchdayOut, not MatchdaySummary --
    is what the live frontend's matchday dropdown/banner actually reads).
    """

    label: str

    @computed_field  # type: ignore[misc]
    @property
    def display_label(self) -> str:
        tail = self.label.split()[-1] if self.label else ""
        return tail if tail.isdigit() else self.label


class MatchdayOut(_MatchdayDisplayLabelMixin, BaseModel):
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


class TeamCreateIn(BaseModel):
    competition_id: uuid.UUID
    name: str
    player_ids: list[uuid.UUID]
    coach_id: uuid.UUID


class RosterEntryOut(BaseModel):
    entity_type: str
    entity_id: uuid.UUID
    name: str
    real_club: str
    purchase_price: float


class TeamOut(BaseModel):
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


class TopPerformerOut(BaseModel):
    player_id: uuid.UUID
    player_name: str
    real_club: str
    raw_points: float


class MatchdaySummary(_MatchdayDisplayLabelMixin, BaseModel):
    """
    `display_label` (from _MatchdayDisplayLabelMixin above): `number` is a
    scraper-internal sort key ONLY (see scraper/db_writer.py's
    _round_number docstring) -- regular rounds get their real round number,
    but playoff rounds (Semifinal, Final, ...) get large fixed offsets
    (9000+) purely so they sort after the regular season without colliding
    with each other. That was never meant to be shown to a user, but nothing
    in this schema said so before this field existed, and a real check of
    the live frontend caught it rendering a literal "9300 KOLO" for a Final
    matchday. `display_label` always returns something presentable: the
    plain round number as a string for a normal round, or the round's own
    label ("Final", "Semifinal", ...) for anything else.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    number: int
    status: str
    deadline: datetime | None


class HomeOut(BaseModel):
    """
    GET /api/home contract -- agreed with the frontend session
    (docs/FRONTEND_BACKEND_HANDOFF.md) specifically to avoid a 4-5 request
    waterfall for the page most users land on first. Deliberately excludes
    anything private (a user's own team) or not shown on that page (full
    catalog, all coaches, top performers) -- those stay separate calls.
    """

    competition_id: uuid.UUID
    selected_matchday: MatchdaySummary | None
    matches: list[MatchOut]
    standings_top4: list[StandingsRow]
    # None means "no successful scrape on record" -- genuinely unknown
    # freshness, not "just updated". See home.py for why this must not
    # default to the current time.
    updated_at: datetime | None
