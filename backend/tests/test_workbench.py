import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from livekit import rtc

from app.agents.orchestrator import Orchestrator
from app.services.workbench import install_workbench
from app.tools.common.time import TIME_TOOL


def bridge():
    handlers = {}
    events = {}

    def register(target):
        def decorator(name):
            def wrap(callback):
                target[name] = callback
                return callback

            return wrap

        return decorator

    local = SimpleNamespace(
        register_rpc_method=register(handlers),
        unregister_rpc_method=Mock(),
        publish_data=AsyncMock(),
        set_attributes=AsyncMock(),
    )
    ctx = SimpleNamespace(
        room=SimpleNamespace(local_participant=local, on=register({})),
        add_shutdown_callback=Mock(),
    )
    session = SimpleNamespace(
        room_io=SimpleNamespace(linked_participant=SimpleNamespace(identity="user")),
        interrupt=AsyncMock(),
        aclose=AsyncMock(),
        on=register(events),
    )
    return ctx, session, handlers, events


def test_interrupt_authentication_and_real_sdk_cancellation():
    async def run():
        ctx, session, handlers, _ = bridge()
        await install_workbench(ctx, session, "en")
        handler = handlers["voice.interrupt"]
        with pytest.raises(rtc.RpcError):
            await handler(SimpleNamespace(caller_identity="untrusted"))
        session.interrupt.assert_not_awaited()
        assert (
            json.loads(await handler(SimpleNamespace(caller_identity="user")))[
                "interrupted"
            ]
            is True
        )
        session.interrupt.assert_awaited_once_with(force=True)
        session.room_io.linked_participant = None
        with pytest.raises(rtc.RpcError):
            await handler(SimpleNamespace(caller_identity="user"))
        await ctx.add_shutdown_callback.call_args.args[0]()
        ctx.room.local_participant.unregister_rpc_method.assert_called_once_with(
            "voice.interrupt"
        )

    asyncio.run(run())


def test_public_usecase_rpc_requires_linked_caller_and_has_no_private_fields():
    from app.bootstrap import build_orchestrator
    from app.config.settings import Settings

    async def run():
        settings = Settings.from_env(
            {
                "LIVEKIT_URL": "wss://example.test",
                "LIVEKIT_API_KEY": "key",
                "LIVEKIT_API_SECRET": "never-public",
                "DEEPGRAM_API_KEY": "key",
                "LLM_API_KEY": "secret-llm",
                "CARTESIA_API_KEY": "key",
                "USE_CASE": "education",
            }
        )
        orchestrator = build_orchestrator(settings)
        ctx, session, handlers, _ = bridge()
        await install_workbench(ctx, session, "en", orchestrator)
        handler = handlers["voice.usecase_config"]
        with pytest.raises(rtc.RpcError):
            await handler(SimpleNamespace(caller_identity="other"))
        raw = await handler(SimpleNamespace(caller_identity="user"))
        assert json.loads(raw)["name"] == "Study Companion"
        assert "never-public" not in raw and "secret-llm" not in raw
        assert "instructions" not in json.loads(raw)
        assert "provider" not in json.loads(raw)
        assert (
            ctx.room.local_participant.set_attributes.call_args.args[0]["voice.usecase"]
            == "education"
        )
        await ctx.add_shutdown_callback.call_args.args[0]()

    asyncio.run(run())


def test_concurrent_shutdown_flushes_history_before_exporters(monkeypatch):
    from app.observability import session as telemetry_module

    async def run():
        ctx, session, _, _ = bridge()
        callbacks, order = [], []
        ctx.add_shutdown_callback.side_effect = callbacks.append
        lock = asyncio.Lock()
        closed = False

        async def close_session():
            nonlocal closed
            async with lock:
                if not closed:
                    await asyncio.sleep(0)
                    order.append("final_history")
                    closed = True

        session.aclose = close_session
        orchestrator = Orchestrator(SimpleNamespace(tool_allowlist=()))

        async def executor_close():
            order.append("tools_closed")

        async def mcp_close():
            order.append("mcp_closed")

        async def persistence_close():
            order.append("persistence_flushed")

        orchestrator.executor.close = executor_close
        orchestrator.external_tools = SimpleNamespace(aclose=mcp_close)
        orchestrator.close_infrastructure = persistence_close
        fake = SimpleNamespace(
            session_id="test",
            request_id="job",
            provider=object(),
            event=Mock(),
            close=lambda: order.append("exporter_closed"),
        )
        monkeypatch.setattr(telemetry_module, "Telemetry", lambda *a, **k: fake)
        monkeypatch.setattr(telemetry_module, "set_tracer_provider", Mock())
        telemetry_module.install_observability(
            ctx, session, orchestrator, SimpleNamespace()
        )
        await install_workbench(ctx, session, "en", orchestrator)
        await asyncio.gather(*(callback() for callback in callbacks))
        assert order == [
            "final_history",
            "tools_closed",
            "mcp_closed",
            "persistence_flushed",
            "exporter_closed",
        ]

    asyncio.run(run())


def test_real_tool_events_are_sanitized_and_targeted():
    async def run():
        ctx, session, _, events = bridge()
        await install_workbench(ctx, session, "en")
        events["tool_execution_updated"](
            SimpleNamespace(
                update=SimpleNamespace(
                    type="tool_call_started",
                    function_call=SimpleNamespace(
                        call_id="call-1", name="lookup", arguments="secret"
                    ),
                )
            )
        )
        await asyncio.sleep(0)
        events["tool_execution_updated"](
            SimpleNamespace(
                update=SimpleNamespace(
                    type="tool_call_ended",
                    call_id="call-1",
                    status="done",
                    message="secret",
                )
            )
        )
        await asyncio.sleep(0)
        calls = ctx.room.local_participant.publish_data.call_args_list
        assert [json.loads(c.args[0])["status"] for c in calls] == ["running", "done"]
        assert all(c.kwargs["destination_identities"] == ["user"] for c in calls)
        assert all("secret" not in c.args[0] for c in calls)
        await ctx.add_shutdown_callback.call_args.args[0]()

    asyncio.run(run())


def test_only_actual_interrupted_items_emit_interruption():
    async def run():
        ctx, session, _, events = bridge()
        await install_workbench(ctx, session, "en")
        events["conversation_item_added"](
            SimpleNamespace(item=SimpleNamespace(interrupted=False))
        )
        await asyncio.sleep(0)
        ctx.room.local_participant.publish_data.assert_not_awaited()
        events["conversation_item_added"](
            SimpleNamespace(item=SimpleNamespace(interrupted=True))
        )
        await asyncio.sleep(0)
        assert json.loads(
            ctx.room.local_participant.publish_data.call_args.args[0]
        ) == {"type": "interrupted"}
        await ctx.add_shutdown_callback.call_args.args[0]()

    asyncio.run(run())


def test_confirmation_rpc_is_linked_human_only_and_rejects_replay():
    async def run():
        ctx, session, handlers, _ = bridge()
        orchestrator = Orchestrator(SimpleNamespace(tool_allowlist=(TIME_TOOL.name,)))
        orchestrator.registry.remove(TIME_TOOL.name)
        orchestrator.registry.register(
            replace(
                TIME_TOOL,
                sensitive=True,
                confirmation_summary=lambda _: "Read the current time",
            )
        )
        await install_workbench(ctx, session, "en", orchestrator)
        pending = asyncio.create_task(
            orchestrator.executor.execute(TIME_TOOL.name, {}, call_id="rpc")
        )
        for _ in range(20):
            await asyncio.sleep(0)
            if orchestrator.executor.confirmations.pending:
                break
        token = next(iter(orchestrator.executor.confirmations.pending))
        snapshot = await handlers["voice.tools_state"](
            SimpleNamespace(caller_identity="user")
        )
        assert json.loads(snapshot)[-1]["name"] == "Check current time"
        payload = json.dumps({"confirmation_id": token, "approved": False})
        for caller, body in [
            ("attacker", payload),
            ("user", '{"approved":"true"}'),
            ("user", "x" * 513),
        ]:
            with pytest.raises(rtc.RpcError):
                await handlers["voice.confirm_tool"](
                    SimpleNamespace(caller_identity=caller, payload=body)
                )
        await handlers["voice.confirm_tool"](
            SimpleNamespace(caller_identity="user", payload=payload)
        )
        assert (await pending).code == "confirmation_denied"
        with pytest.raises(rtc.RpcError):
            await handlers["voice.confirm_tool"](
                SimpleNamespace(caller_identity="user", payload=payload)
            )
        await ctx.add_shutdown_callback.call_args.args[0]()

    asyncio.run(run())
