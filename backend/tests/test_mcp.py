import asyncio
import json
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("mcp", reason="Install optional MCP extra for real transport tests")
pytest.importorskip("jsonschema")

from app.agents.orchestrator import Orchestrator
from app.mcp.client import LiveKitMCPClient
from app.mcp.config import BACKEND_ROOT, MCPConfig, ServerConfig, load_config
from app.mcp.connection_manager import ConnectionManager
from app.mcp.registry import MCPRegistry, tool_name
from app.tools.base import ToolFailure
from app.usecases.registry import registry as usecases


def clock_config():
    # Allow Windows cold interpreter/antivirus startup in transport fixtures.
    return (
        load_config("mcp.demo.example.json")
        .servers[0]
        .model_copy(update={"connect_timeout_seconds": 20})
    )


def prepared_registry(config):
    names = frozenset(tool_name(config.id, alias) for alias in config.approved_tools)
    registry = MCPRegistry(MCPConfig(servers=[config]), names)
    orchestrator = Orchestrator(
        use_case=usecases.get(),
        tool_definitions=tuple(registry.definitions.values()),
        allowlist=names,
        deferred_tools=names,
    )
    orchestrator.state.actor_id = "human"
    registry.orchestrator = orchestrator
    orchestrator.external_tools = registry
    return registry, orchestrator


@contextmanager
def http_server(port):
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "app.mcp.demo_server",
            "--transport",
            "streamable-http",
            "--port",
            str(port),
        ],
        cwd=BACKEND_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and process.poll() is None:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("Local HTTP MCP fixture did not start")
        yield process
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@pytest.mark.parametrize("transport", ["stdio", "streamable_http"])
def test_real_transport_discovery_execution_and_shared_permissions(transport):
    async def run(config):
        registry, orchestrator = prepared_registry(config)
        agent = SimpleNamespace(update_tools=AsyncMock())
        assert orchestrator.tools() == []  # Not exposed before discovery.
        try:
            aliases = await registry.manager.discover(config.id)
            assert aliases == {"get_current_time"}
            name = tool_name(config.id, "get_current_time")
            await orchestrator.set_tool_availability(agent, {name}, {name})
            assert [tool.id for tool in orchestrator.tools()] == [name]
            result = await orchestrator.executor.execute(name, {}, call_id="real")
            assert result.status == "completed"
            assert "+00:00" in result.data["data"]["iso_time"]
            invalid = await orchestrator.executor.execute(
                name, {"unexpected": True}, call_id="invalid"
            )
            assert invalid.code == "invalid_arguments"
            orchestrator.state.permissions = frozenset()
            denied = await orchestrator.executor.execute(name, {}, call_id="denied")
            assert denied.status == "denied"
        finally:
            await orchestrator.executor.close()
            await registry.aclose()

    config = clock_config()
    if transport == "stdio":
        asyncio.run(run(config))
    else:
        port = free_port()
        config = config.model_copy(
            update={
                "transport": "streamable_http",
                "command": None,
                "args": [],
                "url": f"http://127.0.0.1:{port}/mcp",
                "allow_http_loopback": True,
            }
        )
        with http_server(port):
            asyncio.run(run(config))


def test_pinned_schema_drift_and_unapproved_tools_are_not_exposed():
    async def run():
        config = clock_config()
        policy = config.approved_tools["get_current_time"].model_copy(
            update={"input_schema": {"type": "object", "properties": {}}}
        )
        config = config.model_copy(
            update={"approved_tools": {"get_current_time": policy}}
        )
        client = LiveKitMCPClient(config)
        try:
            assert await client.discover() == set()
            assert client.toolset.tools == []
            with pytest.raises(ToolFailure):
                await client.call("get_current_time", {})
        finally:
            await client.aclose()

    asyncio.run(run())


def test_sensitive_mcp_tool_requires_actual_human_approval_and_no_raw_browser_result():
    async def run():
        config = clock_config()
        policy = config.approved_tools["get_current_time"].model_copy(
            update={
                "sensitive": True,
                "confirmation_summary": "Read the external demo clock",
            }
        )
        config = config.model_copy(
            update={"approved_tools": {"get_current_time": policy}}
        )
        registry, orchestrator = prepared_registry(config)
        events = []
        orchestrator.event_sink = events.append
        name = tool_name(config.id, "get_current_time")
        orchestrator.allowlist = frozenset({name})
        orchestrator.executor.allowlist = orchestrator.allowlist
        try:
            task = asyncio.create_task(
                orchestrator.executor.execute(name, {}, call_id="confirm")
            )
            for _ in range(30):
                await asyncio.sleep(0)
                if orchestrator.executor.confirmations.pending:
                    break
            assert registry.manager.clients[config.id].toolset is None
            token = next(iter(orchestrator.executor.confirmations.pending))
            orchestrator.executor.confirmations.resolve(token, "human", True)
            result = await task
            assert result.status == "completed"
            assert any(e.get("status") == "confirmation_required" for e in events)
            assert not any(e["type"] == "result" for e in events)
            assert "iso_time" not in json.dumps(events)
        finally:
            await orchestrator.executor.close()
            await registry.aclose()

    asyncio.run(run())


def fixture_config(tool, **updates):
    config = clock_config()
    policy = config.approved_tools["get_current_time"].model_dump()
    policy.update(
        remote_name=tool,
        input_schema={"properties": {}, "type": "object", "title": f"{tool}Arguments"},
    )
    if tool == "leak":
        policy.update(
            output_schema={
                "type": "object",
                "properties": {"safe": {"type": "string"}},
                "required": ["safe"],
                "additionalProperties": False,
            },
            llm_fields=["safe"],
        )
    if tool == "slow":
        policy.update(
            output_schema={
                "type": "object",
                "properties": {"done": {"type": "boolean"}},
                "required": ["done"],
            },
            llm_fields=["done"],
        )
    data = config.model_dump()
    data.update(
        args=[str(Path(__file__).with_name("mcp_test_server.py"))],
        approved_tools={tool: policy},
        **updates,
    )
    return ServerConfig.model_validate(data)


def test_local_output_validation_filtering_and_credential_disclosure(
    monkeypatch,
):
    monkeypatch.setenv("MCP_TEST_TOKEN", "synthetic-credential-never-a-real-secret")

    async def run():
        for tool in ("broken", "leak"):
            config = fixture_config(tool, env={"TEST_ONLY_TOKEN": "MCP_TEST_TOKEN"})
            manager = ConnectionManager([config])
            try:
                assert await manager.discover(config.id) == {tool}
                assert [t.id for t in manager.clients[config.id].toolset.tools] == [
                    tool
                ]
                with pytest.raises(ToolFailure) as error:
                    await manager.call(config.id, tool, {})
                assert "synthetic-credential" not in str(error.value)
                with pytest.raises(ToolFailure):
                    await manager.call(config.id, "hidden", {})
            finally:
                await manager.aclose()

    asyncio.run(run())


def test_real_request_timeout_and_unavailable_server_fail_closed():
    async def run():
        config = fixture_config("slow", request_timeout_seconds=0.15)
        manager = ConnectionManager([config])
        try:
            assert await manager.discover(config.id) == {"slow"}
            with pytest.raises(ToolFailure):
                await manager.call(config.id, "slow", {})
        finally:
            await manager.aclose()
        config = clock_config().model_copy(
            update={
                "command": str(BACKEND_ROOT / "missing-command.exe"),
                "connect_timeout_seconds": 0.2,
            }
        )
        manager = ConnectionManager([config])
        try:
            assert await manager.discover(config.id) == set()
        finally:
            await manager.aclose()

    asyncio.run(run())


def test_multiple_servers_background_activation_and_reconnect_without_call_replay():
    async def run():
        one = clock_config().model_copy(
            update={"health_interval_seconds": 0.1, "reconnect_interval_seconds": 0.1}
        )
        two = one.model_copy(update={"id": "second"})
        manager = ConnectionManager([one, two])
        available = {}

        async def changed(server_id, aliases):
            available[server_id] = aliases

        manager.start(changed)
        try:
            for _ in range(200):
                if all(available.get(i) for i in (one.id, two.id)):
                    break
                await asyncio.sleep(0.05)
            assert set(available) == {one.id, two.id}
            # Close the real stdio session/process: the monitor must create a new one.
            async with manager.locks[one.id]:
                old = manager.clients[one.id].toolset
                await manager.clients[one.id].aclose()
            manager.wake[one.id].set()
            for _ in range(200):
                client = manager.clients[one.id]
                if (
                    client.toolset is not None
                    and client.toolset is not old
                    and client.approved
                ):
                    break
                await asyncio.sleep(0.05)
            assert manager.clients[one.id].toolset is not old
            assert "iso_time" in await manager.call(one.id, "get_current_time", {})
        finally:
            await manager.aclose()
        assert manager.closed and not manager.tasks

    asyncio.run(run())


def test_real_bootstrap_activation_and_native_agent_tool_call(monkeypatch):
    from app.agents.orchestrator import MainAgent
    from app.bootstrap import build_orchestrator

    # Match the other real-transport fixtures: cold Windows subprocess startup
    # under a concurrent frontend build can exceed the production 5s default.
    config = MCPConfig(servers=[clock_config()])
    monkeypatch.setattr("app.mcp.config.load_config", lambda path: config)

    async def run():
        settings = SimpleNamespace(
            mcp_enabled=True,
            mcp_config_file="mcp.demo.example.json",
            tool_allowlist=("get_current_time", "mcp_clock_get_current_time"),
            instructions="Test",
        )
        orchestrator = build_orchestrator(settings)
        orchestrator.state.actor_id = "human"
        registry = orchestrator.external_tools
        assert [tool.id for tool in orchestrator.tools()] == ["get_current_time"]
        assert registry.manager.clients["clock"].toolset is None
        agent = MainAgent(settings, orchestrator)
        registry.start(agent)
        try:
            async with asyncio.timeout(30):
                while "mcp_clock_get_current_time" not in orchestrator.allowlist:
                    await asyncio.sleep(0.05)
            tool = next(
                t for t in orchestrator.tools() if t.id == "mcp_clock_get_current_time"
            )

            async def wait(tasks):
                await asyncio.gather(*tasks)

            context = SimpleNamespace(
                function_call=SimpleNamespace(call_id="native-mcp"),
                speech_handle=SimpleNamespace(
                    interrupted=False, wait_if_not_interrupted=wait
                ),
            )
            result = await tool({}, context)
            assert result["status"] == "completed"
            assert "+00:00" in result["data"]["data"]["iso_time"]
        finally:
            await orchestrator.executor.close()
            await registry.aclose()

    asyncio.run(run())


def test_external_write_policy_injects_stable_key_and_stays_behind_confirmation():
    async def run():
        config = load_config("mcp.external.example.json")
        business = next(
            server for server in config.servers if server.id == "business"
        ).model_copy(update={"enabled": True})
        registry, orchestrator = prepared_registry(business)
        orchestrator.executor.allowlist = frozenset(registry.definitions)
        orchestrator.state.permissions = frozenset({"requests:create"})
        registry.manager.call = AsyncMock(
            return_value={}
        )  # Test only, not a working business server.
        name = next(iter(registry.definitions))
        parameters = registry.definitions[name].input_schema.model_json_schema()
        assert "operation_id" not in parameters["properties"]
        task = asyncio.create_task(
            orchestrator.executor.execute(
                name,
                {"customer_ref": "test-customer", "request_type": "callback"},
                call_id="write-test",
                idempotency_key="stable-business-key",
            )
        )
        for _ in range(30):
            await asyncio.sleep(0)
            if orchestrator.executor.confirmations.pending:
                break
        registry.manager.call.assert_not_awaited()
        token = next(iter(orchestrator.executor.confirmations.pending))
        orchestrator.executor.confirmations.resolve(token, "human", True)
        assert (await task).status == "completed"
        arguments = registry.manager.call.call_args.args[2]
        assert arguments["operation_id"] == "stable-business-key"
        await registry.aclose()

    asyncio.run(run())
