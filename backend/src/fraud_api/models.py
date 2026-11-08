from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DemoSession(Base):
    __tablename__ = "demo_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ScoredTransaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("session_id", "client_transaction_id"),
        Index("ix_transactions_session_sequence", "session_id", "sequence"),
        Index("ix_transactions_history", "session_id", "account_id", "run_id", "event_at"),
    )

    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    id: Mapped[UUID] = mapped_column(unique=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("demo_sessions.id", ondelete="CASCADE"))
    client_transaction_id: Mapped[UUID]
    account_id: Mapped[str] = mapped_column(String(84))
    run_id: Mapped[UUID | None]
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    risk_score: Mapped[int]
    recommendation: Mapped[str] = mapped_column(String(6))


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    transaction_sequence: Mapped[int] = mapped_column(
        ForeignKey("transactions.sequence", ondelete="CASCADE"), unique=True
    )
    feedback: Mapped[Literal["fraud", "legitimate"] | None] = mapped_column(String(10))
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
