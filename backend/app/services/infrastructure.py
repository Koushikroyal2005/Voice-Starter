"""Bounded, serialized persistence of actual SDK events, independent of UI delivery."""

import asyncio
import logging
import os

from sqlalchemy import text

from app.cache.rate_limiter import RateLimiter
from app.cache.redis_client import create_redis
from app.cache.session_cache import SessionCache
from app.config.infrastructure import InfrastructureSettings
from app.database.connection import Database
from app.services.conversation_service import ConversationService
from app.services.transcript_service import Redactor

logger = logging.getLogger("voice-starter.infrastructure")


async def install_infrastructure(ctx, session, orchestrator, settings):
    config = getattr(settings, "infrastructure", InfrastructureSettings())
    if not config.persistence_enabled and not config.redis_enabled:
        return
    secrets = [
        value
        for key, value in os.environ.items()
        if any(
            marker in key for marker in ("KEY", "SECRET", "TOKEN", "PASSWORD", "_URL")
        )
    ]
    redactor = Redactor(config.redaction_key, secrets)
    database = Database(config.database_url) if config.persistence_enabled else None
    client = create_redis(config)
    try:
        if database:
            async with database.transaction() as db_session:
                # Do not automatically create or alter schemas in workers.
                revision = await db_session.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
                if revision != "0001_voice":
                    raise RuntimeError("Migration required")
        if config.rate_limit:
            await client.ping()
    except Exception:
        if database:
            await database.close()
        if client:
            await client.aclose()
        raise RuntimeError(
            "Infrastructure unavailable: check connection settings and run "
            "uv run alembic upgrade head (no credentials logged)"
        ) from None

    service = ConversationService(database, redactor, config.transcripts_enabled)
    cache = SessionCache(client, config.cache_ttl)
    limiter = RateLimiter(client, config.rate_limit, config.rate_window)
    queue = asyncio.Queue(maxsize=256)
    owner = None
    closing = False
    conversation_id = orchestrator.state.conversation_id

    def enqueue(kind, data=None):
        if closing:
            return
        try:
            queue.put_nowait((kind, data))
        except asyncio.QueueFull:
            logger.error("Persistence queue full; an event was not stored")

    def bind_owner():
        nonlocal owner
        participant = session.room_io.linked_participant
        if participant is None:
            return False
        candidate = redactor.owner_key(config.owner_namespace, participant.identity)
        if owner is not None and candidate != owner:
            return False  # Never transfer durable records to a replacement user.
        if owner is None:
            owner = candidate
            enqueue("start")
        return True

    async def write():
        while True:
            kind, data = await queue.get()
            try:
                if database:
                    await service.apply(owner, conversation_id, kind, data)
                if kind in {"start", "close"}:
                    await cache.put(
                        owner,
                        conversation_id,
                        "active" if kind == "start" else "closed",
                    )
            except Exception:
                # No exception text: drivers may contain connection/statement details.
                logger.error("Persistence write failed; event was not stored")
            finally:
                queue.task_done()

    worker = asyncio.create_task(write())

    def on_tool(event):
        if event.get("type") == "tool" and bind_owner():
            enqueue("tool", {key: event[key] for key in ("id", "name", "status")})

    orchestrator.event_listeners.append(on_tool)

    @session.on("conversation_item_added")
    def on_item(event):
        item = event.item
        if (
            config.transcripts_enabled
            and item.role in {"user", "assistant"}
            and bind_owner()
        ):
            enqueue(
                "turn",
                {
                    "id": item.id,
                    "role": item.role,
                    "text": redactor.text(item.text_content or ""),
                },
            )

    @ctx.room.on("participant_connected")
    def on_participant(_participant):
        bind_owner()

    async def quota():
        if not bind_owner():
            from app.tools.base import ToolFailure

            raise ToolFailure("unauthorized", "Session owner unavailable")
        await limiter.check(owner)

    orchestrator.executor.rate_limit_check = quota if config.rate_limit else None
    bind_owner()

    async def close():
        nonlocal closing
        if closing:
            return
        if owner:
            enqueue("close")
        closing = True
        try:
            await asyncio.wait_for(queue.join(), timeout=10)
        except TimeoutError:
            logger.error("Persistence flush timed out; some events may be lost")
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            if database:
                await database.close()
            if client:
                await client.aclose()

    orchestrator.close_infrastructure = close
