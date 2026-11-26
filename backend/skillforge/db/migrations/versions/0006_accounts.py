"""accounts: a users table, and an owner on everything a person makes

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-26
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

OWNED = ("build_sessions", "suggest_runs", "eval_runs", "model_calls")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("google_sub", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("picture", sa.String(500), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("last_login_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)
    op.create_index("ix_users_email", "users", ["email"])
    # Everything that exists now was made by the one person who used the app, the owner (id "local"), so that is the default for the rows already there.
    # A plain ADD COLUMN, not a table rebuild: with SQLite's foreign keys on, rebuilding build_sessions would cascade-delete the jobs that point at it.
    for table in OWNED:
        op.add_column(table, sa.Column("user_id", sa.String(32), nullable=False, server_default="local"))
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])


def downgrade() -> None:
    for table in OWNED:
        op.drop_index(f"ix_{table}_user_id", table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column("user_id")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_google_sub", table_name="users")
    op.drop_table("users")
