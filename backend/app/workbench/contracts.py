"""Cached, local-only v1 validation at the LiveKit messaging boundary."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from livekit import rtc
from referencing import Registry, Resource

CONTRACT_ROOT = Path(__file__).resolve().parents[3] / "contracts/voice-workbench/v1"
MAX_EVENT_BYTES = 16384

_schemas = {
    name: json.loads(
        (CONTRACT_ROOT / f"{name}.schema.json").read_text(encoding="utf-8")
    )
    for name in ("events", "rpc")
}
TOPIC = _schemas["events"]["$defs"]["topic"]["const"]
for _schema in _schemas.values():
    Draft202012Validator.check_schema(_schema)
_registry = Registry().with_resources(
    (schema["$id"], Resource.from_contents(schema)) for schema in _schemas.values()
)
_events = Draft202012Validator(_schemas["events"], registry=_registry)
_rpc = Draft202012Validator(_schemas["rpc"], registry=_registry)
_methods = {
    branch["properties"]["method"]["const"]: {
        direction: _rpc.evolve(schema=branch["properties"][direction])
        for direction in ("request", "response")
    }
    for branch in _schemas["rpc"]["oneOf"]
}


class ContractError(ValueError):
    """Never includes payload values, schema diagnostics or exception details."""

    def __init__(self):
        super().__init__("Invalid workbench payload")


def _validate(validator, value):
    try:
        if not validator.is_valid(value):
            raise ContractError
    except (RecursionError, TypeError, ValueError):
        raise ContractError from None


def _dump(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ContractError from None


def _bytes(raw):
    try:
        return len(raw.encode("utf-8"))
    except UnicodeError:
        raise ContractError from None


def encode_event(event: dict) -> str:
    _validate(_events, event)
    raw = _dump(event)
    if _bytes(raw) > MAX_EVENT_BYTES:
        raise ContractError
    return raw


def _method(method):
    if method not in _methods:
        raise ContractError
    return _methods[method]


def _invalid_constant(_value):
    raise ContractError


def parse_request(method: str, raw: str) -> dict:
    validators = _method(method)
    if not isinstance(raw, str) or len(raw) > (
        512 if method == "voice.confirm_tool" else 16384
    ):
        raise ContractError
    try:
        value = json.loads(raw, parse_constant=_invalid_constant)
    except (ValueError, TypeError, RecursionError):
        raise ContractError from None
    _validate(validators["request"], value)
    return value


def encode_response(method: str, value) -> str:
    _validate(_method(method)["response"], value)
    raw = _dump(value)
    if _bytes(raw) > (14000 if method == "voice.tools_state" else 16384):
        raise ContractError
    return raw


def validation_error(method: str, *, response=False) -> rtc.RpcError:
    """Use LiveKit's existing structured error transport, never a success envelope."""
    safe_method = method if method in _methods else "unsupported_method"
    code = 2006 if response else (2002 if method == "voice.confirm_tool" else 2005)
    message = (
        "Invalid workbench response"
        if response
        else "Confirmation is invalid, expired or already answered"
        if code == 2002
        else "Invalid workbench request"
    )
    return rtc.RpcError(
        code,
        message,
        data=json.dumps(
            {
                "code": "invalid_response" if response else "invalid_request",
                "method": safe_method,
            }
        ),
    )
