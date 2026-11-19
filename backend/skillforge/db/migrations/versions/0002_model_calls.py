"""model calls: one row per attempt at a model, for the usage shown per session

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_calls",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("build_sessions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("job_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("task", sa.String(16), nullable=False),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("error_kind", sa.String(16), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=False),
    )
    op.create_index("ix_model_calls_session_id", "model_calls", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_model_calls_session_id", table_name="model_calls")
    op.drop_table("model_calls")
