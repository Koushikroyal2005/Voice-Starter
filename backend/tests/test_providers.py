"""Selection and capability tests; all credentials are synthetic."""

import asyncio
from dataclasses import replace

import pytest
from livekit.agents import llm, stt, tts

from app.config.settings import ConfigurationError, ProviderConfig, Settings
from app.providers.factory import create_llm, create_provider, create_tts
from app.providers.registry import ProviderError, ProviderRegistry, registry


def environment():
    return {
        "LIVEKIT_URL": "wss://example.livekit.cloud",
        "LIVEKIT_API_KEY": "test-livekit",
        "LIVEKIT_API_SECRET": "test-secret",
        "DEEPGRAM_API_KEY": "test-deepgram",
        "LLM_API_KEY": "test-llm",
        "CARTESIA_API_KEY": "test-cartesia",
    }


def test_registration_and_duplicate_rejected():
    isolated = ProviderRegistry()
    spec = registry.get("stt", "deepgram")
    isolated.register(spec)
    assert isolated.get("stt", "deepgram") is spec
    assert isolated.list("stt") == (spec,)
    with pytest.raises(ProviderError, match="Duplicate"):
        isolated.register(spec)


@pytest.mark.parametrize("category", ["stt", "llm", "tts"])
def test_unsupported_provider(category):
    with pytest.raises(ConfigurationError, match=f"Unsupported {category}"):
        Settings.from_env(environment() | {f"{category.upper()}_PROVIDER": "missing"})


def test_defaults_and_key_precedence():
    settings = Settings.from_env(environment() | {"OPENAI_API_KEY": "legacy-key"})
    assert (settings.stt.provider, settings.llm.provider, settings.tts.provider) == (
        "deepgram",
        "openai_compatible",
        "cartesia",
    )
    assert settings.llm.api_key == "test-llm"
    assert "test-llm" not in repr(settings)


@pytest.mark.parametrize("category", ["stt", "llm", "tts"])
def test_all_registered_selections_require_only_their_key(category):
    for spec in registry.list(category):
        env = environment() | {
            f"{category.upper()}_PROVIDER": spec.name,
            spec.api_key_env: "selected-key",
            "STT_ALLOW_BATCH": "true",
        }
        settings = Settings.from_env(env)
        config = getattr(settings, category)
        assert config.provider == spec.name
        assert config.model == spec.model
        assert config.api_key == "selected-key"
        env.pop(spec.api_key_env)
        with pytest.raises(ConfigurationError, match=spec.api_key_env):
            Settings.from_env(env)


def test_unselected_keys_not_required():
    env = environment()
    env.pop("DEEPGRAM_API_KEY")
    env.pop("CARTESIA_API_KEY")
    env.pop("LLM_API_KEY")
    settings = Settings.from_env(
        env
        | {
            "STT_PROVIDER": "assemblyai",
            "ASSEMBLYAI_API_KEY": "test-assemblyai",
            "LLM_PROVIDER": "gemini",
            "GOOGLE_API_KEY": "test-google",
            "TTS_PROVIDER": "murf",
            "MURF_API_KEY": "test-murf",
        }
    )
    assert settings.stt.provider == "assemblyai"


def test_custom_endpoint_requires_model():
    with pytest.raises(ConfigurationError, match="LLM_MODEL"):
        Settings.from_env(environment() | {"LLM_BASE_URL": "http://localhost:8000/v1"})
    settings = Settings.from_env(
        environment()
        | {
            "LLM_BASE_URL": "http://localhost:8000/v1",
            "LLM_MODEL": "served-model",
        }
    )
    assert settings.llm.base_url == "http://localhost:8000/v1"


@pytest.mark.parametrize(
    "key,value",
    [
        ("STT_ALLOW_BATCH", "yes"),
        ("STT_REQUIRE_INTERIM", "1"),
        ("TURN_DETECTION", "imaginary"),
        ("LLM_BASE_URL", "https://example.com/v1?api_key=secret"),
        ("LIVEKIT_URL", "wss://[invalid"),
    ],
)
def test_invalid_configuration(key, value):
    with pytest.raises(ConfigurationError):
        Settings.from_env(environment() | {key: value})


def test_batch_mode_must_be_explicit_and_cannot_provide_interims_or_turns():
    env = environment() | {"STT_PROVIDER": "whisper", "OPENAI_API_KEY": "test-whisper"}
    with pytest.raises(ConfigurationError, match="STT_ALLOW_BATCH"):
        Settings.from_env(env)
    settings = Settings.from_env(env | {"STT_ALLOW_BATCH": "true"})
    assert settings.stt.model == "whisper-1"
    for incompatible in ({"STT_REQUIRE_INTERIM": "true"}, {"TURN_DETECTION": "stt"}):
        with pytest.raises(ConfigurationError):
            Settings.from_env(env | {"STT_ALLOW_BATCH": "true"} | incompatible)


def test_capability_requirements():
    registry.require("stt", "deepgram", "streaming")
    registry.require("stt", "assemblyai", "turn_detection")
    assert registry.get("stt", "whisper").capabilities.streaming is False
    for category, name, capability in (
        ("stt", "whisper", "interim_transcription"),
        ("llm", "openai_compatible", "tool_calling"),
        ("stt", "deepgram", "nonexistent"),
    ):
        with pytest.raises(ProviderError):
            registry.require(category, name, capability)


def test_factory_rejects_invalid_config_before_import():
    config = Settings.from_env(environment()).stt
    with pytest.raises(ProviderError, match="requires"):
        create_provider(replace(config, api_key=""))
    with pytest.raises(ProviderError, match="Unsupported"):
        create_provider(replace(config, provider="missing"))
    for factory in (create_llm, create_tts):
        with pytest.raises(ProviderError, match="Expected"):
            factory(config)


SPECS = [spec for category in ("stt", "llm", "tts") for spec in registry.list(category)]


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: f"{p.category}-{p.name}")
def test_real_plugin_construction_and_native_capabilities(spec):
    """Exercise every installed plugin, without stream/network calls."""
    config = ProviderConfig(
        spec.category,
        spec.name,
        spec.model,
        "test-only-key",
        base_url=spec.base_url,
        voice=spec.voice,
    )

    async def check():
        provider = create_provider(config)
        try:
            interface = {"stt": stt.STT, "llm": llm.LLM, "tts": tts.TTS}[spec.category]
            assert isinstance(provider, interface)
            plugin_name = {
                "whisper": "openai",
                "openai_compatible": "openai",
                "gemini": "google",
                "groq": "openai",
                "nvidia": "openai",
            }.get(spec.name, spec.name)
            if spec.name == "groq" and spec.category == "tts":
                assert provider.__class__.__module__ == "app.providers.tts.groq"
            else:
                assert provider.__class__.__module__.startswith(
                    f"livekit.plugins.{plugin_name}."
                )
            assert provider.model == config.model
            if spec.category != "llm":
                assert provider.capabilities.streaming == spec.capabilities.streaming
            if spec.category == "stt":
                assert (
                    provider.capabilities.interim_results
                    == spec.capabilities.interim_transcription
                )
            assert callable(
                provider.on
            )  # Native event emitter, not a text-only wrapper.
        finally:
            await provider.aclose()

    asyncio.run(check())


def test_provider_model_validation():
    with pytest.raises(ConfigurationError, match="STT_MODEL"):
        Settings.from_env(environment() | {"STT_MODEL": "flux-general-en"})


@pytest.mark.parametrize(
    "provider,language", [("cartesia", "es"), ("elevenlabs", "es"), ("murf", "es-ES")]
)
def test_tts_language_reaches_installed_plugin(provider, language):
    spec = registry.get("tts", provider)

    async def check():
        instance = create_tts(
            ProviderConfig(
                "tts",
                provider,
                spec.model,
                "test-key",
                voice=spec.voice,
                language=language,
            )
        )
        try:
            actual = (
                instance._opts.locale if provider == "murf" else instance._opts.language
            )
            assert str(actual) == language
        finally:
            await instance.aclose()

    asyncio.run(check())


def test_compatible_endpoint_options_reach_real_client():
    settings = Settings.from_env(
        environment()
        | {
            "LLM_BASE_URL": "http://localhost:8000/v1",
            "LLM_MODEL": "custom-model",
        }
    )

    async def check():
        provider = create_llm(settings.llm)
        try:
            assert str(provider._client.base_url) == "http://localhost:8000/v1/"
            assert provider._client.api_key == "test-llm"
            assert provider.model == "custom-model"
        finally:
            await provider.aclose()

    asyncio.run(check())
