"""behaviour scan runs are kept

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A new table: nothing to carry over, and nothing that existing rows hang off, so no rebuild of any other table (see 0006).
    op.create_table(
        "scan_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("runs", sa.Integer(), nullable=False),
        sa.Column("scenarios", sa.Integer(), nullable=False),
        sa.Column("control", sa.Boolean(), nullable=False),
        sa.Column("draft", sa.Boolean(), nullable=False),
        sa.Column("tasks_total", sa.Integer(), nullable=False),
        sa.Column("tasks_done", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False, server_default="local"),
    )
    op.create_index("ix_scan_runs_status", "scan_runs", ["status"])
    op.create_index("ix_scan_runs_name", "scan_runs", ["name"])
    op.create_index("ix_scan_runs_user_id", "scan_runs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_scan_runs_user_id", table_name="scan_runs")
    op.drop_index("ix_scan_runs_name", table_name="scan_runs")
    op.drop_index("ix_scan_runs_status", table_name="scan_runs")
    op.drop_table("scan_runs")
