"""task plans are kept, answered and approved

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A new table: nothing to carry over, and nothing that existing rows hang off, so no rebuild of any other table (see 0006).
    op.create_table(
        "plan_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("repo_name", sa.String(200), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("rev", sa.Integer(), nullable=False),
        sa.Column("approved_at", sa.String(32), nullable=True),
        sa.Column("approval", sa.JSON(), nullable=True),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False, server_default="local"),
    )
    op.create_index("ix_plan_sessions_status", "plan_sessions", ["status"])
    op.create_index("ix_plan_sessions_user_id", "plan_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_plan_sessions_user_id", table_name="plan_sessions")
    op.drop_index("ix_plan_sessions_status", table_name="plan_sessions")
    op.drop_table("plan_sessions")
