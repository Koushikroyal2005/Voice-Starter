import builtins
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.bootstrap import build_orchestrator
from app.config.settings import ConfigurationError
from app.mcp.config import MCPConfig, ServerConfig, load_config


def http_config(**kwargs):
    return ServerConfig(
        id="maps",
        transport="streamable_http",
        url="https://example.invalid/mcp",
        **kwargs,
    )


def test_disabled_does_not_import_optional_dependencies_or_read_config(monkeypatch):
    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "mcp" or name.startswith("mcp.") or name == "jsonschema":
            raise AssertionError("Disabled MCP must not import optional packages")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    orchestrator = build_orchestrator(
        SimpleNamespace(
            mcp_enabled=False,
            mcp_config_file="does-not-exist.json",
            tool_allowlist=("get_current_time",),
        )
    )
    assert orchestrator.external_tools is None
    assert [t.id for t in orchestrator.tools()] == ["get_current_time"]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.invalid/mcp",
        "https://user:secret@example.invalid/mcp",
        "https://example.invalid/mcp?token=secret",
        "file:///secret",
        "https://example.invalid/mcp#secret",
    ],
)
def test_unsafe_urls_rejected(url):
    with pytest.raises(ConfigurationError):
        http_config().model_copy(update={"url": url}).endpoint()


def test_loopback_http_requires_explicit_opt_in_and_missing_credentials_are_clear(
    monkeypatch,
):
    config = http_config().model_copy(update={"url": "http://127.0.0.1:8765/mcp"})
    with pytest.raises(ConfigurationError):
        config.endpoint()
    assert (
        config.model_copy(update={"allow_http_loopback": True})
        .endpoint()
        .startswith("http://127.0.0.1")
    )
    monkeypatch.delenv("MISSING_MCP_ENDPOINT", raising=False)
    config = ServerConfig(
        id="test", transport="streamable_http", url_env="MISSING_MCP_ENDPOINT"
    )
    with pytest.raises(ConfigurationError, match="MISSING_MCP_ENDPOINT"):
        config.endpoint()


def test_credentials_are_references_only_and_headers_cannot_override_host():
    with pytest.raises(ValidationError):
        http_config(headers_env={"Authorization": "Bearer actual-secret"})
    with pytest.raises(ValidationError):
        http_config(headers_env={"Host": "MCP_HOST"})
    config = http_config(headers_env={"Authorization": "MCP_AUTHORIZATION"})
    assert "MCP_AUTHORIZATION" not in repr(config)
    with pytest.raises(ValidationError):
        ServerConfig(
            id="s", transport="stdio", command="python", url="https://example.invalid"
        )
    with pytest.raises(ValidationError):
        MCPConfig(servers=[config, config])


def test_invalid_config_does_not_echo_input_secrets(tmp_path):
    path = tmp_path / "mcp.json"
    # Fixture setup through a test API, not application credential storage.
    path.write_text(
        json.dumps({"servers": [{"secret": "do-not-echo-this"}]}), encoding="utf-8"
    )
    with pytest.raises(ConfigurationError) as error:
        load_config(str(path))
    assert "do-not-echo" not in str(error.value)


def test_demo_and_external_examples_are_valid_but_only_demo_is_enabled():
    demo = load_config("mcp.demo.example.json")
    assert len(demo.servers) == 1 and demo.servers[0].enabled
    external = load_config("mcp.external.example.json")
    assert {s.id for s in external.servers} == {"maps", "database", "business"}
    assert not any(s.enabled for s in external.servers)
