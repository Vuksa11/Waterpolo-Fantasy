"""add performance indexes

Revision ID: e2f53c959c38
Revises: f2806bcaae2f
Create Date: 2026-09-06 19:21:27.400631

Part of the performance/scale plan in docs/FRONTEND_BACKEND_HANDOFF.md.
Uses CONCURRENTLY (same pattern as Codex's c83207f2a491 catalog-indexes
migration) so this never blocks writes on the tables involved -- matters
once these tables are under real concurrent load, not just for this
still-tiny dataset. CONCURRENTLY can't run inside a transaction, hence the
autocommit_block.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e2f53c959c38'
down_revision: Union[str, None] = 'f2806bcaae2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES = [
    ("ix_coach_stats_coach_id", "coach_stats", ["coach_id"]),
    ("ix_coach_stats_match_id", "coach_stats", ["match_id"]),
    ("ix_coaches_competition_id", "coaches", ["competition_id"]),
    ("ix_fantasy_scores_matchday_entity", "fantasy_scores", ["matchday_id", "entity_type", "entity_id"]),
    ("ix_fantasy_teams_league_id", "fantasy_teams", ["league_id"]),
    ("ix_fantasy_teams_user_id", "fantasy_teams", ["user_id"]),
    ("ix_leagues_season_id", "leagues", ["season_id"]),
    ("ix_lineups_fantasy_team_id", "lineups", ["fantasy_team_id"]),
    ("ix_lineups_matchday_id", "lineups", ["matchday_id"]),
    ("ix_matchdays_season_id", "matchdays", ["season_id"]),
    ("ix_matches_matchday_id", "matches", ["matchday_id"]),
    ("ix_player_stats_match_id", "player_stats", ["match_id"]),
    ("ix_player_stats_player_id", "player_stats", ["player_id"]),
    ("ix_players_competition_id", "players", ["competition_id"]),
    ("ix_price_history_entity", "price_history", ["entity_type", "entity_id"]),
    ("ix_rosters_fantasy_team_id", "rosters", ["fantasy_team_id"]),
    ("ix_seasons_competition_id", "seasons", ["competition_id"]),
    ("ix_transfer_history_fantasy_team_id", "transfer_history", ["fantasy_team_id"]),
]


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, table, columns in _INDEXES:
            op.create_index(name, table, columns, unique=False, postgresql_concurrently=True)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, table, _columns in reversed(_INDEXES):
            op.drop_index(name, table_name=table, postgresql_concurrently=True)
