import pytest

from app.agents.instructions import DEFAULT_INSTRUCTIONS
from app.config import settings as settings_module
from app.config.settings import ConfigurationError, Settings


def valid_env():
    return {
        "LIVEKIT_URL": "wss://example.livekit.cloud",
        "LIVEKIT_API_KEY": "test-key",
        "LIVEKIT_API_SECRET": "test-secret",
        "DEEPGRAM_API_KEY": "test-deepgram",
        "OPENAI_API_KEY": "test-openai",
        "CARTESIA_API_KEY": "test-cartesia",
    }


def test_tool_allowlist_defaults_and_explicit_empty_override():
    assert Settings.from_env(valid_env()).tool_allowlist == (
        "get_current_time",
        "calculate_expression",
        "time_and_calculate",
    )
    assert Settings.from_env(valid_env() | {"TOOL_ALLOWLIST": ""}).tool_allowlist == ()
    assert Settings.from_env(
        valid_env() | {"TOOL_ALLOWLIST": " get_current_time , "}
    ).tool_allowlist == ("get_current_time",)


def test_defaults_and_secrets_hidden():
    settings = Settings.from_env(valid_env())
    assert settings.agent_name == ""
    assert settings.instructions == DEFAULT_INSTRUCTIONS
    assert settings.stt.model == "nova-3"
    assert "test-secret" not in repr(settings)
    assert "test-openai" not in repr(settings)


@pytest.mark.parametrize("key", list(valid_env()))
@pytest.mark.parametrize("value", ["", "  "])
def test_missing_credentials(key, value):
    env = valid_env() | {key: value}
    with pytest.raises(ConfigurationError, match=key):
        Settings.from_env(env)


def test_all_missing_reported_without_values():
    with pytest.raises(ConfigurationError) as error:
        Settings.from_env({})
    for key in valid_env():
        assert key in str(error.value)


def test_custom_config_and_blank_defaults():
    settings = Settings.from_env(
        valid_env()
        | {
            "AGENT_NAME": "demo",
            "AGENT_INSTRUCTIONS": "Be concise.",
            "LLM_BASE_URL": "http://localhost:8080/v1",
            "LLM_MODEL": "custom",
            "STT_MODEL": " ",
        }
    )
    assert settings.agent_name == "demo"
    assert settings.instructions == "Be concise."
    assert settings.llm.model == "custom"
    assert settings.stt.model == "nova-3"


@pytest.mark.parametrize(
    "key,value",
    [
        ("LIVEKIT_URL", "https://example.com"),
        ("LIVEKIT_URL", "wss://"),
        ("LLM_BASE_URL", "invalid"),
        ("LLM_BASE_URL", "https://user:secret@example.com/v1"),
    ],
)
def test_invalid_urls(key, value):
    with pytest.raises(ConfigurationError, match=key):
        Settings.from_env(valid_env() | {key: value})


def test_dotenv_and_process_precedence(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(f"{key}={value}" for key, value in valid_env().items())
        + "\nAGENT_NAME=file-agent\n",
        encoding="utf-8",
    )
    for key in valid_env():
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AGENT_NAME", "process-agent")
    monkeypatch.setattr(settings_module, "ENV_FILE", env_file)
    loaded = settings_module.load_settings()
    assert loaded.agent_name == "process-agent"
    assert loaded.livekit_url == "wss://example.livekit.cloud"
