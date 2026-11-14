import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app import main


def test_session_closes_job_and_uses_client_disconnect_cleanup(monkeypatch):
    callbacks = {}

    def on(event):
        def register(callback):
            callbacks[event] = callback
            return callback

        return register

    session = SimpleNamespace(on=on, start=AsyncMock(), generate_reply=AsyncMock())
    ctx = SimpleNamespace(
        room=SimpleNamespace(name="test-room"), connect=AsyncMock(), shutdown=Mock()
    )
    monkeypatch.setattr(
        main, "load_settings", lambda: SimpleNamespace(instructions="Demo")
    )
    monkeypatch.setattr(main, "create_session", lambda _: session)
    asyncio.run(main.voice_session(ctx))
    assert session.start.call_args.kwargs["room"] is ctx.room
    assert session.start.call_args.kwargs["room_options"].close_on_disconnect is True
    ctx.connect.assert_awaited_once()
    session.generate_reply.assert_awaited_once()
    callbacks["close"](None)
    ctx.shutdown.assert_called_once_with(reason="voice_session_closed")
