"""Catalog/profile resolution is deterministic, offline and secret-safe."""

import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from app.config.catalogs import Catalog, read_yaml, register_catalogs
from app.config.profiles import VoiceProfile, resolve_voice_profile
from app.config.settings import ConfigurationError, Settings
from app.providers.doctor import offline_report
from app.providers.registry import ProviderRegistry, registry


def environment(**values):
    return {
        "LIVEKIT_URL": "ws://localhost:7880",
        "LIVEKIT_API_KEY": "synthetic-livekit",
        "LIVEKIT_API_SECRET": "synthetic-secret",
        "GROQ_API_KEY": "synthetic-groq",
        "GOOGLE_API_KEY": "synthetic-google",
        "NVIDIA_API_KEY": "synthetic-nvidia",
        "VOICE_PROFILE": "groq_gemini",
        **values,
    }


@pytest.mark.parametrize(
    "name,llm,stt,batch,interim",
    [
        ("groq_gemini", "groq", "groq", True, False),
        ("gemini_only", "gemini", "gemini", False, True),
        ("nvidia_gemini", "nvidia", "groq", True, False),
    ],
)
def test_profiles_resolve_without_manual_models(name, llm, stt, batch, interim):
    config = Settings.from_env(environment(VOICE_PROFILE=name))
    assert config.stt.provider == stt and config.llm.provider == llm
    assert config.tts.model == "gemini-3.8-flash-tts" and config.tts.voice == "Kore"
    assert config.allow_batch_stt is batch and config.require_interim is interim
    assert config.google_api_version == "v1beta" and config.turn_detection == "vad"
    assert not config.fallbacks and not config.mcp_enabled
    assert (
        not config.infrastructure.persistence_enabled
        and not config.infrastructure.redis_enabled
    )


def test_nvidia_uses_dedicated_key_not_stale_primary_llm_key():
    config = Settings.from_env(
        environment(VOICE_PROFILE="nvidia_gemini", LLM_API_KEY="wrong-groq-key")
    )
    assert config.llm.api_key == "synthetic-nvidia"
    assert config.llm.base_url == "https://integrate.api.nvidia.com/v1"
    assert config.llm.model == "meta/llama-3.3-70b-instruct"
    assert config.stt.api_key == "synthetic-groq"


@pytest.mark.parametrize(
    "name", ["absent_profile", "../private", "secret/key", "unknown-profile"]
)
def test_unknown_profiles_are_rejected_without_echo(name):
    with pytest.raises(ConfigurationError) as caught:
        Settings.from_env(environment(VOICE_PROFILE=name))
    assert name not in str(caught.value)


@pytest.mark.parametrize("key", ["GROQ_API_KEY", "GOOGLE_API_KEY"])
def test_missing_selected_credentials(key):
    with pytest.raises(ConfigurationError, match=key):
        Settings.from_env(environment(**{key: ""}))


def test_legacy_no_profile_remains_unchanged():
    from tests.test_providers import environment as legacy

    config = Settings.from_env(legacy())
    assert (config.stt.provider, config.llm.provider, config.tts.provider) == (
        "deepgram",
        "openai_compatible",
        "cartesia",
    )
    assert not config.voice_profile


def test_stale_env_conflicts_fail_closed_then_explicit_override_wins():
    values = environment(TTS_MODEL="gemini-3.1-flash-tts-preview")
    before = dict(values)
    with pytest.raises(ConfigurationError, match="TTS_MODEL"):
        Settings.from_env(values)
    config = Settings.from_env(values | {"VOICE_PROFILE_ALLOW_OVERRIDES": "true"})
    assert config.tts.model == "gemini-3.1-flash-tts-preview"
    assert config.profile_overrides == ("TTS_MODEL",) and values == before


def test_blank_overrides_do_not_erase_profile_defaults():
    config = Settings.from_env(
        environment(STT_MODEL=" ", LLM_BASE_URL="", TTS_VOICE="")
    )
    assert config.stt.model == "whisper-large-v3-turbo"
    assert (
        config.llm.base_url == "https://api.groq.com/openai/v1"
        and config.tts.voice == "Kore"
    )


@pytest.mark.parametrize(
    "values,message",
    [
        ({"STT_REQUIRE_INTERIM": "true"}, "interim"),
        ({"STT_ALLOW_BATCH": "false"}, "Batch STT"),
        ({"STT_PROVIDER": "missing"}, "unsupported provider"),
        ({"TTS_VOICE": "imaginary"}, "TTS_VOICE"),
        ({"STT_MODEL": "whisper-1"}, "STT_MODEL"),
        ({"LLM_BASE_URL": "https://name:private@host/v1"}, "valid URL"),
    ],
)
def test_incompatible_overrides_still_rejected(values, message):
    with pytest.raises(ConfigurationError, match=message):
        Settings.from_env(environment(VOICE_PROFILE_ALLOW_OVERRIDES="true", **values))


def test_switch_to_generic_adapter_preserves_explicit_model_and_endpoint():
    config = Settings.from_env(
        environment(
            VOICE_PROFILE_ALLOW_OVERRIDES="true",
            LLM_PROVIDER="openai_compatible",
            LLM_API_KEY="local-key",
            LLM_MODEL="served-model",
            LLM_BASE_URL="http://localhost:8000/v1",
        )
    )
    assert config.llm.model == "served-model" and config.llm.api_key == "local-key"


def test_model_specific_capabilities_and_fallback_restrictions():
    from app.config.providers import resolve_provider, resolve_stt_requirements

    spec = registry.get("stt", "groq")
    altered = dict(spec.model_metadata)
    model = altered["whisper-large-v3"]
    altered["whisper-large-v3"] = replace(
        model,
        capabilities=replace(
            model.capabilities, streaming=True, interim_transcription=True
        ),
    )
    isolated = ProviderRegistry()
    isolated.register(replace(spec, model_metadata=altered))
    values, _ = resolve_voice_profile(
        environment(STT_MODEL="whisper-large-v3", VOICE_PROFILE_ALLOW_OVERRIDES="true"),
        {},
        registry,
    )
    config = resolve_provider("stt", values, isolated)
    resolve_stt_requirements({"STT_REQUIRE_INTERIM": "true"}, config, isolated)
    with pytest.raises(ConfigurationError, match="interim"):
        resolve_stt_requirements(
            {"STT_ALLOW_BATCH": "true", "STT_REQUIRE_INTERIM": "true"},
            replace(config, model="whisper-large-v3-turbo"),
            isolated,
        )
    with pytest.raises(ConfigurationError, match="operator verification"):
        Settings.from_env(
            environment(
                LLM_FALLBACK_PROVIDER="nvidia", LLM_FALLBACK_API_KEY="synthetic"
            )
        )
    with pytest.raises(ConfigurationError, match="Batch providers"):
        Settings.from_env(
            environment(
                TTS_FALLBACK_PROVIDER="gemini",
                TTS_FALLBACK_API_KEY="synthetic",
                TTS_FALLBACK_COMPATIBLE="true",
            )
        )


def test_safe_repr_and_offline_report_never_include_keys():
    config = Settings.from_env(environment())
    with patch("socket.create_connection", side_effect=AssertionError("No network")):
        report = offline_report(config)
    serialized = json.dumps(report) + repr(config)
    for key, value in environment().items():
        if "KEY" in key or "SECRET" in key:
            assert value not in serialized
    assert report["result"] == "configuration_valid_inference_not_tested"
    assert all(s["inference"] == "not_tested" for s in report["stages"])


@pytest.mark.parametrize(
    "raw",
    [
        "version: 1\nname: first\nname: second\n",
        "version: 1\nname: test\napi_key: private\n",
        "name: &name profile\nversion: 1\nllm: *name\n",
    ],
)
def test_invalid_yaml_is_sanitized(tmp_path, raw):
    file = tmp_path / "profile.yaml"
    file.write_text(raw, encoding="utf-8")
    with pytest.raises(ConfigurationError) as caught:
        read_yaml(file, VoiceProfile)
    assert "private" not in str(caught.value)


def test_catalogs_repopulate_same_registry_and_reject_bad_metadata(tmp_path):
    from app.config.catalogs import CONFIG_ROOT

    isolated = ProviderRegistry()
    register_catalogs(isolated)
    assert isolated.list("stt") == registry.list("stt")
    file = tmp_path / "bad.yaml"
    file.write_text("version: 1\nname: private\napi_key: private\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        register_catalogs(ProviderRegistry(), tmp_path)
    assert set(
        read_yaml(CONFIG_ROOT / "providers/nvidia.yaml", Catalog).categories
    ) == {"llm", "tts"}
