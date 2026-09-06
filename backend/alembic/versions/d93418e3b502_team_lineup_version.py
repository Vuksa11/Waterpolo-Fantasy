"""Version team mutations and represent coach lineup roles without a fake position."""
from alembic import op
import sqlalchemy as sa
revision = 'd93418e3b502'
down_revision = 'c83207f2a491'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('fantasy_teams', sa.Column('version', sa.Integer(), server_default='0', nullable=False))
    op.alter_column('lineups', 'slot_role', existing_type=sa.Enum('GK','OT','CF','CB','CF_CB', name='slot_role'), nullable=True)

def downgrade():
    # Coach rows have no player role; do not manufacture one on downgrade.
    op.execute("DELETE FROM lineups WHERE entity_type = 'COACH' AND slot_role IS NULL")
    op.alter_column('lineups', 'slot_role', existing_type=sa.Enum('GK','OT','CF','CB','CF_CB', name='slot_role'), nullable=False)
    op.drop_column('fantasy_teams', 'version')
