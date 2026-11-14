"""Portable transaction tests; real PostgreSQL is an explicitly opt-in contract run."""

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import inspect, select

from app.cache.rate_limiter import RateLimiter
from app.cache.session_cache import SessionCache
from app.config.infrastructure import InfrastructureSettings
from app.database.connection import Database
from app.database.models import Base, Conversation, ToolExecution
from app.database.repositories.voice import RecordUnavailable, VoiceRepository
from app.services.conversation_service import ConversationService
from app.services.transcript_service import Redactor
from app.tools.base import ToolFailure

OWNER, OTHER = "a" * 64, "b" * 64


async def repository_contract(url, create_schema=True):
    db = Database(url)
    cid = str(uuid4())
    if create_schema:
        async with db.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    service = ConversationService(db, Redactor("x" * 32, ["test-secret"]), True)
    try:
        await service.apply(OWNER, cid, "start")
        await service.apply(
            OWNER,
            cid,
            "turn",
            {"id": "turn1", "role": "user", "text": "test-secret a@example.com"},
        )
        await service.apply(
            OWNER, cid, "turn", {"id": "turn1", "role": "user", "text": "duplicate"}
        )
        for status in ("selected", "running", "completed"):
            await service.apply(
                OWNER,
                cid,
                "tool",
                {"id": "call1", "name": "Current time", "status": status},
            )
        async with db.transaction() as session:
            repo = VoiceRepository(session, OWNER)
            turns = await repo.turns(cid)
            assert len(turns) == 1
            assert turns[0].text == "[REDACTED] [REDACTED]"
            tools = list(
                await session.scalars(
                    select(ToolExecution).where(ToolExecution.conversation_id == cid)
                )
            )
            assert len(tools) == 1 and tools[0].status == "completed"
            assert len(await repo.tools(cid)) == 1
        for kind, data in (
            ("close", None),
            ("turn", {"id": "attack", "role": "user", "text": "attack"}),
        ):
            with pytest.raises(RecordUnavailable):
                await service.apply(OTHER, cid, kind, data)
        with pytest.raises(RecordUnavailable):
            async with db.transaction() as session:
                await VoiceRepository(session, OTHER).turns(cid)
        with pytest.raises(RecordUnavailable):
            async with db.transaction() as session:
                await VoiceRepository(session, OTHER).tools(cid)
        with pytest.raises(RuntimeError):
            async with db.transaction() as session:
                await VoiceRepository(session, OWNER).close(cid)
                raise RuntimeError("rollback")
        async with db.transaction() as session:
            assert (
                await VoiceRepository(session, OWNER).require(cid)
            ).status == "active"
        await service.apply(OWNER, cid, "close")
        async with db.transaction() as session:
            record = await VoiceRepository(session, OWNER).require(cid)
            assert record.ended_at is not None and record.status == "closed"
    finally:
        # Only test-owned records, no broad schema destruction on external database.
        async with db.transaction() as session:
            from sqlalchemy import delete

            from app.database.models import Turn

            await session.execute(delete(Turn).where(Turn.conversation_id == cid))
            await session.execute(
                delete(ToolExecution).where(ToolExecution.conversation_id == cid)
            )
            await session.execute(delete(Conversation).where(Conversation.id == cid))
        await db.close()


def test_repository_transactions_ownership_and_redaction(tmp_path):
    asyncio.run(repository_contract(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"))


def test_transcripts_disabled(tmp_path):
    async def check():
        db = Database(f"sqlite+aiosqlite:///{tmp_path / 'off.db'}")
        async with db.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        service = ConversationService(db, Redactor("x" * 32))
        await service.apply(OWNER, "c", "start")
        await service.apply(
            OWNER, "c", "turn", {"id": "t", "role": "user", "text": "private"}
        )
        async with db.transaction() as session:
            assert not await VoiceRepository(session, OWNER).turns("c")
        await db.close()

    asyncio.run(check())


def test_migration_upgrade_downgrade_and_model_parity(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'migrations.db'}"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    command.check(config)

    async def tables():
        db = Database(url)
        async with db.engine.connect() as connection:
            names = await connection.run_sync(lambda c: inspect(c).get_table_names())
        await db.close()
        return names

    assert set(Base.metadata.tables) <= set(asyncio.run(tables()))
    command.downgrade(config, "base")
    assert not set(Base.metadata.tables) & set(asyncio.run(tables()))
    command.upgrade(config, "head")


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="No test PostgreSQL URL")
def test_real_postgresql_contract():
    # Use a dedicated migrated test database, never a production URL.
    asyncio.run(repository_contract(os.environ["TEST_DATABASE_URL"], False))


def test_redaction_and_identity():
    redactor = Redactor("s" * 32)
    assert redactor.owner_key("tenant1", "user") != redactor.owner_key(
        "tenant2", "user"
    )
    for text in ("Bearer abc123", "api_key=abc123", "+1 202 555 0100"):
        assert redactor.text(text) == "[REDACTED]"
    with pytest.raises(PermissionError):
        redactor.owner_key("tenant", "")


@pytest.mark.parametrize(
    "env",
    [
        {"PERSIST_TRANSCRIPTS": "true"},
        {"PERSISTENCE_ENABLED": "yes"},
        {"PERSISTENCE_ENABLED": "true", "DATABASE_URL": "secret-not-a-url"},
        {"REDIS_ENABLED": "true"},
        {"TOOL_RATE_LIMIT": "1"},
        {"SESSION_CACHE_TTL_SECONDS": "0"},
        {"RATE_LIMIT_WINDOW_SECONDS": "invalid"},
    ],
)
def test_invalid_configuration(env):
    with pytest.raises(ValueError) as error:
        InfrastructureSettings.from_env(env)
    assert "secret-not-a-url" not in str(error.value)


def test_config_defaults_and_secret_repr():
    assert not InfrastructureSettings.from_env({}).persistence_enabled
    config = InfrastructureSettings.from_env(
        {
            "PERSISTENCE_ENABLED": "true",
            "DATABASE_URL": "postgresql+asyncpg://test:super-secret@localhost/db",
            "DATA_REDACTION_KEY": "x" * 32,
            "PERSISTENCE_OWNER_NAMESPACE": "demo",
        }
    )
    assert "super-secret" not in repr(config)


def test_cache_ttl_disabled_outage_and_owner_scoping():
    async def check():
        assert await SessionCache().get(OWNER, "c") is None
        client = AsyncMock()
        cache = SessionCache(client, ttl=30)
        await cache.put(OWNER, "c", "active")
        assert client.set.call_args.kwargs["ex"] == 30
        assert cache.key(OWNER, "c") != cache.key(OTHER, "c")
        with pytest.raises(ValueError):
            await cache.put(OWNER, "c", "private transcript")
        client.get.side_effect = RedisConnectionError()
        assert await cache.get(OWNER, "c") is None
        client.set.side_effect = RedisConnectionError()
        await cache.put(OWNER, "c", "active")
        with pytest.raises(ValueError):
            SessionCache(client, ttl=0)

    asyncio.run(check())


def test_rate_limit_and_outage():
    async def check():
        await RateLimiter().check(OWNER)
        client = AsyncMock()
        limiter = RateLimiter(client, limit=1, window=10)
        client.eval.side_effect = [1, 2, RedisConnectionError()]
        await limiter.check(OWNER)
        with pytest.raises(ToolFailure) as error:
            await limiter.check(OWNER)
        assert error.value.code == "rate_limited"
        with pytest.raises(ToolFailure) as error:
            await limiter.check(OWNER)
        assert error.value.code == "rate_limit_unavailable"
        assert client.eval.call_args.args[-1] == 10

    asyncio.run(check())


@pytest.mark.skipif(not os.getenv("TEST_REDIS_URL"), reason="No test Redis URL")
def test_real_redis_ttl_and_atomic_quota():
    async def check():
        from redis.asyncio import Redis

        client = Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
        owner = uuid4().hex * 2
        cid = str(uuid4())
        cache = SessionCache(client, ttl=1)
        try:
            await cache.put(owner, cid, "active")
            assert (await cache.get(owner, cid))["status"] == "active"
            limiter = RateLimiter(client, 1, 1)
            results = await asyncio.gather(
                limiter.check(owner), limiter.check(owner), return_exceptions=True
            )
            assert sum(isinstance(r, ToolFailure) for r in results) == 1
            assert 0 < await client.ttl(f"voice:quota:{owner}") <= 1
            await asyncio.sleep(1.1)
            assert await cache.get(owner, cid) is None
            await limiter.check(owner)
        finally:
            await client.delete(cache.key(owner, cid), f"voice:quota:{owner}")
            await client.aclose()

    asyncio.run(check())
