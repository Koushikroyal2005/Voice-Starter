"""Strict local YAML metadata; the existing provider registry remains authoritative."""

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config.validation import ConfigurationError, validate_url

CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ModelEntry(StrictModel):
    capabilities: dict[str, bool | str | None]
    voice: str = ""
    language: str = "en"
    voices: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    api_version: Literal["", "v1beta"] = ""
    evidence: Literal["documented", "inference_verified", "handshake_only"] = (
        "documented"
    )


class CategoryEntry(StrictModel):
    adapter: str
    api_key_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]*_API_KEY$")
    default_model: str
    base_url: str = ""
    allow_custom_models: bool = False
    capabilities: dict[str, bool | str | None]
    models: dict[str, ModelEntry]
    docs: str


class Catalog(StrictModel):
    version: Literal[1]
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")
    categories: dict[Literal["stt", "llm", "tts"], CategoryEntry]


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise ConfigurationError("Configuration contains duplicate/invalid keys")
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping
)


def read_yaml(path: Path, schema):
    try:
        if path.stat().st_size > 65536:
            raise ValueError
        raw = path.read_text(encoding="utf-8")
        # Config is deliberately small and explicit; no YAML aliases/tags/includes.
        if any(
            isinstance(t, (yaml.AliasToken, yaml.AnchorToken)) for t in yaml.scan(raw)
        ):
            raise ValueError
        return schema.model_validate(yaml.load(raw, Loader=UniqueLoader))
    except (OSError, ValueError, TypeError, yaml.YAMLError, ValidationError):
        # Never echo YAML values, paths, validation inputs or accidentally pasted keys.
        raise ConfigurationError(
            "Invalid or missing local provider/profile YAML"
        ) from None


def register_catalogs(target, directory: Path = CONFIG_ROOT / "providers"):
    from app.providers.registry import Capabilities, ModelMetadata, ProviderSpec

    adapters = {
        "stt": {"groq", "gemini", "deepgram", "assemblyai", "whisper"},
        "llm": {"openai_compatible", "gemini"},
        "tts": {
            "groq_tts",
            "gemini",
            "cartesia",
            "elevenlabs",
            "murf",
            "nvidia_magpie",
        },
    }
    plugins = {
        "groq": "openai",
        "groq_tts": "openai",
        "whisper": "openai",
        "openai_compatible": "openai",
        "gemini": "google",
    }

    def caps(values):
        try:
            if not isinstance(values.get("streaming"), bool):
                raise ValueError
            for key, value in values.items():
                if key == "notes":
                    if not isinstance(value, str):
                        raise ValueError
                elif value is not None and not isinstance(value, bool):
                    raise ValueError
            return Capabilities(**values)
        except (TypeError, ValueError):
            raise ConfigurationError("Invalid catalog capabilities") from None

    paths = sorted(directory.glob("*.yaml"))
    if not paths:
        raise ConfigurationError("Provider catalogs are missing")
    for path in paths:
        catalog = read_yaml(path, Catalog)
        for category, entry in catalog.categories.items():
            if (
                entry.adapter not in adapters[category]
                or entry.default_model not in entry.models
            ):
                raise ConfigurationError(
                    "Catalog requires a supported adapter and default model"
                )
            if entry.base_url:
                validate_url("Catalog endpoint", entry.base_url, {"http", "https"})
            metadata = {
                name: ModelMetadata(
                    capabilities=caps(model.capabilities),
                    voice=model.voice,
                    language=model.language,
                    voices=tuple(model.voices),
                    languages=tuple(model.languages),
                    api_version=model.api_version,
                    evidence=model.evidence,
                )
                for name, model in entry.models.items()
            }
            default = metadata[entry.default_model]
            target.register(
                ProviderSpec(
                    category,
                    catalog.name,
                    f"app.providers.{category}:{entry.adapter}",
                    entry.api_key_env,
                    entry.default_model,
                    caps(entry.capabilities),
                    voice=default.voice,
                    base_url=entry.base_url,
                    docs=entry.docs,
                    models=() if entry.allow_custom_models else tuple(metadata),
                    model_metadata=metadata,
                    plugin_module=(
                        "app.providers.tts.nvidia"
                        if entry.adapter == "nvidia_magpie"
                        else "livekit.plugins."
                        + plugins.get(entry.adapter, entry.adapter)
                    ),
                )
            )


def valid_name(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z][a-z0-9_]{0,47}", name))
