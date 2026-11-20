"""build sessions get a kind (skill, later agent, plugin, mcp) and a parent for child builds

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-20
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Every session made before this was a skill, so that is the default for the rows already there.
    with op.batch_alter_table("build_sessions") as batch:
        batch.add_column(sa.Column("kind", sa.String(16), nullable=False, server_default="skill"))
        batch.add_column(sa.Column("parent_id", sa.String(32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("build_sessions") as batch:
        batch.drop_column("parent_id")
        batch.drop_column("kind")
