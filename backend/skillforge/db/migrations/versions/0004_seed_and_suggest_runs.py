"""a build session can start from a repository, and suggestion runs are kept

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("build_sessions") as batch:
        batch.add_column(sa.Column("seed", sa.JSON(), nullable=True))
    op.create_table(
        "suggest_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("repo", sa.Text(), nullable=False),
        sa.Column("repo_name", sa.String(200), nullable=False),
        sa.Column("focus", sa.Text(), nullable=True),
        sa.Column("with_ideas", sa.Boolean(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_suggest_runs_status", "suggest_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_suggest_runs_status", table_name="suggest_runs")
    op.drop_table("suggest_runs")
    with op.batch_alter_table("build_sessions") as batch:
        batch.drop_column("seed")
