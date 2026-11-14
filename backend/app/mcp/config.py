"""Backend-only configuration. Secrets are referenced by environment name, not value."""

import json
import os
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config.settings import ConfigurationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]
NAME = r"[a-z][a-z0-9_]{0,23}"
ENV_NAME = r"[A-Z_][A-Z0-9_]*"


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    remote_name: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=500)
    input_schema: dict = Field(repr=False)
    output_schema: dict = Field(repr=False)
    llm_fields: list[str] = Field(default_factory=list)
    permission: str = Field(min_length=1)
    sensitive: bool = True
    side_effects: bool = True
    cancellation_safe: bool = False
    confirmation_summary: str = Field(
        default="Review the requested external action.", max_length=500
    )
    confirmation_fields: list[str] = Field(default_factory=list)
    timeout_seconds: float = Field(default=10, gt=0, le=120)
    idempotency_argument: str | None = None

    @model_validator(mode="after")
    def safe_policy(self):
        fields = set(self.input_schema.get("properties", {})) - {
            self.idempotency_argument
        }
        if self.sensitive and fields and not self.confirmation_fields:
            raise ValueError(
                "Sensitive parameterized tools require reviewed confirmation fields"
            )
        if any(field not in fields for field in self.confirmation_fields):
            raise ValueError("Invalid confirmation disclosure field")
        if self.side_effects:
            if (
                not self.sensitive
                or self.cancellation_safe
                or self.permission == "tools:read"
                or not self.idempotency_argument
            ):
                raise ValueError(
                    "MCP writes require confirmation, a write permission "
                    "and a remote idempotency argument"
                )
        if "idempotency_key" in self.input_schema.get("properties", {}):
            raise ValueError("idempotency_key is reserved for the execution envelope")
        if (
            self.idempotency_argument
            and self.idempotency_argument not in self.input_schema.get("properties", {})
        ):
            raise ValueError(
                "Remote idempotency argument must exist in the reviewed schema"
            )
        if any(
            field not in self.output_schema.get("properties", {})
            for field in self.llm_fields
        ):
            raise ValueError(
                "Every LLM disclosure field must be in the reviewed output schema"
            )
        if (
            self.input_schema.get("type") != "object"
            or self.output_schema.get("type") != "object"
        ):
            raise ValueError("Approved MCP input and output must be JSON objects")
        return self


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=f"^{NAME}$")
    enabled: bool = False
    transport: Literal["stdio", "streamable_http"]
    command: str | None = Field(default=None, repr=False)
    args: list[str] = Field(default_factory=list, repr=False)
    cwd: str | None = Field(default=None, repr=False)
    env: dict[str, str] = Field(default_factory=dict, repr=False)
    url: str | None = Field(default=None, repr=False)
    url_env: str | None = Field(default=None, repr=False)
    headers_env: dict[str, str] = Field(default_factory=dict, repr=False)
    allow_http_loopback: bool = False
    connect_timeout_seconds: float = Field(default=5, gt=0, le=20)
    request_timeout_seconds: float = Field(default=10, gt=0, le=120)
    reconnect_interval_seconds: float = Field(default=2, ge=0.1, le=30)
    health_interval_seconds: float = Field(default=15, ge=0.1, le=120)
    approved_tools: dict[str, Policy] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_transport(self):
        if self.transport == "stdio":
            if not self.command or self.url or self.url_env or self.headers_env:
                raise ValueError(
                    "stdio requires command and cannot have HTTP configuration"
                )
        elif (
            bool(self.url) == bool(self.url_env)
            or self.command
            or self.env
            or self.args
            or self.cwd
        ):
            raise ValueError(
                "HTTP requires one of url/url_env and no subprocess configuration"
            )
        for alias in self.approved_tools:
            if not re.fullmatch(NAME, alias):
                raise ValueError("Invalid approved tool alias")
        if len({p.remote_name for p in self.approved_tools.values()}) != len(
            self.approved_tools
        ):
            raise ValueError("Duplicate remote tool approvals")
        for variable in [
            *self.env.values(),
            *self.headers_env.values(),
            *([self.url_env] if self.url_env else []),
        ]:
            if not re.fullmatch(ENV_NAME, variable):
                raise ValueError(
                    "Credentials/config must reference environment variable names"
                )
        for name in self.headers_env:
            if not re.fullmatch(r"[A-Za-z0-9-]+", name) or name.lower() in {
                "host",
                "connection",
                "content-length",
                "transfer-encoding",
                "proxy-authorization",
            }:
                raise ValueError("Unsafe HTTP header configuration")
        return self

    def endpoint(self) -> str:
        value = self.url or required_env(self.url_env)
        try:
            parsed = urlsplit(value)
            _ = parsed.port
            valid = parsed.scheme == "https" or (
                self.allow_http_loopback
                and parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            )
            if (
                not valid
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError
        except ValueError:
            raise ConfigurationError(
                "MCP requires HTTPS or explicit loopback HTTP, "
                "without embedded credentials/query/fragment"
            ) from None
        return value


class MCPConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    servers: list[ServerConfig] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def unique_servers(self):
        if len({s.id for s in self.servers}) != len(self.servers):
            raise ValueError("Duplicate MCP server IDs")
        return self


def required_env(name: str | None) -> str:
    value = os.environ.get(name or "", "").strip()
    if not value:
        raise ConfigurationError(
            f"Missing backend environment variable for MCP: {name}"
        )
    return value


def load_config(path: str) -> MCPConfig:
    source = Path(path)
    if not source.is_absolute():
        source = BACKEND_ROOT / source
    try:
        if source.stat().st_size > 131072:
            raise ValueError
        return MCPConfig.model_validate(
            json.loads(source.read_text(encoding="utf-8-sig"))
        )
    except (OSError, ValueError):
        # Pydantic errors can echo secret-bearing configuration. Do not forward them.
        raise ConfigurationError(
            "Invalid/missing MCP config; check the backend JSON file and MCP docs"
        ) from None
