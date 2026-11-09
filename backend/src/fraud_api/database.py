from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from fraud_api.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=5,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 5,
            "options": "-c statement_timeout=5000 -c lock_timeout=3000",
        },
    )


def get_db() -> Iterator[Session]:
    from fraud_api.cleanup import maybe_cleanup

    engine = get_engine()
    maybe_cleanup(engine)
    with Session(engine) as session:
        yield session
