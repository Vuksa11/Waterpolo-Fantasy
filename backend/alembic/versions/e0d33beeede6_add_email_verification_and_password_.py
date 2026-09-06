"""add email verification and password reset fields to users

Revision ID: e0d33beeede6
Revises: 11873788c5dc
Create Date: 2026-09-07 00:54:28.410334

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e0d33beeede6'
down_revision: Union[str, None] = '11873788c5dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('users', sa.Column('email_verification_token', sa.String(), nullable=True))
    op.add_column('users', sa.Column('email_verification_token_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('password_reset_token', sa.String(), nullable=True))
    op.add_column('users', sa.Column('password_reset_token_expires_at', sa.DateTime(timezone=True), nullable=True))
    # Named explicitly -- autogenerate's `None` name works for CREATE (the
    # DB picks a name) but not for the DROP in downgrade(), which needs a
    # real name to reference.
    op.create_unique_constraint('uq_users_password_reset_token', 'users', ['password_reset_token'])
    op.create_unique_constraint('uq_users_email_verification_token', 'users', ['email_verification_token'])


def downgrade() -> None:
    op.drop_constraint('uq_users_email_verification_token', 'users', type_='unique')
    op.drop_constraint('uq_users_password_reset_token', 'users', type_='unique')
    op.drop_column('users', 'password_reset_token_expires_at')
    op.drop_column('users', 'password_reset_token')
    op.drop_column('users', 'email_verification_token_expires_at')
    op.drop_column('users', 'email_verification_token')
    op.drop_column('users', 'email_verified')
