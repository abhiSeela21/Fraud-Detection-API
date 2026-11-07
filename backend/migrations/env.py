from alembic import context

from fraud_api.database import get_engine
from fraud_api.models import Base

if context.is_offline_mode():
    context.configure(dialect_name="postgresql", target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
else:
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
