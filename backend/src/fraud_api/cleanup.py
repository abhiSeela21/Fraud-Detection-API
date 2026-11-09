"""Bounded expiry maintenance; only expired sessions are eligible."""

import argparse
import logging
from datetime import UTC, datetime
from threading import Lock
from time import monotonic

from sqlalchemy import Engine, delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fraud_api.config import get_settings
from fraud_api.models import DemoSession

_lock = Lock()
_next_attempt = 0.0
logger = logging.getLogger("fraud_api.maintenance")


def cleanup_batch(db: Session, limit: int, now: datetime | None = None) -> int:
    if not 1 <= limit <= 1000:
        raise ValueError("Cleanup batch must be between 1 and 1000")
    expired = list(
        db.scalars(
            select(DemoSession.id)
            .where(
                DemoSession.expires_at <= (now or datetime.now(UTC)),
            )
            .order_by(DemoSession.expires_at, DemoSession.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    if expired:
        db.execute(delete(DemoSession).where(DemoSession.id.in_(expired)))
    return len(expired)


def maybe_cleanup(engine: Engine) -> None:
    global _next_attempt
    now = monotonic()
    if now < _next_attempt or not _lock.acquire(blocking=False):
        return
    try:
        if now < _next_attempt:
            return
        settings = get_settings()
        _next_attempt = now + settings.cleanup_interval_seconds
        try:
            with Session(engine) as db, db.begin():
                count = cleanup_batch(db, settings.cleanup_batch_size)
            logger.info('{"event":"expiry_cleanup","sessions_deleted":%d}', count)
        except SQLAlchemyError:
            logger.warning('{"event":"expiry_cleanup_failed"}')
    finally:
        _lock.release()


def main() -> None:
    from fraud_api.database import get_engine

    parser = argparse.ArgumentParser(description="Delete expired demo sessions and related records")
    parser.add_argument(
        "--batch-size", type=int, default=100, choices=range(1, 1001), metavar="1..1000"
    )
    parser.add_argument("--batches", type=int, default=1, choices=range(1, 101), metavar="1..100")
    args = parser.parse_args()
    deleted = 0
    for _ in range(args.batches):
        with Session(get_engine()) as db, db.begin():
            count = cleanup_batch(db, args.batch_size)
        deleted += count
        if count < args.batch_size:
            break
    print(f"Deleted {deleted} expired sessions and their related transactions/alerts.")


if __name__ == "__main__":
    main()
