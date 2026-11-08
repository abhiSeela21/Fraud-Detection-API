"""Persist immutable scores and editable alert feedback."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("id", sa.Uuid(), nullable=False, unique=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("demo_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.String(84), nullable=False),
        sa.Column("run_id", sa.Uuid()),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("result", JSONB(), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("recommendation", sa.String(6), nullable=False),
        sa.UniqueConstraint("session_id", "client_transaction_id"),
    )
    op.create_index("ix_transactions_session_sequence", "transactions", ["session_id", "sequence"])
    op.create_index(
        "ix_transactions_history",
        "transactions",
        ["session_id", "account_id", "run_id", "event_at"],
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "transaction_sequence",
            sa.BigInteger(),
            sa.ForeignKey("transactions.sequence", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("feedback", sa.String(10)),
        sa.Column("feedback_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_table("transactions")
