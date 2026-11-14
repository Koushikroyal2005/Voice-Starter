"""Deterministic corpus through actual producers, RPC handlers and SDK errors.

Room/session IO and MCP transport are test doubles. No paid providers or room join.
Run from backend with PYTHONPATH=. (the Node fixture generator sets it).
"""

import asyncio
import json
from collections import defaultdict
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from livekit import rtc
from livekit.agents.llm import ChatMessage

from app.bootstrap import build_orchestrator
from app.config.settings import Settings
from app.observability.session import SessionObserver
from app.services.workbench import install_workbench
from app.tools.common.time import TIME_TOOL
from app.workbench.contracts import TOPIC


def config(**values):
    return Settings.from_env(
        {
            "LIVEKIT_URL": "wss://example.test",
            "LIVEKIT_API_KEY": "fixture-key",
            "LIVEKIT_API_SECRET": "fixture-secret",
            "DEEPGRAM_API_KEY": "fixture-stt",
            "LLM_API_KEY": "fixture-llm",
            "CARTESIA_API_KEY": "fixture-tts",
            **values,
        }
    )


def bridge():
    handlers, listeners = {}, defaultdict(list)

    def register(name):
        def keep(callback):
            handlers[name] = callback
            return callback

        return keep

    def on(name):
        def keep(callback):
            listeners[name].append(callback)
            return callback

        return keep

    def fire(name, event):
        for callback in listeners[name]:
            callback(event)

    local = NS(
        register_rpc_method=register,
        unregister_rpc_method=Mock(),
        publish_data=AsyncMock(),
        set_attributes=AsyncMock(),
    )
    ctx = NS(room=NS(local_participant=local, on=on), add_shutdown_callback=Mock())
    session = NS(
        on=on,
        room_io=NS(linked_participant=NS(identity="fixture-user")),
        interrupt=AsyncMock(),
        aclose=AsyncMock(),
    )
    return ctx, session, handlers, fire


async def collect():
    records = {"topic": TOPIC, "events": [], "rpc": [], "errors": []}
    ctx, session, handlers, fire = bridge()
    alias = "mcp_clock_get_current_time"
    runtime = build_orchestrator(
        config(
            MCP_ENABLED="true",
            MCP_CONFIG_FILE="mcp.demo.example.json",
            TOOL_ALLOWLIST=f"calculate_expression,get_current_time,{alias}",
        )
    )
    await install_workbench(ctx, session, "en", runtime)
    observer = SessionObserver(session, runtime, NS(event=Mock(), close=Mock()))

    async def call(method, request=None, actor="fixture-user", raw=None):
        payload = (
            json.dumps(request if request is not None else {}) if raw is None else raw
        )
        try:
            response = await handlers[method](
                NS(caller_identity=actor, payload=payload)
            )
            records["rpc"].append(
                {
                    "method": method,
                    "request": json.loads(payload),
                    "response": json.loads(response),
                }
            )
        except rtc.RpcError as error:
            # Exercise LiveKit's real error serialization, not a hand-shaped fixture.
            proto = error._to_proto()
            records["errors"].append(
                {
                    "code": proto.code,
                    "message": proto.message,
                    **({"data": proto.data} if proto.data else {}),
                }
            )

    try:
        await call("voice.usecase_config")
        await runtime.executor.execute(
            "calculate_expression", {"expression": "3*5"}, call_id="calculator"
        )
        runtime.registry.remove(TIME_TOOL.name)
        runtime.registry.register(
            replace(
                TIME_TOOL,
                sensitive=True,
                confirmation_summary=lambda _: "Read the current time?",
            )
        )
        with patch(
            "app.tools.confirmation.secrets.token_urlsafe",
            return_value="fixture-confirmation-token-123456",
        ):
            pending = asyncio.create_task(
                runtime.executor.execute(TIME_TOOL.name, {}, call_id="approval")
            )
            for _ in range(20):
                await asyncio.sleep(0)
                if runtime.executor.confirmations.pending:
                    break
            token = next(iter(runtime.executor.confirmations.pending))
            await call("voice.tools_state")
            await call(
                "voice.confirm_tool",
                {"confirmation_id": token, "approved": False},
                actor="other-user",
            )
            await call(
                "voice.confirm_tool", {"confirmation_id": token, "approved": False}
            )
            await pending
            await call(
                "voice.confirm_tool", {"confirmation_id": token, "approved": False}
            )
        await runtime.set_tool_availability(
            NS(update_tools=AsyncMock()), {alias}, {alias}
        )
        runtime.external_tools.manager.call = AsyncMock(
            return_value={"iso_time": "2026-01-01T00:00:00+00:00"}
        )
        await runtime.executor.execute(alias, {}, call_id="mcp-clock")
        for status in ("unknown", "cancelled"):
            runtime.executor.event(f"status-{status}", TIME_TOOL, status)
        fire("error", NS(error=NS(type="tts_error", recoverable=False), source=None))
        fire("user_transcription_timeout", NS())
        fire(
            "conversation_item_added",
            NS(
                item=ChatMessage(
                    id="fixture-interruption",
                    role="assistant",
                    content=[],
                    interrupted=True,
                )
            ),
        )
        await call("voice.interrupt")
        await call("voice.interrupt", raw='{"private":"must-not-appear"}')
        await call("voice.confirm_tool", raw='{"approved":"must-not-appear"}')
        runtime.executor.running_writes.add("test-only-write")
        await call("voice.interrupt")
        runtime.executor.running_writes.clear()
        session.interrupt.side_effect = TimeoutError()
        await call("voice.interrupt")
        runtime.activities["invalid"] = {
            "type": "tool",
            "id": "invalid",
            "name": "Action",
            "status": "malformed",
        }
        await call("voice.tools_state")
        await asyncio.sleep(0)
        records["events"].extend(
            json.loads(c.args[0])
            for c in ctx.room.local_participant.publish_data.call_args_list
        )
    finally:
        await ctx.add_shutdown_callback.call_args.args[0]()
        await observer.close()

    ctx, session, handlers, fire = bridge()
    education = build_orchestrator(config(USE_CASE="education"))
    await install_workbench(ctx, session, "en", education)
    try:
        await call("voice.usecase_config")
        await education.executor.execute(
            "create_study_plan", {"topic": "Fractions", "days": 2}, call_id="study-plan"
        )
        await asyncio.sleep(0)
        records["events"].extend(
            json.loads(c.args[0])
            for c in ctx.room.local_participant.publish_data.call_args_list
        )
    finally:
        await ctx.add_shutdown_callback.call_args.args[0]()

    ctx, session, handlers, fire = bridge()
    await install_workbench(ctx, session, "en")
    try:
        for status in ("done", "error"):
            fire(
                "tool_execution_updated",
                NS(
                    update=NS(
                        type="tool_call_started",
                        function_call=NS(call_id=f"native-{status}", name="native"),
                    )
                ),
            )
            fire(
                "tool_execution_updated",
                NS(
                    update=NS(
                        type="tool_call_ended",
                        call_id=f"native-{status}",
                        status=status,
                    )
                ),
            )
        await asyncio.sleep(0)
        records["events"].extend(
            json.loads(c.args[0])
            for c in ctx.room.local_participant.publish_data.call_args_list
        )
    finally:
        await ctx.add_shutdown_callback.call_args.args[0]()
    proto = rtc.RpcError._built_in(
        rtc.RpcError.ErrorCode.UNSUPPORTED_METHOD
    )._to_proto()
    records["errors"].append({"code": proto.code, "message": proto.message})
    return records


if __name__ == "__main__":
    print(json.dumps(asyncio.run(collect()), ensure_ascii=False, indent=2))
