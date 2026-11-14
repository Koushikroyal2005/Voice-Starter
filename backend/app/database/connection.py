"""A session/transaction per operation, never shared across concurrent tasks."""

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class Database:
    def __init__(self, url: str):
        options = {}
        if url.startswith("postgresql+asyncpg:"):
            options["connect_args"] = {"timeout": 5, "command_timeout": 5}
        self.engine = create_async_engine(
            url, pool_pre_ping=True, echo=False, hide_parameters=True, **options
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def transaction(self):
        async with self.sessions.begin() as session:
            yield session

    async def close(self):
        await self.engine.dispose()
