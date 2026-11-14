"""Explicit migrations; environment URL never written to Alembic config/logs."""

import asyncio
import os

from alembic import context
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from app.config.settings import ENV_FILE
from app.database.models import Base

load_dotenv(ENV_FILE, override=False)
url = context.config.attributes.get("database_url") or os.environ.get("DATABASE_URL")
if not url:
    raise RuntimeError("DATABASE_URL is required for migrations")


def migrate(connection):
    context.configure(
        connection=connection, target_metadata=Base.metadata, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


async def online():
    engine = create_async_engine(url, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
