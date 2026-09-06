"""Add competition-scoped player catalog indexes without blocking writes.

Revision ID: c83207f2a491
Revises: f2806bcaae2f
"""
from alembic import op
import sqlalchemy as sa

revision = 'c83207f2a491'
down_revision = 'f2806bcaae2f'
branch_labels = None
depends_on = None

INDEXES = [
    ('ix_players_competition_cost_id', ['competition_id', sa.text('current_cost DESC'), 'id']),
    ('ix_players_competition_name_id', ['competition_id', 'name', 'id']),
    ('ix_players_competition_club_position', ['competition_id', 'real_club', 'position']),
]


def upgrade():
    # PostgreSQL requires CONCURRENTLY outside a transaction. Apply separately
    # from any data migrations; this revision does not change stored data.
    with op.get_context().autocommit_block():
        for name, columns in INDEXES:
            op.create_index(name, 'players', columns, postgresql_concurrently=True)


def downgrade():
    with op.get_context().autocommit_block():
        for name, _ in reversed(INDEXES):
            op.drop_index(name, table_name='players', postgresql_concurrently=True)
