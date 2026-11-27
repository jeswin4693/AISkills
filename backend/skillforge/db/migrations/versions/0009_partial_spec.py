"""a builder session keeps the requirement as far as it is answered, between rounds

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nothing is stored for sessions that already exist: their next round simply has nothing to keep. A plain ADD COLUMN, never a table rebuild (see 0006).
    op.add_column("build_sessions", sa.Column("partial_spec", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("build_sessions", "partial_spec")  # plain DROP COLUMN: a batch rebuild could cascade-delete the rows that hang off a session (see 0006)
