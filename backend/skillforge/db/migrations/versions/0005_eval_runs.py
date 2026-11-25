"""Testing Lab runs are kept

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("runs", sa.Integer(), nullable=False),
        sa.Column("baseline", sa.Boolean(), nullable=False),
        sa.Column("cases_total", sa.Integer(), nullable=False),
        sa.Column("cases_done", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_eval_runs_status", "eval_runs", ["status"])
    op.create_index("ix_eval_runs_name", "eval_runs", ["name"])


def downgrade() -> None:
    op.drop_index("ix_eval_runs_name", table_name="eval_runs")
    op.drop_index("ix_eval_runs_status", table_name="eval_runs")
    op.drop_table("eval_runs")
