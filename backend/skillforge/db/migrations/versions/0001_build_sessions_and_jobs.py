"""build sessions and jobs

Revision ID: 0001
Revises:
Create Date: 2026-11-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "build_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("words", sa.Text, nullable=False),
        sa.Column("round", sa.Integer, nullable=False),
        sa.Column("with_scripts", sa.Boolean, nullable=False),
        sa.Column("questions", sa.JSON, nullable=False),
        sa.Column("spec", sa.JSON, nullable=True),
        sa.Column("result", sa.JSON, nullable=True),
        sa.Column("error", sa.Text, nullable=False),
        sa.Column("retryable", sa.Boolean, nullable=False),
        sa.Column("model_calls", sa.Integer, nullable=False),
        sa.Column("notes", sa.JSON, nullable=False),
        sa.Column("saved_name", sa.String(64), nullable=False),
        sa.Column("saved_version", sa.String(16), nullable=False),
    )
    op.create_index("ix_build_sessions_status", "build_sessions", ["status"])
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("build_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("started_at", sa.String(32), nullable=True),
        sa.Column("finished_at", sa.String(32), nullable=True),
        sa.Column("events", sa.JSON, nullable=False),
        sa.Column("error", sa.Text, nullable=False),
    )
    op.create_index("ix_jobs_session_id", "jobs", ["session_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_session_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_build_sessions_status", table_name="build_sessions")
    op.drop_table("build_sessions")
