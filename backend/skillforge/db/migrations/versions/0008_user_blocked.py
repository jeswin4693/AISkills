"""an owner can turn a person's account off

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-26
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Everyone who has signed in so far is on. A plain ADD COLUMN, never a table rebuild (see 0006).
    op.add_column("users", sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("users", "blocked")  # plain DROP COLUMN: a batch rebuild could cascade-delete the rows that hang off a person (see 0006)
