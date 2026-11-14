"""Characterize public presentation independently from execution outcomes."""

import asyncio
import json
from dataclasses import replace
from unittest.mock import Mock

import pytest

from app.agents.conversation import ConversationState
from app.tools.base import PublicCard, Schema, ToolDefinition, ToolFailure
from app.tools.executor import ToolExecutor
from app.tools.presentation import present_result
from app.tools.registry import ToolRegistry
from app.workbench.contracts import encode_event


class Empty(Schema):
    pass


class Output(Schema):
    public_value: str = "Reviewed result"
    private_value: str = "private-output-not-for-browser"


async def handler(_args, _context):
    return Output()


DEFINITION = ToolDefinition(
    "presentation_test",
    "Reviewed title",
    "Test-only action",
    Empty,
    Output,
    handler,
    public_result=lambda output: output.public_value,
)


def runtime(definition, approve=True):
    registry = ToolRegistry()
    registry.register(definition)
    events = []

    def emit(event):
        events.append(event)
        if event.get("status") == "confirmation_required":
            executor.confirmations.resolve(event["confirmation_id"], "human", approve)

    executor = ToolExecutor(
        registry,
        ConversationState("conversation", actor_id="human"),
        frozenset({definition.name}),
        emit,
    )
    return executor, events


def raises_private_error(_output):
    raise RuntimeError("private-formatting-error-with-credential")


def bad_card(kind):
    if kind == "unapproved":
        return lambda _: PublicCard(
            card_type="not_approved", data={"secret": "private"}
        )
    if kind == "oversized":
        return lambda _: PublicCard(card_type="text", data={"large": "x" * 12000})
    if kind == "not_json":
        return lambda _: PublicCard(card_type="text", data={"object": object()})
    if kind == "nan":
        return lambda _: PublicCard(card_type="text", data={"number": float("nan")})
    return raises_private_error


@pytest.mark.parametrize("kind", ["unapproved", "oversized", "not_json", "exception"])
def test_bad_public_card_does_not_change_success_or_expose_private_output(kind, caplog):
    async def check():
        executor, events = runtime(replace(DEFINITION, public_card=bad_card(kind)))
        result = await executor.execute(DEFINITION.name, {}, call_id="result")
        assert result.status == "completed"
        assert result.data["private_value"] == "private-output-not-for-browser"
        assert not any(event["type"] == "result" for event in events)
        assert [event["status"] for event in events] == [
            "selected",
            "running",
            "completed",
        ]
        assert "private-output-not-for-browser" not in json.dumps(events)
        await executor.close()

    asyncio.run(check())
    assert [record.getMessage() for record in caplog.records] == [
        "Tool public result unavailable"
    ]
    assert all(record.exc_info is None for record in caplog.records)
    assert "private-formatting-error" not in caplog.text


@pytest.mark.parametrize(
    "formatter", [raises_private_error, lambda _: None, lambda _: 123]
)
def test_bad_summary_does_not_change_success(formatter):
    async def check():
        executor, events = runtime(replace(DEFINITION, public_result=formatter))
        assert (
            await executor.execute(DEFINITION.name, {}, call_id="result")
        ).status == "completed"
        assert not any(event["type"] == "result" for event in events)
        await executor.close()

    asyncio.run(check())


def test_public_result_wire_shape_and_private_output_are_separate():
    async def check():
        executor, events = runtime(DEFINITION)
        result = await executor.execute(DEFINITION.name, {}, call_id="result")
        expected = {
            "type": "result",
            "id": "result",
            "title": "Reviewed title",
            "text": "Reviewed result",
        }
        assert events[-1] == expected
        assert json.loads(encode_event(events[-1])) == expected
        assert result.data["private_value"] not in json.dumps(events)
        await executor.close()

    asyncio.run(check())


def test_pydantic_public_card_normalizes_nan_to_json_null():
    async def check():
        executor, events = runtime(replace(DEFINITION, public_card=bad_card("nan")))
        result = await executor.execute(DEFINITION.name, {}, call_id="nan")
        assert result.status == "completed"
        assert events[-1]["data"] == {"number": None}
        encode_event(events[-1])
        await executor.close()

    asyncio.run(check())


@pytest.mark.parametrize("with_card", [False, True])
def test_private_only_tools_never_publish_result_events(with_card):
    async def check():
        card = Mock(return_value=PublicCard(card_type="text", data={"private": "data"}))
        executor, events = runtime(
            replace(
                DEFINITION, public_result=None, public_card=card if with_card else None
            )
        )
        assert (
            await executor.execute(DEFINITION.name, {}, call_id="result")
        ).status == "completed"
        assert not any(event["type"] == "result" for event in events)
        card.assert_not_called()
        await executor.close()

    asyncio.run(check())


def test_approved_card_and_blank_display_title_preserve_existing_values():
    async def check():
        executor, events = runtime(
            replace(
                DEFINITION,
                title="",
                description="",
                public_card=lambda _: PublicCard(
                    card_type="text", data={"safe": "value"}
                ),
            )
        )
        await executor.execute(DEFINITION.name, {}, call_id="result")
        assert events[-1] == {
            "type": "result",
            "id": "result",
            "title": "",
            "text": "Reviewed result",
            "card_type": "text",
            "data": {"safe": "value"},
        }
        encode_event(events[-1])
        await executor.close()

    asyncio.run(check())


def test_summary_truncation_and_ascii_escaped_unicode_budget():
    async def check():
        executor, events = runtime(
            replace(DEFINITION, public_result=lambda _: "x" * 5000)
        )
        await executor.execute(DEFINITION.name, {}, call_id="result")
        assert events[-1]["text"] == "x" * 4000
        await executor.close()
        executor, events = runtime(
            replace(DEFINITION, public_result=lambda _: "😀" * 1000)
        )
        await executor.execute(DEFINITION.name, {}, call_id="unicode")
        assert not any(event["type"] == "result" for event in events)
        await executor.close()

    asyncio.run(check())


def test_committed_test_write_with_failed_presentation_is_not_reexecuted(caplog):
    """A test-only in-memory write, not a claim of an external booking/database test."""

    async def check():
        committed = []

        async def write(_args, context):
            committed.append(context.idempotency_key)
            return Output()

        formatter = Mock(side_effect=raises_private_error)
        definition = replace(
            DEFINITION,
            handler=write,
            sensitive=True,
            side_effects=True,
            cancellation_safe=False,
            permission="demo:write",
            confirmation_summary=lambda _: "Perform one test-only write",
            public_result=formatter,
        )
        executor, events = runtime(definition)
        executor.state.permissions = frozenset({"demo:write"})
        first, duplicate = await asyncio.gather(
            executor.execute(
                definition.name, {}, call_id="first", idempotency_key="stable"
            ),
            executor.execute(
                definition.name, {}, call_id="second", idempotency_key="stable"
            ),
        )
        retry = await executor.execute(
            definition.name, {}, call_id="retry", idempotency_key="stable"
        )
        assert [first.status, duplicate.status, retry.status] == ["completed"] * 3
        assert committed == ["stable"]
        formatter.assert_called_once()
        assert len(executor.ledger.operations) == 1
        assert not any(event["type"] == "result" for event in events)
        await executor.close()

    asyncio.run(check())
    assert "private-formatting-error" not in caplog.text


@pytest.mark.parametrize("approve", [True, False])
def test_confirmation_still_precedes_execution_and_presentation(approve):
    async def check():
        formatter = Mock(return_value="Reviewed")
        definition = replace(
            DEFINITION,
            sensitive=True,
            confirmation_summary=lambda _: "Read a test value",
            public_result=formatter,
        )
        executor, events = runtime(definition, approve=approve)
        result = await executor.execute(definition.name, {}, call_id="approval")
        assert result.status == ("completed" if approve else "failed")
        assert formatter.call_count == int(approve)
        assert events[1]["status"] == "confirmation_required"
        if not approve:
            assert result.code == "confirmation_denied"
        await executor.close()

    asyncio.run(check())


def test_failed_operation_never_formats_its_private_exception():
    async def check():
        async def fail(_args, _context):
            raise ToolFailure("test_failure", "Reviewed domain failure")

        formatter = Mock(return_value="Should not run")
        executor, events = runtime(
            replace(DEFINITION, handler=fail, public_result=formatter)
        )
        result = await executor.execute(DEFINITION.name, {}, call_id="failure")
        assert result.status == "failed" and result.code == "test_failure"
        formatter.assert_not_called()
        assert not any(event["type"] == "result" for event in events)
        await executor.close()

    asyncio.run(check())


# These focused tests invoke only the presenter: no event loop, ledger or agent.
def test_presenter_does_not_invoke_handler_or_infer_private_fields():
    forbidden_handler = Mock(side_effect=AssertionError("Must not execute"))
    definition = replace(DEFINITION, handler=forbidden_handler)
    output = Output()
    event = present_result(definition, output, "direct", frozenset({"text"}))
    assert event == {
        "type": "result",
        "id": "direct",
        "title": "Reviewed title",
        "text": output.public_value,
    }
    assert "private_value" not in event and "data" not in event
    forbidden_handler.assert_not_called()
    assert json.loads(encode_event(event)) == event


def test_presenter_without_summary_does_not_evaluate_card():
    card = Mock(side_effect=AssertionError("Must not disclose"))
    assert (
        present_result(
            replace(DEFINITION, public_result=None, public_card=card),
            Output(),
            "private",
            frozenset({"text"}),
        )
        is None
    )
    card.assert_not_called()


@pytest.mark.parametrize(
    "approved", [frozenset(), frozenset({"text"}), frozenset({"study_plan"})]
)
def test_presenter_card_allowlist_is_supplied_not_inferred(approved):
    definition = replace(
        DEFINITION,
        public_card=lambda _: PublicCard(card_type="study_plan", data={"safe": 1}),
    )
    event = present_result(definition, Output(), "card", approved)
    if "study_plan" not in approved:
        assert event is None
    else:
        assert event["card_type"] == "study_plan" and event["data"] == {"safe": 1}
        encode_event(event)


@pytest.mark.parametrize("extra", [0, 1])
def test_presenter_preserves_exact_12000_byte_boundary(extra):
    baseline = {
        "type": "result",
        "id": "size",
        "title": DEFINITION.title,
        "text": "safe",
        "card_type": "text",
        "data": {"value": ""},
    }
    available = 12000 - len(json.dumps(baseline, allow_nan=False).encode())
    definition = replace(
        DEFINITION,
        public_result=lambda _: "safe",
        public_card=lambda _: PublicCard(
            card_type="text", data={"value": "x" * (available + extra)}
        ),
    )
    event = present_result(definition, Output(), "size", frozenset({"text"}))
    if extra:
        assert event is None
    else:
        assert len(json.dumps(event, allow_nan=False).encode()) == 12000
        assert len(event["data"]["value"]) == available
        encode_event(event)


@pytest.mark.parametrize("summary", ["x" * 6000, "é" * 1000, "😀" * 100])
def test_presenter_truncates_characters_without_changing_json_encoding(summary):
    event = present_result(
        replace(DEFINITION, public_result=lambda _: summary),
        Output(),
        "unicode",
        frozenset(),
    )
    assert event["text"] == summary[:4000]
    encode_event(event)


@pytest.mark.parametrize("kind", ["unapproved", "oversized", "not_json", "exception"])
def test_presenter_failure_is_none_and_only_logs_fixed_warning(kind, caplog):
    output = Output()
    before = output.model_dump()
    assert (
        present_result(
            replace(DEFINITION, public_card=bad_card(kind)),
            output,
            "direct",
            frozenset({"text"}),
        )
        is None
    )
    assert output.model_dump() == before
    assert [record.getMessage() for record in caplog.records] == [
        "Tool public result unavailable"
    ]
    assert all(record.exc_info is None for record in caplog.records)
    assert "private-output-not-for-browser" not in caplog.text
    assert "private-formatting-error" not in caplog.text


def test_presenter_does_not_swallow_cancellation_as_a_formatting_failure():
    def cancelled(_output):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        present_result(
            replace(DEFINITION, public_result=cancelled),
            Output(),
            "cancelled",
            frozenset(),
        )


def test_shared_boundary_remains_owner_of_wire_schema_validation():
    # A malformed call ID was previously formatted, then rejected by the bridge.
    # Do not silently add a parallel schema or change emitter behavior here.
    from app.workbench.contracts import ContractError

    event = present_result(DEFINITION, Output(), "x" * 201, frozenset())
    assert event is not None
    with pytest.raises(ContractError):
        encode_event(event)
