import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from livekit import rtc
from test_workbench import bridge

from app.bootstrap import build_orchestrator
from app.services.workbench import install_workbench
from app.workbench.contracts import (
    CONTRACT_ROOT,
    ContractError,
    _registry,
    _schemas,
    encode_event,
    encode_response,
    parse_request,
    validation_error,
)

CORPUS = json.loads((CONTRACT_ROOT / "fixtures.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("event", CORPUS["events"])
def test_python_validates_actual_serialized_event_corpus(event):
    assert json.loads(encode_event(event)) == event


@pytest.mark.parametrize("call", CORPUS["rpc"])
def test_every_rpc_request_and_response_corpus(call):
    assert parse_request(call["method"], json.dumps(call["request"])) == call["request"]
    assert (
        json.loads(encode_response(call["method"], call["response"]))
        == call["response"]
    )


@pytest.mark.parametrize("error", CORPUS["errors"])
def test_livekit_error_corpus_matches_schema(error):
    validator = Draft202012Validator(
        {"$ref": _schemas["rpc"]["$id"] + "#/$defs/rpcError"},
        registry=_registry,
    )
    validator.validate(error)
    assert "must-not-appear" not in json.dumps(error)


def test_real_producers_and_rpc_handlers_match_checked_in_corpus():
    pytest.importorskip("mcp")
    from export_workbench_fixtures import collect

    assert asyncio.run(collect()) == CORPUS
    assert {event["type"] for event in CORPUS["events"]} == {
        "tool",
        "result",
        "error",
        "interrupted",
    }
    assert {call["method"] for call in CORPUS["rpc"]} == {
        "voice.interrupt",
        "voice.confirm_tool",
        "voice.tools_state",
        "voice.usecase_config",
    }
    assert {
        event["status"] for event in CORPUS["events"] if event["type"] == "tool"
    } == {
        "selected",
        "running",
        "completed",
        "failed",
        "confirmation_required",
        "unknown",
        "cancelled",
        "done",
        "error",
    }


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"type": "unknown"},
        {"type": "interrupted", "private": "must-not-appear"},
        {"type": "error", "code": "unknown"},
        {
            "type": "tool",
            "id": "1",
            "name": "Action",
            "status": "confirmation_required",
        },
        {
            "type": "tool",
            "id": "1",
            "name": "Action",
            "status": "running",
            "revision": -1,
        },
        {
            "type": "tool",
            "id": "1",
            "name": "Action",
            "status": "running",
            "revision": True,
        },
        {
            "type": "tool",
            "id": "1",
            "name": "Action",
            "status": "running",
            "revision": 9007199254740992,
        },
        {"type": "result", "id": "1", "title": "Result", "text": "ok", "data": []},
        {
            "type": "result",
            "id": "1",
            "title": "Result",
            "text": "ok",
            "card_type": "../invalid",
        },
    ],
)
def test_invalid_outgoing_events_are_rejected_without_values(payload):
    with pytest.raises(ContractError) as error:
        encode_event(payload)
    assert str(error.value) == "Invalid workbench payload"


@pytest.mark.parametrize(
    "method,body",
    [
        ("voice.interrupt", "null"),
        ("voice.tools_state", "[]"),
        ("voice.usecase_config", '{"extra":1}'),
        ("voice.interrupt", "{"),
        ("voice.confirm_tool", '{"confirmation_id":"x","approved":"true"}'),
        ("voice.confirm_tool", '{"approved":true}'),
        ("voice.confirm_tool", '{"confirmation_id":"x","approved":true,"extra":1}'),
        ("voice.interrupt", '{"x":NaN}'),
        ("unknown", "{}"),
    ],
)
def test_invalid_requests_and_unknown_methods(method, body):
    with pytest.raises(ContractError):
        parse_request(method, body)


def test_versions_limits_unicode_and_optional_fields():
    assert json.loads(encode_event({"type": "interrupted"})) == {"type": "interrupted"}
    assert json.loads(
        encode_event({"type": "error", "code": "provider_unavailable", "revision": 1})
    )
    with pytest.raises(ContractError):
        encode_event(
            {"type": "result", "id": "1", "title": "Result", "text": "x" * 17000}
        )
    public = deepcopy(
        next(
            c["response"]
            for c in CORPUS["rpc"]
            if c["method"] == "voice.usecase_config"
        )
    )
    public["name"] = "😀" * 80
    assert (
        json.loads(encode_response("voice.usecase_config", public))["name"]
        == public["name"]
    )
    public["schema_version"] = 2
    with pytest.raises(ContractError):
        encode_response("voice.usecase_config", public)
    for method, value in (
        ("voice.confirm_tool", {"accepted": False}),
        ("voice.interrupt", {"interrupted": False}),
        ("unknown", {}),
    ):
        with pytest.raises(ContractError):
            encode_response(method, value)


def test_validation_error_serialization_never_exposes_input():
    error = validation_error("voice.confirm_tool")
    proto = error._to_proto()
    assert proto.code == 2002
    assert json.loads(proto.data) == {
        "code": "invalid_request",
        "method": "voice.confirm_tool",
    }
    assert rtc.RpcError._from_proto(proto).message == error.message


def test_all_event_required_fields_and_non_json_values():
    required = {
        "tool": _schemas["events"]["$defs"]["toolFields"]["required"],
        **{
            kind: _schemas["events"]["$defs"][kind + "Event"]["required"]
            for kind in ("result", "error", "interrupted")
        },
    }
    for kind, fields in required.items():
        sample = next(event for event in CORPUS["events"] if event["type"] == kind)
        for field in fields:
            changed = {key: value for key, value in sample.items() if key != field}
            with pytest.raises(ContractError):
                encode_event(changed)
    for text in ("\ud800", float("nan")):
        with pytest.raises(ContractError):
            encode_event(
                {"type": "result", "id": "bad", "title": "Result", "text": text}
            )


def test_boundary_drops_invalid_events_and_auth_precedes_validation(caplog):
    async def check():
        ctx, session, handlers, _ = bridge()
        runtime = build_orchestrator(SimpleNamespace(tool_allowlist=()))
        await install_workbench(ctx, session, "en", runtime)
        try:
            runtime.emit({"type": "unknown", "private": "must-not-appear"})
            await asyncio.sleep(0)
            ctx.room.local_participant.publish_data.assert_not_awaited()
            for actor, expected in (("attacker", 2001), ("user", 2005)):
                with pytest.raises(rtc.RpcError) as error:
                    await handlers["voice.interrupt"](
                        SimpleNamespace(
                            caller_identity=actor,
                            payload='{"private":"must-not-appear"}',
                        )
                    )
                assert error.value.code == expected
                assert "must-not-appear" not in str(error.value)
            session.interrupt.assert_not_awaited()
            runtime.activities["bad"] = {
                "type": "tool",
                "id": "bad",
                "name": "Action",
                "status": "invalid",
            }
            with pytest.raises(rtc.RpcError) as error:
                await handlers["voice.tools_state"](
                    SimpleNamespace(caller_identity="user", payload="{}")
                )
            assert error.value.code == 2006
            assert "must-not-appear" not in caplog.text
        finally:
            await ctx.add_shutdown_callback.call_args.args[0]()

    asyncio.run(check())
