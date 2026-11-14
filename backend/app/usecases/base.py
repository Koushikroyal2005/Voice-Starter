"""Small trusted application contract; no plugin loading or secret serialization."""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.tools.base import ToolDefinition


class PublicUseCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: int = 1
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=300)
    languages: tuple[
        Annotated[str, Field(pattern=r"^[a-zA-Z][a-zA-Z0-9-]{0,23}$")], ...
    ] = Field(min_length=1, max_length=10)
    result_card_types: tuple[str, ...] = Field(
        default=("text",), min_length=1, max_length=10
    )
    notice: str = Field(default="", max_length=400)


@dataclass(frozen=True)
class ConversationPolicies:
    instructions: str = ""
    allow_transcript_storage: bool = True
    allow_side_effects: bool = True
    require_confirmation_for: tuple[str, ...] = ()


def no_tools():
    return ()


@dataclass(frozen=True)
class UseCase:
    id: str
    name: str
    description: str
    instructions: str
    supported_languages: tuple[str, ...] = ("en",)
    restrict_languages: bool = True
    provider_defaults: Mapping[str, str] = field(default_factory=dict)
    allowed_providers: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    default_tools: tuple[str, ...] = (
        "get_current_time",
        "calculate_expression",
        "time_and_calculate",
    )
    allowed_tools: tuple[str, ...] | None = None
    tool_factory: Callable[[], tuple[ToolDefinition, ...]] = no_tools
    mcp_servers: tuple[str, ...] | None = ()
    mcp_tool_allowlist: tuple[str, ...] = ()
    mcp_config_file: str | None = None
    policies: ConversationPolicies = field(default_factory=ConversationPolicies)
    service_names: tuple[str, ...] = ()
    result_card_types: tuple[str, ...] = ("text",)
    notice: str = ""

    def __post_init__(self):
        self.public_config()
        allowed_defaults = {
            f"{category}_{name}"
            for category in ("STT", "LLM", "TTS")
            for name in ("PROVIDER", "MODEL", "LANGUAGE", "VOICE", "BASE_URL")
        }
        if set(self.provider_defaults) - allowed_defaults:
            raise ValueError(
                "Use-case defaults may contain only public provider options"
            )
        if not self.instructions.strip() or not self.supported_languages:
            raise ValueError("Use cases require instructions and declared languages")
        if any(
            not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", name)
            for name in self.result_card_types
        ):
            raise ValueError("Invalid result card type")

    def public_config(self, active_language=None):
        languages = self.supported_languages
        if not self.restrict_languages and active_language:
            languages = tuple(dict.fromkeys((*languages, active_language)))
        return PublicUseCase(
            id=self.id,
            name=self.name,
            description=self.description,
            languages=languages,
            result_card_types=self.result_card_types,
            notice=self.notice,
        )

    def validate_selection(self, providers, tools, infrastructure):
        if self.mcp_servers is not None and any(
            tool.startswith("mcp_") and tool not in self.mcp_tool_allowlist
            for tool in tools
        ):
            raise ValueError("MCP tool is not allowed by this use case")
        for category, config in providers.items():
            allowed = self.allowed_providers.get(category)
            if allowed is not None and config.provider not in allowed:
                raise ValueError(
                    f"Use case does not allow selected {category} provider"
                )
            if (
                self.restrict_languages
                and category in {"stt", "tts"}
                and config.language not in self.supported_languages
            ):
                raise ValueError("Language is not declared by this use case")
        if self.allowed_tools is not None:
            if set(tools) - set(self.allowed_tools) - set(self.mcp_tool_allowlist):
                raise ValueError("Tool is not allowed by this use case")
        if (
            infrastructure.transcripts_enabled
            and not self.policies.allow_transcript_storage
        ):
            raise ValueError("Use case forbids transcript persistence")


def apply_tool_policies(profile, definitions):
    result = []
    for tool in definitions:
        if tool.side_effects and not profile.policies.allow_side_effects:
            raise ValueError("Use case forbids side-effecting tools")
        if tool.name in profile.policies.require_confirmation_for:
            if tool.confirmation_summary is None:
                raise ValueError("Confirmation policy requires a reviewed tool summary")
            tool = replace(tool, sensitive=True)
        result.append(tool)
    return tuple(result)
