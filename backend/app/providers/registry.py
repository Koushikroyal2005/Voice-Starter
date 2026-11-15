"""Metadata registry; LiveKit objects remain the actual provider interfaces."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

Category = Literal["stt", "llm", "tts"]


class ProviderError(ValueError):
    """Invalid provider selection or capability requirement."""


@dataclass(frozen=True)
class Capabilities:
    # None means model/endpoint dependent or not applicable, never guaranteed.
    streaming: bool
    interim_transcription: bool | None = None
    turn_detection: bool | None = None
    multilingual: bool | None = None
    cancellation: bool = True
    tool_calling: bool | None = None
    notes: str = "Cancellation closes local streams; remote billing may continue."


@dataclass(frozen=True)
class ModelMetadata:
    capabilities: Capabilities
    voice: str = ""
    language: str = "en"
    voices: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    api_version: str = ""
    evidence: str = "documented"


@dataclass(frozen=True)
class ProviderSpec:
    category: Category
    name: str
    builder: str
    api_key_env: str
    model: str
    capabilities: Capabilities
    voice: str = ""
    base_url: str = ""
    docs: str = ""
    models: tuple[str, ...] = ()  # Empty: defer model availability to provider API.
    model_metadata: Mapping[str, ModelMetadata] = field(default_factory=dict)
    plugin_module: str = ""

    def capabilities_for(
        self, model: str, *, base_url: str | None = None
    ) -> Capabilities:
        if base_url is not None and base_url.rstrip("/") != self.base_url.rstrip("/"):
            # A vendor model name on a different endpoint is not the same promise.
            return self.capabilities
        metadata = self.model_metadata.get(model)
        return metadata.capabilities if metadata else self.capabilities


class ProviderRegistry:
    def __init__(self) -> None:
        self._entries: dict[tuple[Category, str], ProviderSpec] = {}

    def register(self, spec: ProviderSpec) -> None:
        if spec.category not in ("stt", "llm", "tts") or not spec.name:
            raise ProviderError("Provider requires a valid category and name")
        key = (spec.category, spec.name)
        if key in self._entries:
            raise ProviderError(f"Duplicate provider: {spec.category}/{spec.name}")
        self._entries[key] = spec

    def get(self, category: Category, name: str) -> ProviderSpec:
        try:
            return self._entries[(category, name)]
        except KeyError:
            supported = ", ".join(p.name for p in self.list(category))
            raise ProviderError(
                f"Unsupported {category} provider {name!r}. Supported: {supported}"
            ) from None

    def list(self, category: Category) -> tuple[ProviderSpec, ...]:
        return tuple(p for p in self._entries.values() if p.category == category)

    def require(
        self, category: Category, name: str, capability: str, model: str = ""
    ) -> None:
        spec = self.get(category, name)
        caps = spec.capabilities_for(model) if model else spec.capabilities
        if capability not in Capabilities.__dataclass_fields__ or capability == "notes":
            raise ProviderError(f"Unknown capability: {capability}")
        if getattr(caps, capability) is not True:
            raise ProviderError(
                f"{category}/{name} does not guarantee {capability}; "
                "check the selected model/endpoint"
            )


registry = ProviderRegistry()

# Catalogs populate this registry; there is no separate model registry.
from app.config.catalogs import register_catalogs  # noqa: E402

register_catalogs(registry)
