"""Resolve provider values without reading environment or composing the application."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.config.validation import (
    ConfigurationError,
    boolean,
    require_credentials,
    validate_url,
)
from app.providers.registry import (
    Category,
    ProviderError,
    ProviderRegistry,
    ProviderSpec,
    registry,
)


@dataclass(frozen=True)
class ProviderConfig:
    category: Category
    provider: str
    model: str
    api_key: str = field(repr=False)
    base_url: str = ""
    language: str = "en"
    voice: str = ""


@dataclass(frozen=True)
class STTRequirements:
    allow_batch: bool
    require_interim: bool
    turn_detection: str


def _get_spec(
    category: Category, name: str, provider_registry: ProviderRegistry
) -> ProviderSpec:
    try:
        return provider_registry.get(category, name)
    except ProviderError:
        # A mistyped selection can accidentally contain a credential or URL. Keep
        # registry lookup/error semantics but do not echo the untrusted value.
        supported = ", ".join(spec.name for spec in provider_registry.list(category))
        raise ProviderError(
            f"Unsupported {category} provider. Supported: {supported}"
        ) from None


def resolve_provider(
    category: Category,
    values: Mapping[str, str],
    provider_registry: ProviderRegistry = registry,
    *,
    missing: list[str] | None = None,
) -> ProviderConfig:
    """Resolve one category; optionally contribute to application key aggregation.

    Values are already merged by the caller. No profile, infrastructure or process
    environment is consulted here. STT interaction requirements are checked later,
    preserving the application's existing missing-key and LiveKit-URL precedence.
    """

    def optional(key: str, default: str = "") -> str:
        return values.get(key, "").strip() or default

    prefix = category.upper()
    default = {"stt": "deepgram", "llm": "openai_compatible", "tts": "cartesia"}[
        category
    ]
    name = optional(f"{prefix}_PROVIDER", default).lower()
    try:
        spec = _get_spec(category, name, provider_registry)
    except ProviderError as error:
        raise ConfigurationError(str(error)) from None
    absent = [] if missing is None else missing
    key = optional(spec.api_key_env)
    if name == "openai_compatible":
        key = key or optional("OPENAI_API_KEY")
    if not key:
        absent.append(
            "LLM_API_KEY (or OPENAI_API_KEY)"
            if name == "openai_compatible"
            else spec.api_key_env
        )
    model = optional(f"{prefix}_MODEL", spec.model)
    if spec.models and model not in spec.models:
        raise ConfigurationError(
            f"{prefix}_MODEL is unsupported for {name}; "
            f"supported: {', '.join(spec.models)}"
        )
    base_url = optional(f"{prefix}_BASE_URL", spec.base_url)
    if category == "llm" and name == "gemini" and base_url:
        raise ConfigurationError("LLM_BASE_URL is not supported for gemini")
    if category == "stt" and name != "whisper" and base_url:
        raise ConfigurationError(f"STT_BASE_URL is not supported for {name}")
    if category == "tts" and base_url:
        raise ConfigurationError("TTS_BASE_URL is not configured by these adapters")
    if base_url:
        validate_url(f"{prefix}_BASE_URL", base_url, {"http", "https"})
    if category == "llm" and name == "openai_compatible":
        if base_url.rstrip("/") != spec.base_url and not optional("LLM_MODEL"):
            raise ConfigurationError("LLM_MODEL is required for a custom LLM_BASE_URL")
    config = ProviderConfig(
        category=category,
        provider=name,
        model=model,
        api_key=key,
        base_url=base_url,
        language=optional(f"{prefix}_LANGUAGE", "en"),
        voice=optional(f"{prefix}_VOICE", spec.voice),
    )
    if missing is None:
        require_credentials(absent)
    return config


def resolve_stt_requirements(
    values: Mapping[str, str],
    config: ProviderConfig,
    provider_registry: ProviderRegistry = registry,
) -> STTRequirements:
    """Validate the existing STT interaction policy against registered capabilities."""
    allow_batch = boolean(values, "STT_ALLOW_BATCH")
    require_interim = boolean(values, "STT_REQUIRE_INTERIM")
    turn_detection = values.get("TURN_DETECTION", "").strip() or "vad"
    if turn_detection not in ("vad", "stt"):
        raise ConfigurationError("TURN_DETECTION must be vad or stt")
    caps = provider_registry.get("stt", config.provider).capabilities
    if not caps.streaming and not allow_batch:
        raise ConfigurationError(
            "Batch STT requires STT_ALLOW_BATCH=true; no live interim results"
        )
    if require_interim and caps.interim_transcription is not True:
        raise ConfigurationError("Selected STT does not support interim transcription")
    if turn_detection == "stt" and caps.turn_detection is not True:
        raise ConfigurationError(
            "Selected STT does not support provider turn detection; use vad"
        )
    return STTRequirements(allow_batch, require_interim, turn_detection)


def resolve_fallbacks(
    values: Mapping[str, str],
    primary_providers: Mapping[Category, ProviderConfig],
    provider_registry: ProviderRegistry = registry,
) -> tuple[ProviderConfig, ...]:
    """Resolve selected backups independently, preserving category order and gates."""
    fallbacks = []
    clean = {k: v for k, v in values.items() if "_FALLBACK_" not in k}
    for category in ("stt", "llm", "tts"):
        prefix = category.upper()
        name = values.get(f"{prefix}_FALLBACK_PROVIDER", "").strip()
        if not name:
            continue
        # Retain the registry's exact-name lookup for fallback selections.
        spec = _get_spec(category, name, provider_registry)
        key = values.get(f"{prefix}_FALLBACK_API_KEY", "").strip()
        if not key:
            raise ConfigurationError(f"{prefix}_FALLBACK_API_KEY is required")
        if values.get(f"{prefix}_FALLBACK_COMPATIBLE", "false") != "true":
            raise ConfigurationError(
                f"{prefix}_FALLBACK_COMPATIBLE=true requires operator verification "
                "of language, model, tools, consent and data residency"
            )
        overlay = dict(clean)
        for field_name in ("MODEL", "BASE_URL", "VOICE", "LANGUAGE"):
            overlay[f"{prefix}_{field_name}"] = values.get(
                f"{prefix}_FALLBACK_{field_name}", ""
            )
        overlay[f"{prefix}_PROVIDER"] = name
        overlay[spec.api_key_env] = key
        fallback = resolve_provider(category, overlay, provider_registry)
        if category == "stt":
            resolve_stt_requirements(overlay, fallback, provider_registry)
        if fallback.language != primary_providers[category].language:
            raise ConfigurationError("Fallback language must match primary")
        if not spec.capabilities.streaming:
            raise ConfigurationError("Batch providers cannot be realtime fallbacks")
        fallbacks.append(fallback)
    return tuple(fallbacks)
