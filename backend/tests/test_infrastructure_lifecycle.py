import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.bootstrap import build_orchestrator
from app.config.infrastructure import InfrastructureSettings
from app.database.connection import Database
from app.database.models import Conversation, ToolExecution, Turn
from app.services import infrastructure


class Emitter:
    def __init__(self):
        self.callbacks = {}

    def on(self, name):
        def register(callback):
            self.callbacks[name] = callback
            return callback

        return register


def test_real_session_events_are_persisted_and_flushed(monkeypatch, tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'lifecycle.db'}"
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")
    monkeypatch.setattr(infrastructure, "Database", lambda _: Database(url))

    async def check():
        session = Emitter()
        session.room_io = SimpleNamespace(
            linked_participant=SimpleNamespace(identity="authenticated-user")
        )
        ctx = SimpleNamespace(room=Emitter())
        settings = SimpleNamespace(
            tool_allowlist=("calculate_expression",),
            infrastructure=InfrastructureSettings(
                persistence_enabled=True,
                transcripts_enabled=True,
                redaction_key="s" * 32,
                owner_namespace="tenant",
            ),
        )
        orchestrator = build_orchestrator(settings)
        orchestrator.state.actor_id = "authenticated-user"
        await infrastructure.install_infrastructure(
            ctx, session, orchestrator, settings
        )
        session.callbacks["conversation_item_added"](
            SimpleNamespace(
                item=SimpleNamespace(
                    id="turn1", role="user", text_content="Contact user@example.com"
                )
            )
        )
        result = await orchestrator.executor.execute(
            "calculate_expression", {"expression": "2+3"}, call_id="call1"
        )
        assert result.status == "completed"
        session.room_io.linked_participant.identity = "replacement-user"
        session.callbacks["conversation_item_added"](
            SimpleNamespace(
                item=SimpleNamespace(
                    id="unauthorized", role="user", text_content="Must not be saved"
                )
            )
        )
        await orchestrator.executor.close()
        await orchestrator.close_infrastructure()
        await orchestrator.close_infrastructure()  # Idempotent resource disposal.
        db = Database(url)
        async with db.transaction() as s:
            conversation = await s.scalar(select(Conversation))
            assert conversation.status == "closed"
            assert "authenticated-user" not in conversation.owner_key
            turns = list(await s.scalars(select(Turn)))
            assert len(turns) == 1 and "user@example.com" not in turns[0].text
            tool = await s.scalar(select(ToolExecution))
            assert tool.status == "completed"
        await db.close()

    asyncio.run(check())


def test_disabled_infrastructure_never_opens_connections(monkeypatch):
    def fail(*_args):
        raise AssertionError("Must not connect")

    monkeypatch.setattr(infrastructure, "Database", fail)
    monkeypatch.setattr(infrastructure, "create_redis", fail)
    asyncio.run(
        infrastructure.install_infrastructure(
            None, None, None, SimpleNamespace(infrastructure=InfrastructureSettings())
        )
    )


def test_missing_database_fails_without_logging_secrets(monkeypatch):
    database = SimpleNamespace(close=AsyncMock())

    def unavailable():
        raise RuntimeError("postgresql://secret:password@host/db")

    database.transaction = unavailable
    monkeypatch.setattr(infrastructure, "Database", lambda _: database)
    config = InfrastructureSettings(
        persistence_enabled=True,
        database_url="secret",
        redaction_key="s" * 32,
        owner_namespace="tenant",
    )
    with pytest.raises(RuntimeError, match="Infrastructure unavailable") as error:
        asyncio.run(
            infrastructure.install_infrastructure(
                None, None, None, SimpleNamespace(infrastructure=config)
            )
        )
    assert "password" not in str(error.value)
    assert error.value.__suppress_context__
    database.close.assert_awaited_once()
