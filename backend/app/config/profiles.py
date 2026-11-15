"""Resolve a named pipeline into existing environment/provider settings, offline."""

from collections.abc import Mapping
from typing import Literal

from app.config.catalogs import CONFIG_ROOT, StrictModel, read_yaml, valid_name
from app.config.validation import ConfigurationError, boolean


class Selection(StrictModel):
    provider: str
    model: str = ""
    voice: str = ""
    language: str = ""
    base_url: str = ""


class VoiceProfile(StrictModel):
    version: Literal[1]
    name: str
    stt: Selection
    llm: Selection
    tts: Selection
    turn_detection: Literal["vad", "stt"] = "vad"


def resolve_voice_profile(
    supplied: Mapping[str, str],
    defaults: Mapping[str, str],
    provider_registry,
    *,
    root=CONFIG_ROOT,
) -> tuple[dict[str, str], tuple[str, ...]]:
    name = supplied.get("VOICE_PROFILE", "").strip()
    if not name:
        return {**defaults, **supplied}, ()  # Preserve legacy blank/reset semantics.
    if not valid_name(name):
        raise ConfigurationError("Invalid VOICE_PROFILE name")
    path = root / "profiles" / f"{name}.yaml"
    if not path.is_file():
        raise ConfigurationError(
            "Unknown or missing VOICE_PROFILE; see config/profiles"
        )
    profile = read_yaml(path, VoiceProfile)
    if profile.name != name:
        raise ConfigurationError("VOICE_PROFILE name does not match its file")

    def spec_for(category, provider):
        try:
            return provider_registry.get(category, provider)
        except ValueError:
            raise ConfigurationError(
                "Profile selects an unsupported provider/category"
            ) from None

    def category_values(category, selection, explicit):
        prefix = category.upper()
        provider = explicit.get(f"{prefix}_PROVIDER", "").strip() or selection.provider
        spec = spec_for(category, provider)
        same_provider = provider == selection.provider
        model = (
            explicit.get(f"{prefix}_MODEL", "").strip()
            or (selection.model if same_provider else "")
            or spec.model
        )
        if spec.models and model not in spec.models:
            raise ConfigurationError(
                f"{prefix}_MODEL is unsupported for selected provider"
            )
        metadata = spec.model_metadata.get(model)
        result = {f"{prefix}_PROVIDER": provider, f"{prefix}_MODEL": model}
        for field, default in (
            ("VOICE", metadata.voice if metadata else spec.voice),
            ("LANGUAGE", metadata.language if metadata else "en"),
            ("BASE_URL", spec.base_url),
        ):
            chosen = getattr(selection, field.lower()) if same_provider else ""
            result[f"{prefix}_{field}"] = (
                explicit.get(f"{prefix}_{field}", "").strip() or chosen or default
            )
        return result, spec.capabilities_for(model), metadata

    baseline = {}
    resolved = {}
    versions = set()
    base_versions = set()
    for category in ("stt", "llm", "tts"):
        selection = getattr(profile, category)
        base, base_caps, base_model = category_values(category, selection, {})
        current, caps, metadata = category_values(category, selection, supplied)
        baseline.update(base)
        resolved.update(current)
        if metadata and metadata.api_version:
            versions.add(metadata.api_version)
        if base_model and base_model.api_version:
            base_versions.add(base_model.api_version)
        if category == "stt":
            baseline.update(
                STT_ALLOW_BATCH=str(not base_caps.streaming).lower(),
                STT_REQUIRE_INTERIM=str(
                    base_caps.interim_transcription is True
                ).lower(),
            )
            resolved.update(
                STT_ALLOW_BATCH=str(not caps.streaming).lower(),
                STT_REQUIRE_INTERIM=str(caps.interim_transcription is True).lower(),
            )
    if len(versions) > 1:
        raise ConfigurationError("Profile requires incompatible Google API versions")
    baseline["TURN_DETECTION"] = profile.turn_detection
    resolved["TURN_DETECTION"] = profile.turn_detection
    if base_versions:
        baseline["GOOGLE_GENAI_API_VERSION"] = next(iter(base_versions))
    if versions:
        resolved["GOOGLE_GENAI_API_VERSION"] = next(iter(versions))
    # Nonblank explicit settings always win, but potentially stale ones must be
    # acknowledged first. Neither values nor secrets appear in conflict messages.
    conflicts = tuple(
        sorted(
            key
            for key, value in baseline.items()
            if supplied.get(key, "").strip() and supplied[key].strip() != value
        )
    )
    if conflicts and not boolean(supplied, "VOICE_PROFILE_ALLOW_OVERRIDES"):
        raise ConfigurationError(
            "VOICE_PROFILE conflicts with environment settings: "
            + ", ".join(conflicts)
            + ". Remove stale overrides or set VOICE_PROFILE_ALLOW_OVERRIDES=true."
        )
    merged = {**defaults, **supplied, **resolved}
    for key in resolved:
        if supplied.get(key, "").strip():
            merged[key] = supplied[key].strip()
    return merged, conflicts
