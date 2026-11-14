"""Provider-independent contracts. No SQL, LLM or transport access in handlers."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ToolResult(Schema):
    call_id: str
    tool: str
    status: Literal["completed", "failed", "denied", "cancelled", "timeout", "unknown"]
    message: str
    data: dict[str, Any] | None = None
    code: str | None = None


class ToolFailure(Exception):
    """An intentionally public, non-sensitive domain error."""

    def __init__(self, code: str, message: str, *, outcome_unknown: bool = False):
        self.code = code
        self.message = message
        self.outcome_unknown = outcome_unknown
        super().__init__(message)


@dataclass(frozen=True)
class ExecutionContext:
    conversation_id: str
    actor_id: str
    call_id: str
    idempotency_key: str | None
    run_tool: Callable[..., Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    title: str
    description: str
    input_schema: type[Schema]
    output_schema: type[Schema]
    handler: Callable[[Any, ExecutionContext], Awaitable[BaseModel]]
    permission: str = "tools:read"
    timeout_seconds: float = 10
    sensitive: bool = False
    side_effects: bool = False
    cancellation_safe: bool = True
    # Must be an explicit safe summary: do not serialize arbitrary sensitive input.
    confirmation_summary: Callable[[Any], str] | None = None
    public_result: Callable[[Any], str] | None = None

    def __post_init__(self):
        if not 0 < self.timeout_seconds <= 120:
            raise ValueError("Tool timeout must be between 0 and 120 seconds")
        if self.side_effects and (not self.sensitive or self.cancellation_safe):
            raise ValueError(
                "Side-effecting tools must require confirmation "
                "and not be cancellation-safe"
            )
        if self.sensitive and self.confirmation_summary is None:
            raise ValueError("Sensitive tools require a reviewed confirmation summary")
        if self.side_effects and self.permission == "tools:read":
            raise ValueError("Writes require an explicit non-read permission")
        if "idempotency_key" in self.input_schema.model_fields:
            raise ValueError("idempotency_key is reserved for the execution envelope")
        if len(self.title) > 200 or len(self.description) > 500:
            raise ValueError("Tool title/description exceeds UI metadata limits")
