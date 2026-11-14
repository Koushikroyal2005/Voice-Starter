"""Local approvals, pinned schemas and disclosure. Server annotations grant nothing."""

import copy
import json

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ConfigDict, model_validator

from app.mcp.config import Policy
from app.tools.base import Schema, ToolFailure


def check_schema(schema: dict) -> None:
    def visit(value):
        if isinstance(value, dict):
            if any(k in value for k in ("$id", "$dynamicRef", "$dynamicAnchor")):
                raise ValueError("Dynamic/external schema references are not allowed")
            if "$ref" in value and not str(value["$ref"]).startswith("#/"):
                raise ValueError("Only local schema references are permitted")
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    if len(json.dumps(schema)) > 16384:
        raise ValueError("Schema exceeds limit")
    visit(schema)
    Draft202012Validator.check_schema(schema)


def validate_json(value, schema: dict) -> None:
    try:
        if len(json.dumps(value, allow_nan=False).encode()) > 16384:
            raise ValueError
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    except Exception:
        raise ToolFailure(
            "mcp_schema_invalid",
            "External tool data did not match the reviewed schema.",
        ) from None


def argument_model(policy: Policy) -> type[Schema]:
    reviewed = copy.deepcopy(policy.input_schema)
    reviewed["additionalProperties"] = False
    if policy.idempotency_argument:
        reviewed["properties"].pop(policy.idempotency_argument)
        reviewed["required"] = [
            name
            for name in reviewed.get("required", [])
            if name != policy.idempotency_argument
        ]

    class ApprovedArguments(Schema):
        model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)

        @model_validator(mode="before")
        @classmethod
        def approved_schema(cls, value):
            try:
                validate_json(value, reviewed)
            except ToolFailure:
                raise ValueError(
                    "Arguments do not match the approved external tool schema"
                ) from None
            return value

        @classmethod
        def model_json_schema(cls, *args, **kwargs):
            return copy.deepcopy(reviewed)

    return ApprovedArguments


def matches_schema(remote: dict, pinned: dict) -> bool:
    return remote == pinned  # Fail closed on drift, including new fields/descriptions.
