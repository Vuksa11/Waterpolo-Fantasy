"""merge frontend lineup/catalog-indexes branch with main performance/idempotency branch

Revision ID: 11873788c5dc
Revises: d86291b3557f, d93418e3b502
Create Date: 2026-09-06 21:39:34.083538

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '11873788c5dc'
down_revision: Union[str, None] = ('d86291b3557f', 'd93418e3b502')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
