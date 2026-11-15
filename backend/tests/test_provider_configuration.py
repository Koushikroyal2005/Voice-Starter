"""Configuration characterization; synthetic credentials, no model API calls."""

import subprocess
import sys
from dataclasses import replace
from unittest.mock import patch

import pytest

from app.config.infrastructure import InfrastructureSettings
from app.config.providers import (
    ProviderConfig,
    resolve_fallbacks,
    resolve_provider,
    resolve_stt_requirements,
)
from app.config.settings import ConfigurationError, Settings
from app.observability.config import ObservabilitySettings
from app.providers.registry import ProviderError, ProviderRegistry, registry
from app.usecases.registry import registry as usecases


def environment(**values):
    return {
        "LIVEKIT_URL": "wss://example.test",
        "LIVEKIT_API_KEY": "synthetic-room-key",
        "LIVEKIT_API_SECRET": "synthetic-room-secret",
        "DEEPGRAM_API_KEY": "synthetic-stt-key",
        "LLM_API_KEY": "synthetic-llm-key",
        "CARTESIA_API_KEY": "synthetic-tts-key",
        **values,
    }


def fallback(category, name, **values):
    prefix = category.upper() + "_FALLBACK_"
    return {
        prefix + "PROVIDER": name,
        prefix + "API_KEY": "synthetic-fallback-key",
        prefix + "COMPATIBLE": "true",
        **{prefix + key: value for key, value in values.items()},
    }


@pytest.mark.parametrize("category", ["stt", "llm", "tts"])
def test_primary_defaults_resolve_registered_metadata(category):
    config = getattr(Settings.from_env(environment()), category)
    spec = registry.get(category, config.provider)
    assert (config.model, config.voice, config.base_url) == (
        spec.model,
        spec.voice,
        spec.base_url,
    )
    assert config.language == "en"


def test_three_fallback_categories_are_ordered_and_have_dedicated_credentials():
    values = environment()
    for category, name in (
        ("stt", "assemblyai"),
        ("llm", "gemini"),
        ("tts", "elevenlabs"),
    ):
        values.update(fallback(category, name))
    settings = Settings.from_env(values)
    assert [config.category for config in settings.fallbacks] == ["stt", "llm", "tts"]
    assert [config.provider for config in settings.fallbacks] == [
        "assemblyai",
        "gemini",
        "elevenlabs",
    ]
    assert all(
        config.api_key == "synthetic-fallback-key" for config in settings.fallbacks
    )


@pytest.mark.parametrize(
    "category,name",
    [
        (spec.category, spec.name)
        for category in ("stt", "llm", "tts")
        for spec in registry.list(category)
        if spec.capabilities.streaming
    ],
)
def test_primary_and_fallback_use_equivalent_field_resolution(category, name):
    prefix = category.upper()
    spec = registry.get(category, name)
    options = {"LANGUAGE": "en", "MODEL": spec.model, "VOICE": spec.voice}
    primary = getattr(
        Settings.from_env(
            environment(
                **{
                    prefix + "_PROVIDER": name,
                    spec.api_key_env: "synthetic-fallback-key",
                    **{prefix + "_" + key: value for key, value in options.items()},
                }
            )
        ),
        category,
    )
    backup = Settings.from_env(
        environment(**fallback(category, name, **options))
    ).fallbacks[0]
    assert backup == primary


def test_fallback_fields_reset_to_registry_defaults_not_primary_fields():
    settings = Settings.from_env(
        environment(
            LLM_MODEL="primary-model",
            LLM_BASE_URL="https://primary.invalid/v1",
            TTS_MODEL="primary-tts",
            TTS_VOICE="primary-voice",
            **fallback("llm", "openai_compatible", MODEL="  ", BASE_URL="  "),
            **fallback("tts", "elevenlabs", MODEL="", VOICE="  "),
        )
    )
    llm, tts = settings.fallbacks
    assert llm.model == registry.get("llm", "openai_compatible").model
    assert llm.base_url == "https://api.openai.com/v1"
    assert tts.model == registry.get("tts", "elevenlabs").model
    assert tts.voice == registry.get("tts", "elevenlabs").voice


@pytest.mark.parametrize("key", ["", "  "])
def test_legacy_llm_key_is_used_only_when_generic_key_is_blank(key):
    settings = Settings.from_env(
        environment(LLM_API_KEY=key, OPENAI_API_KEY="legacy-key")
    )
    assert settings.llm.api_key == "legacy-key"


def test_fallback_never_borrows_primary_or_vendor_credentials():
    values = environment(**fallback("llm", "gemini"), GOOGLE_API_KEY="primary-google")
    values["LLM_FALLBACK_API_KEY"] = " "
    with pytest.raises(ConfigurationError, match="LLM_FALLBACK_API_KEY is required"):
        Settings.from_env(values)


@pytest.mark.parametrize(
    "endpoint,model",
    [
        ("http://localhost:8000/v1", "local-model"),
        ("https://nim.example.invalid/v1", "namespace/nim-model"),
    ],
)
def test_custom_compatible_endpoint_fields_are_equivalent(endpoint, model):
    values = environment(
        LLM_BASE_URL=endpoint,
        LLM_MODEL=model,
        **fallback("llm", "openai_compatible", BASE_URL=endpoint, MODEL=model),
    )
    settings = Settings.from_env(values)
    assert (
        replace(settings.llm, api_key=settings.fallbacks[0].api_key)
        == settings.fallbacks[0]
    )


@pytest.mark.parametrize(
    "values,message",
    [
        ({"STT_MODEL": "secret-invalid-model"}, "STT_MODEL is unsupported"),
        (
            fallback("stt", "assemblyai", MODEL="secret-invalid-model"),
            "STT_MODEL is unsupported",
        ),
        (
            fallback(
                "llm", "openai_compatible", BASE_URL="https://nim.example.invalid/v1"
            ),
            "LLM_MODEL is required",
        ),
        (
            fallback("llm", "gemini", BASE_URL="https://custom.invalid/v1"),
            "LLM_BASE_URL is not supported",
        ),
        (
            fallback("tts", "cartesia", BASE_URL="https://custom.invalid/v1"),
            "TTS_BASE_URL is not configured",
        ),
        (
            fallback("stt", "assemblyai", BASE_URL="https://custom.invalid/v1"),
            "STT_BASE_URL is not supported",
        ),
    ],
)
def test_validation_precedence_and_safe_messages(values, message):
    with pytest.raises(ConfigurationError, match=message) as error:
        Settings.from_env(environment(**values))
    assert "secret-invalid-model" not in str(error.value)
    assert "synthetic-fallback-key" not in str(error.value)


def test_fallback_must_match_language_and_language_is_not_inherited():
    with pytest.raises(
        ConfigurationError, match="Fallback language must match primary"
    ):
        Settings.from_env(
            environment(STT_LANGUAGE="te", **fallback("stt", "assemblyai"))
        )
    result = Settings.from_env(
        environment(STT_LANGUAGE="te", **fallback("stt", "assemblyai", LANGUAGE="te"))
    )
    assert result.fallbacks[0].language == "te"
    with pytest.raises(ConfigurationError, match="Language is not declared"):
        Settings.from_env(environment(USE_CASE="finance", STT_LANGUAGE="te"))


def test_batch_and_provider_turn_detection_checks_are_retained():
    with pytest.raises(
        ConfigurationError, match="Batch providers cannot be realtime fallbacks"
    ):
        Settings.from_env(
            environment(STT_ALLOW_BATCH="true", **fallback("stt", "whisper"))
        )
    with pytest.raises(ConfigurationError, match="provider turn detection"):
        Settings.from_env(
            environment(
                STT_PROVIDER="assemblyai",
                ASSEMBLYAI_API_KEY="selected",
                TURN_DETECTION="stt",
                **fallback("stt", "deepgram"),
            )
        )


@pytest.mark.parametrize("flag", ["", "TRUE", " true ", "false"])
def test_fallback_compatibility_acknowledgement_is_exact_not_a_boolean_flag(flag):
    with pytest.raises(ConfigurationError, match="COMPATIBLE=true"):
        Settings.from_env(environment(**fallback("llm", "gemini", COMPATIBLE=flag)))


def test_blank_primary_provider_uses_application_default_not_profile_default(
    monkeypatch,
):
    profile = replace(
        usecases.get(),
        provider_defaults={
            "STT_PROVIDER": "assemblyai",
            "STT_MODEL": "universal-3-5-pro",
        },
    )
    monkeypatch.setitem(usecases.entries, profile.id, profile)
    selected = Settings.from_env(environment(ASSEMBLYAI_API_KEY="profile-key"))
    assert (
        selected.stt.provider == "assemblyai"
        and selected.stt.model == "universal-3-5-pro"
    )
    explicit = Settings.from_env(
        environment(STT_PROVIDER="deepgram", STT_MODEL="nova-2")
    )
    assert explicit.stt.model == "nova-2"
    blank = Settings.from_env(environment(STT_PROVIDER=" ", STT_MODEL=" "))
    assert blank.stt.provider == "deepgram" and blank.stt.model == "nova-3"


def test_missing_credentials_aggregate_in_existing_order():
    with pytest.raises(ConfigurationError) as error:
        Settings.from_env({})
    assert str(error.value) == (
        "Missing required environment variables: LIVEKIT_URL, LIVEKIT_API_KEY, "
        "LIVEKIT_API_SECRET, DEEPGRAM_API_KEY, LLM_API_KEY (or OPENAI_API_KEY), "
        "CARTESIA_API_KEY"
    )
    with pytest.raises(ConfigurationError, match="STT_MODEL is unsupported"):
        Settings.from_env({"STT_MODEL": "invalid"})


def test_disabled_infrastructure_and_empty_allowlist_survive_fallback_resolution():
    settings = Settings.from_env(
        environment(
            TOOL_ALLOWLIST="",
            DATABASE_URL="not-a-database",
            REDIS_URL="not-redis",
            **fallback("llm", "gemini"),
        )
    )
    assert settings.tool_allowlist == ()
    assert not settings.infrastructure.persistence_enabled
    assert not settings.infrastructure.redis_enabled


def test_primary_normalizes_provider_case_but_fallback_selection_is_case_sensitive():
    assert (
        Settings.from_env(
            environment(LLM_PROVIDER=" GEMINI ", GOOGLE_API_KEY="key")
        ).llm.provider
        == "gemini"
    )
    with pytest.raises(ProviderError, match="Unsupported llm"):
        Settings.from_env(environment(**fallback("llm", "GEMINI")))


def test_configuration_errors_and_repr_do_not_include_credentials():
    values = environment(
        **fallback(
            "llm",
            "openai_compatible",
            BASE_URL="https://user:private-url-secret@host/v1",
        )
    )
    with pytest.raises(ConfigurationError) as error:
        Settings.from_env(values)
    for secret in (
        *environment().values(),
        "private-url-secret",
        "synthetic-fallback-key",
    ):
        assert secret not in str(error.value)
    assert "synthetic-fallback-key" not in repr(
        Settings.from_env(environment(**fallback("llm", "gemini")))
    )


def test_fallback_resolution_no_longer_requires_unrelated_application_settings():
    """The old recursive parser raised missing LIVEKIT_URL here before extraction."""
    primary = Settings.from_env(environment()).llm
    configs = Settings.parse_fallbacks(fallback("llm", "gemini"), {"llm": primary})
    assert configs[0].provider == "gemini"


def test_llm_fallback_does_not_read_other_application_or_provider_configuration(
    monkeypatch,
):
    primary = Settings.from_env(environment()).llm

    def forbidden(*args, **kwargs):
        pytest.fail("Provider resolver must not assemble application configuration")

    monkeypatch.setattr(Settings, "from_env", forbidden)
    monkeypatch.setattr(InfrastructureSettings, "from_env", forbidden)
    monkeypatch.setattr(ObservabilitySettings, "from_env", forbidden)
    monkeypatch.setattr(usecases, "get", forbidden)
    values = fallback("llm", "gemini") | {
        "USE_CASE": "invalid",
        "PERSISTENCE_ENABLED": "true",
        "DATABASE_URL": "invalid",
        "REDIS_ENABLED": "not-a-flag",
        "VOICE_OTLP_ENDPOINT": "invalid",
        "PROVIDER_MAX_RETRIES": "invalid",
        "STT_PROVIDER": "unsupported",
        "STT_MODEL": "invalid",
        "STT_REQUIRE_INTERIM": "not-a-flag",
        "TURN_DETECTION": "invalid",
        "TTS_PROVIDER": "unsupported",
        "MCP_ENABLED": "invalid",
        "TOOL_ALLOWLIST": "not-a-tool",
    }
    assert resolve_fallbacks(values, {"llm": primary})[0].provider == "gemini"
    assert Settings.parse_fallbacks(values, {"llm": primary})[0].provider == "gemini"


def test_tts_fallback_only_queries_selected_category_metadata():
    primary = Settings.from_env(environment()).tts
    isolated = ProviderRegistry()
    isolated.register(registry.get("tts", "murf"))
    with patch.object(isolated, "get", wraps=isolated.get) as lookup:
        result = resolve_fallbacks(
            fallback("tts", "murf")
            | {"STT_MODEL": "invalid", "STT_ALLOW_BATCH": "invalid"},
            {"tts": primary},
            isolated,
        )
    assert result[0].provider == "murf"
    assert all(call.args[0] == "tts" for call in lookup.call_args_list)


def test_application_components_are_resolved_once_even_with_three_fallbacks():
    values = environment()
    for category, name in (("stt", "assemblyai"), ("llm", "gemini"), ("tts", "murf")):
        values.update(fallback(category, name))
    with (
        patch.object(usecases, "get", wraps=usecases.get) as profile,
        patch.object(
            InfrastructureSettings, "from_env", wraps=InfrastructureSettings.from_env
        ) as infrastructure,
        patch.object(
            ObservabilitySettings, "from_env", wraps=ObservabilitySettings.from_env
        ) as telemetry,
    ):
        assert len(Settings.from_env(values).fallbacks) == 3
    assert profile.call_count == infrastructure.call_count == telemetry.call_count == 1


def test_provider_module_import_does_not_import_application_infrastructure_or_livekit():
    code = """
import sys
from app.config.providers import resolve_provider
config = resolve_provider('llm', {
    'GOOGLE_API_KEY': 'synthetic', 'LLM_PROVIDER': 'gemini'
})
assert config.provider == 'gemini'
for prefix in ('app.config.settings', 'app.config.infrastructure', 'app.observability',
               'app.usecases', 'livekit', 'sqlalchemy', 'redis'):
    loaded = any(
        name == prefix or name.startswith(prefix + '.') for name in sys.modules
    )
    assert not loaded, prefix
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("category", ["stt", "llm", "tts"])
def test_standalone_resolution_requires_only_selected_credentials(
    category, monkeypatch
):
    spec = registry.list(category)[0]
    monkeypatch.setenv(spec.api_key_env, "must-not-read-process")
    values = {
        f"{category.upper()}_PROVIDER": spec.name,
        spec.api_key_env: "selected-key",
        "STT_ALLOW_BATCH": "true" if category == "stt" else "false",
    }
    config = resolve_provider(category, values)
    assert config.api_key == "selected-key"
    assert config == getattr(Settings.from_env(environment(**values)), category)
    values.pop(spec.api_key_env)
    with pytest.raises(ConfigurationError, match=spec.api_key_env):
        resolve_provider(category, values)


@pytest.mark.parametrize(
    "capability,values,message",
    [
        ("streaming", {}, "Batch STT requires"),
        (
            "interim_transcription",
            {"STT_REQUIRE_INTERIM": "true"},
            "interim transcription",
        ),
        ("turn_detection", {"TURN_DETECTION": "stt"}, "provider turn detection"),
    ],
)
def test_stt_primary_and_fallback_capability_checks_use_injected_metadata(
    capability, values, message
):
    isolated = ProviderRegistry()
    spec = registry.get("stt", "assemblyai")
    altered = replace(
        spec, capabilities=replace(spec.capabilities, **{capability: False})
    )
    isolated.register(altered)
    primary = resolve_provider(
        "stt", {"STT_PROVIDER": spec.name, spec.api_key_env: "key"}, isolated
    )
    with pytest.raises(ConfigurationError, match=message):
        resolve_stt_requirements(values, primary, isolated)
    with pytest.raises(ConfigurationError, match=message):
        resolve_fallbacks(
            values | fallback("stt", spec.name), {"stt": primary}, isolated
        )


def test_nonstreaming_llm_and_tts_metadata_cannot_be_used_as_fallbacks():
    for category in ("llm", "tts"):
        spec = registry.list(category)[0]
        isolated = ProviderRegistry()
        isolated.register(
            replace(spec, capabilities=replace(spec.capabilities, streaming=False))
        )
        primary = getattr(Settings.from_env(environment()), category)
        with pytest.raises(
            ConfigurationError, match="Batch providers cannot be realtime fallbacks"
        ):
            resolve_fallbacks(
                fallback(category, spec.name), {category: primary}, isolated
            )


def test_resolvers_do_not_mutate_inputs_or_primary_credentials():
    primary = Settings.from_env(environment()).llm
    values = fallback("llm", "gemini")
    before = dict(values)
    resolve_fallbacks(values, {"llm": primary})
    assert values == before
    assert primary.api_key == "synthetic-llm-key"


def test_blank_fallback_provider_ignores_other_fallback_fields():
    assert (
        resolve_fallbacks(
            fallback("llm", "   ", API_KEY="", COMPATIBLE="invalid", MODEL="invalid"),
            {},
        )
        == ()
    )


def test_aggregate_collection_and_standalone_errors_share_required_key_labels():
    missing = ["LIVEKIT_API_KEY"]
    config = resolve_provider("llm", {}, missing=missing)
    assert config.api_key == ""
    assert missing == ["LIVEKIT_API_KEY", "LLM_API_KEY (or OPENAI_API_KEY)"]
    with pytest.raises(ConfigurationError, match="LLM_API_KEY"):
        resolve_provider("llm", {})


@pytest.mark.parametrize("category", ["stt", "llm", "tts"])
def test_unrecognized_selection_errors_do_not_echo_pasted_secrets(category):
    value = "accidentally-pasted-private-credential"
    with pytest.raises(ConfigurationError) as primary_error:
        resolve_provider(category, {f"{category.upper()}_PROVIDER": value})
    with pytest.raises(ProviderError) as fallback_error:
        resolve_fallbacks(fallback(category, value), {})
    assert value not in str(primary_error.value)
    assert value not in str(fallback_error.value)


def test_legacy_imports_keep_type_and_error_identity():
    from app.config.settings import ProviderConfig as LegacyConfig
    from app.config.validation import ConfigurationError as SharedError

    assert LegacyConfig is ProviderConfig
    assert SharedError is ConfigurationError


def test_app_still_validates_infrastructure_and_usecase_policy_with_fallback():
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        Settings.from_env(
            environment(
                PERSISTENCE_ENABLED="true",
                DATABASE_URL="invalid",
                **fallback("llm", "gemini"),
            )
        )
    profile = replace(usecases.get(), allowed_providers={"llm": ("openai_compatible",)})
    with patch.dict(usecases.entries, {profile.id: profile}):
        with pytest.raises(ConfigurationError, match="does not allow selected llm"):
            Settings.from_env(environment(**fallback("llm", "gemini")))
