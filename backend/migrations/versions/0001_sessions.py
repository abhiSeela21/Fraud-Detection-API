"""Create anonymous demo sessions."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "demo_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_demo_sessions_expires_at", "demo_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_table("demo_sessions")
