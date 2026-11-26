"""a person's own model (sealed key), and whose key paid for each model call

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-26
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_models",
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("key_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    # Every call recorded so far used the server's model (the only one there was). A plain ADD COLUMN, never a table rebuild (see 0006).
    op.add_column("model_calls", sa.Column("key_source", sa.String(8), nullable=False, server_default="server"))


def downgrade() -> None:
    op.drop_column("model_calls", "key_source")  # plain DROP COLUMN: a batch rebuild would cascade-delete rows (see 0006)
    op.drop_table("user_models")
