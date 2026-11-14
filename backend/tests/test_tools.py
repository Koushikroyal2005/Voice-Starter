import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from livekit.agents import Agent
from pydantic import Field

from app.agents.conversation import ConversationState
from app.agents.orchestrator import MainAgent, Orchestrator
from app.bootstrap import build_orchestrator
from app.tools.base import Schema, ToolDefinition, ToolFailure
from app.tools.common.calculator import CALCULATOR_TOOL, calculate
from app.tools.common.time import TIME_TOOL
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.usecases.registry import registry as usecases
from app.workflows.time_calculation import WORKFLOW_TOOL


def runtime(*definitions, allowlist=None):
    registry = ToolRegistry()
    for definition in definitions:
        registry.register(definition)
    state = ConversationState("conversation", actor_id="human")
    events = []
    executor = ToolExecutor(
        registry,
        state,
        frozenset(
            allowlist if allowlist is not None else [d.name for d in definitions]
        ),
        events.append,
    )
    return executor, events


def test_quota_is_applied_only_to_new_operations():
    async def check():
        executor, _ = runtime(CALCULATOR_TOOL)
        executor.rate_limit_check = AsyncMock()
        for _ in range(2):
            result = await executor.execute(
                "calculate_expression", {"expression": "2+3"}, call_id="same-call"
            )
            assert result.status == "completed"
        executor.rate_limit_check.assert_awaited_once()
        executor.rate_limit_check.side_effect = ToolFailure("rate_limited", "Wait")
        result = await executor.execute(
            "calculate_expression", {"expression": "2+3"}, call_id="new-call"
        )
        assert result.status == "failed" and result.code == "rate_limited"
        await executor.close()

    asyncio.run(check())


def test_registry_allowlist_and_removal():
    registry = ToolRegistry()
    registry.register(TIME_TOOL)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(TIME_TOOL)
    assert registry.selected(frozenset()) == []
    assert registry.selected(frozenset({TIME_TOOL.name})) == [TIME_TOOL]
    with pytest.raises(ValueError, match="not registered"):
        registry.selected(frozenset({"unknown"}))
    registry.remove(TIME_TOOL.name)
    with pytest.raises(ValueError):
        registry.get(TIME_TOOL.name)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2+3*4", 14),
        ("(2+3)*4", 20),
        ("-5 + +2", -3),
        ("2**3", 8),
        ("7//2", 3),
        ("7%2", 1),
        ("1/4", 0.25),
    ],
)
def test_safe_arithmetic(expression, expected):
    assert calculate(expression) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('whoami')",
        "x",
        "[1][0]",
        "True+1",
        "1/0",
        "1e309",
        "10**10000",
        "2**(2**10)",
        "1<<5",
        "(1).__class__",
        "sum([1])",
        "1" * 201,
        "-" * 20 + "1",
        "(-1)**0.5",
    ],
)
def test_calculator_rejects_code_and_resource_abuse(expression):
    with pytest.raises(ToolFailure):
        calculate(expression)


def test_validation_permissions_and_selection_events():
    async def run():
        executor, events = runtime(TIME_TOOL, CALCULATOR_TOOL)
        good = await executor.execute(
            "calculate_expression", {"expression": "1+2"}, call_id="ok"
        )
        assert good.status == "completed" and good.data == {"value": 3.0}
        assert [e["status"] for e in events if e["type"] == "tool"] == [
            "selected",
            "running",
            "completed",
        ]
        assert events[0]["name"] == "Calculate expression"
        for i, args in enumerate(
            [{"expression": 3}, {"expression": "1", "extra": True}]
        ):
            assert (
                await executor.execute("calculate_expression", args, call_id=f"bad{i}")
            ).code == "invalid_arguments"
        assert (
            await executor.execute(
                "get_current_time", {"utc_offset_minutes": 1000}, call_id="offset"
            )
        ).code == "invalid_arguments"
        executor.allowlist = frozenset()
        assert (
            await executor.execute("get_current_time", {}, call_id="denied")
        ).status == "denied"
        assert (
            await executor.execute("no_such_tool", {}, call_id="unknown")
        ).code == "unsupported_tool"
        executor.allowlist = frozenset({TIME_TOOL.name})
        executor.state.permissions = frozenset()
        assert (
            await executor.execute(TIME_TOOL.name, {}, call_id="permission")
        ).status == "denied"

    asyncio.run(run())


def test_sequential_workflow_and_child_allowlist():
    async def run():
        executor, events = runtime(TIME_TOOL, CALCULATOR_TOOL, WORKFLOW_TOOL)
        result = await executor.execute(
            WORKFLOW_TOOL.name, {"expression": "6*7"}, call_id="flow"
        )
        assert result.status == "completed" and result.data["value"] == 42
        running = [e["name"] for e in events if e.get("status") == "running"]
        assert running == [
            "Time-stamped calculation",
            "Check current time",
            "Calculate expression",
        ]
        executor.allowlist = frozenset({WORKFLOW_TOOL.name, CALCULATOR_TOOL.name})
        failed = await executor.execute(
            WORKFLOW_TOOL.name, {"expression": "1"}, call_id="flow2"
        )
        assert failed.code == "workflow_step_failed"

    asyncio.run(run())


class Empty(Schema):
    pass


class Value(Schema):
    value: int = Field(ge=0)


def test_cancelling_duplicate_waiter_does_not_cancel_shared_read():
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def read(_args, _context):
            calls.append(1)
            started.set()
            await release.wait()
            return Value(value=7)

        tool = ToolDefinition(
            "shared_read", "Shared read", "Test read", Empty, Value, read
        )
        executor, events = runtime(tool)
        owner = asyncio.create_task(executor.execute(tool.name, {}, call_id="same"))
        await started.wait()
        duplicate = asyncio.create_task(executor.execute(tool.name, {}, call_id="same"))
        await asyncio.sleep(0)
        duplicate.cancel()
        with pytest.raises(asyncio.CancelledError):
            await duplicate
        assert not owner.done()
        assert not any(e.get("status") == "cancelled" for e in events)
        release.set()
        assert (await owner).data == {"value": 7} and calls == [1]
        await executor.close()

    asyncio.run(run())


def test_timeout_cancellation_failure_and_output_validation():
    async def run():
        async def slow(args, context):
            await asyncio.sleep(30)
            return Value(value=1)

        definition = ToolDefinition(
            "slow",
            "Slow action",
            "Read a value",
            Empty,
            Value,
            slow,
            timeout_seconds=0.02,
        )
        executor, _ = runtime(definition)
        assert (
            await executor.execute("slow", {}, call_id="timeout")
        ).status == "timeout"
        task = asyncio.create_task(executor.execute("slow", {}, call_id="cancel"))
        await asyncio.sleep(0.005)
        await executor.cancel_safe()
        with pytest.raises(asyncio.CancelledError):
            await task

        async def bad(args, context):
            raise RuntimeError("secret connection string")

        executor.registry.remove("slow")
        executor.registry.register(replace(definition, handler=bad))
        result = await executor.execute("slow", {}, call_id="failure")
        assert result.code == "operation_failed" and "secret" not in result.message

        async def invalid_output(args, context):
            return {"value": "not an int"}

        executor.registry.remove("slow")
        executor.registry.register(replace(definition, handler=invalid_output))
        assert (
            await executor.execute("slow", {}, call_id="output")
        ).code == "operation_failed"
        await executor.close()
        assert (
            await executor.execute("slow", {}, call_id="closed")
        ).code == "session_unavailable"

    asyncio.run(run())


async def wait_confirmation(executor):
    for _ in range(30):
        await asyncio.sleep(0)
        if executor.confirmations.pending:
            return next(iter(executor.confirmations.pending))
    raise AssertionError("No confirmation request")


def test_confirmation_identity_replay_rejection_and_idempotency():
    async def run():
        calls = []

        async def write(args, context):
            calls.append(context.idempotency_key)
            await asyncio.sleep(0.01)
            return Value(value=1)

        definition = ToolDefinition(
            "write",
            "Demo write",
            "Test-only simulated write",
            Empty,
            Value,
            write,
            sensitive=True,
            side_effects=True,
            permission="demo:write",
            cancellation_safe=False,
            confirmation_summary=lambda _: "Create one test record",
        )
        executor, events = runtime(definition)
        executor.state.permissions = frozenset({"tools:read", "demo:write"})
        assert (
            await executor.execute("write", {}, call_id="missing")
        ).code == "idempotency_required"
        first = asyncio.create_task(
            executor.execute("write", {}, call_id="first", idempotency_key="stable")
        )
        second = asyncio.create_task(
            executor.execute("write", {}, call_id="second", idempotency_key="stable")
        )
        token = await wait_confirmation(executor)
        assert calls == []
        with pytest.raises(ToolFailure):
            executor.confirmations.resolve(token, "attacker", True)
        executor.confirmations.resolve(token, "human", True)
        with pytest.raises(ToolFailure):
            executor.confirmations.resolve(token, "human", True)
        assert all(r.status == "completed" for r in await asyncio.gather(first, second))
        assert calls == ["stable"]
        assert any(e.get("status") == "confirmation_required" for e in events)
        replay = await executor.execute(
            "write", {}, call_id="retry", idempotency_key="stable"
        )
        assert replay.status == "completed" and calls == ["stable"]
        denied = asyncio.create_task(
            executor.execute(
                "write", {}, call_id="decline", idempotency_key="different"
            )
        )
        token = await wait_confirmation(executor)
        executor.confirmations.resolve(token, "human", False)
        assert (await denied).code == "confirmation_denied" and calls == ["stable"]
        executor.confirmations.timeout = 0.01
        expired = await executor.execute(
            "write", {}, call_id="expire", idempotency_key="expire"
        )
        assert expired.code == "confirmation_expired" and calls == ["stable"]

    asyncio.run(run())


def test_idempotency_conflict_revocation_and_non_cancellable_write():
    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        async def write(args, context):
            started.set()
            await release.wait()
            return Value(value=args.value)

        definition = ToolDefinition(
            "write",
            "Reviewed operation",
            "Test only",
            Value,
            Value,
            write,
            sensitive=True,
            side_effects=True,
            permission="demo:write",
            cancellation_safe=False,
            confirmation_summary=lambda args: f"Use value {args.value}",
        )
        executor, _ = runtime(definition)
        executor.state.permissions = frozenset({"tools:read", "demo:write"})
        waiting = asyncio.create_task(
            executor.execute("write", {"value": 1}, call_id="1", idempotency_key="key")
        )
        token = await wait_confirmation(executor)
        conflict = await executor.execute(
            "write", {"value": 2}, call_id="2", idempotency_key="key"
        )
        assert conflict.code == "idempotency_conflict"
        executor.confirmations.resolve(token, "human", True)
        await started.wait()
        await executor.cancel_safe()
        assert executor.running_writes and not waiting.done()
        release.set()
        assert (await waiting).status == "completed"
        revoked = asyncio.create_task(
            executor.execute("write", {"value": 1}, call_id="3", idempotency_key="new")
        )
        token = await wait_confirmation(executor)
        executor.state.permissions = frozenset()
        executor.confirmations.resolve(token, "human", True)
        assert (await revoked).code == "permission_denied"

    asyncio.run(run())


def test_actual_livekit_registration_adapter_interruption_and_removal():
    async def run():
        settings = SimpleNamespace(
            tool_allowlist=(TIME_TOOL.name, CALCULATOR_TOOL.name, WORKFLOW_TOOL.name),
            instructions="Test",
        )
        orchestrator = build_orchestrator(settings)
        orchestrator.state.actor_id = "human"
        agent = MainAgent(settings, orchestrator)
        assert isinstance(agent, Agent)
        tool = next(t for t in orchestrator.tools() if t.id == CALCULATOR_TOOL.name)
        assert tool.info.raw_schema["parameters"]["additionalProperties"] is False

        async def wait(tasks):
            await asyncio.gather(*tasks)

        handle = SimpleNamespace(interrupted=False, wait_if_not_interrupted=wait)
        context = SimpleNamespace(
            function_call=SimpleNamespace(call_id="native"), speech_handle=handle
        )
        result = await tool({"expression": "3*4"}, context)
        assert result["data"]["value"] == 12
        handle.interrupted = True
        context.function_call.call_id = "interrupted"
        assert await tool({"expression": "3*4"}, context) is None
        mock_agent = SimpleNamespace(update_tools=AsyncMock())
        await orchestrator.remove(mock_agent, TIME_TOOL.name)
        assert TIME_TOOL.name not in [t.id for t in orchestrator.tools()]
        mock_agent.update_tools.assert_awaited_once()
        await orchestrator.register(mock_agent, TIME_TOOL)
        assert TIME_TOOL.name in [t.id for t in orchestrator.tools()]
        with pytest.raises(ValueError):
            build_orchestrator(SimpleNamespace(tool_allowlist=("unsupported",)))

    asyncio.run(run())


def test_write_timeout_is_unknown_and_never_reexecuted():
    async def run():
        calls = []

        async def write(args, context):
            calls.append(context.idempotency_key)
            await asyncio.sleep(20)
            return Value(value=1)

        definition = ToolDefinition(
            "write",
            "Test write",
            "Test-only write",
            Empty,
            Value,
            write,
            sensitive=True,
            side_effects=True,
            cancellation_safe=False,
            permission="demo:write",
            timeout_seconds=0.01,
            confirmation_summary=lambda _: "Perform test write",
        )
        executor, _ = runtime(definition)
        executor.state.permissions = frozenset({"demo:write"})
        task = asyncio.create_task(
            executor.execute("write", {}, call_id="1", idempotency_key="key")
        )
        token = await wait_confirmation(executor)
        executor.confirmations.resolve(token, "human", True)
        assert (await task).status == "unknown"
        assert (
            await executor.execute("write", {}, call_id="retry", idempotency_key="key")
        ).status == "unknown"
        assert calls == ["key"]

    asyncio.run(run())


def test_closing_session_revokes_pending_approval_and_capacity_is_bounded():
    async def run():
        sensitive = replace(
            TIME_TOOL,
            sensitive=True,
            confirmation_summary=lambda _: "Read current time",
        )
        executor, _ = runtime(sensitive)
        pending = asyncio.create_task(
            executor.execute(sensitive.name, {}, call_id="pending")
        )
        token = await wait_confirmation(executor)
        await executor.close()
        with pytest.raises(asyncio.CancelledError):
            await pending
        with pytest.raises(ToolFailure):
            executor.confirmations.resolve(token, "human", True)
        executor, _ = runtime(TIME_TOOL)
        executor.ledger.limit = 1
        assert (
            await executor.execute(TIME_TOOL.name, {}, call_id="one")
        ).status == "completed"
        assert (
            await executor.execute(TIME_TOOL.name, {}, call_id="two")
        ).code == "operation_limit"

    asyncio.run(run())


def test_registration_requires_explicit_policy_and_supports_app_composition():
    with pytest.raises(ValueError):
        replace(TIME_TOOL, side_effects=True)
    with pytest.raises(ValueError):
        replace(TIME_TOOL, sensitive=True)
    extra = replace(TIME_TOOL, name="use_case_time", title="Use-case clock")
    orchestrator = Orchestrator(
        use_case=usecases.get(),
        tool_definitions=(extra,),
        allowlist=frozenset({extra.name}),
    )
    assert [t.id for t in orchestrator.tools()] == [extra.name]


def test_removing_a_tool_while_confirmation_is_pending_prevents_execution():
    async def run():
        sensitive = replace(
            TIME_TOOL, sensitive=True, confirmation_summary=lambda _: "Read clock"
        )
        executor, _ = runtime(sensitive)
        task = asyncio.create_task(
            executor.execute(sensitive.name, {}, call_id="removed")
        )
        token = await wait_confirmation(executor)
        executor.registry.remove(sensitive.name)
        executor.confirmations.resolve(token, "human", True)
        assert (await task).status == "failed"

    asyncio.run(run())


def test_native_adapter_stops_inflight_read_on_speech_interruption():
    async def run():
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def read(args, context):
            started.set()
            try:
                await asyncio.sleep(30)
                return Value(value=1)
            finally:
                cancelled.set()

        definition = ToolDefinition(
            "read_slow", "Read test value", "Test read", Empty, Value, read
        )
        orchestrator = Orchestrator(
            use_case=usecases.get(),
            tool_definitions=(definition,),
            allowlist=frozenset({definition.name}),
        )
        orchestrator.state.actor_id = "human"

        async def wait(tasks):
            await started.wait()

        context = SimpleNamespace(
            function_call=SimpleNamespace(call_id="interruption"),
            speech_handle=SimpleNamespace(
                interrupted=True, wait_if_not_interrupted=wait
            ),
        )
        tool = orchestrator.tools()[0]
        assert await tool({}, context) is None
        assert cancelled.is_set()
        assert all(
            op.task.done() for op in orchestrator.executor.ledger.operations.values()
        )

    asyncio.run(run())


def test_cancelled_caller_cannot_cancel_or_duplicate_running_write():
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def write(args, context):
            calls.append(context.idempotency_key)
            started.set()
            await release.wait()
            return Value(value=1)

        definition = ToolDefinition(
            "write",
            "Test write",
            "Test only",
            Empty,
            Value,
            write,
            sensitive=True,
            side_effects=True,
            cancellation_safe=False,
            permission="demo:write",
            confirmation_summary=lambda _: "Perform one test write",
        )
        executor, _ = runtime(definition)
        executor.state.permissions = frozenset({"demo:write"})
        first = asyncio.create_task(
            executor.execute("write", {}, call_id="first", idempotency_key="key")
        )
        token = await wait_confirmation(executor)
        executor.confirmations.resolve(token, "human", True)
        await started.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert executor.running_writes
        retry = asyncio.create_task(
            executor.execute("write", {}, call_id="retry", idempotency_key="key")
        )
        release.set()
        assert (await retry).status == "completed" and calls == ["key"]

    asyncio.run(run())
