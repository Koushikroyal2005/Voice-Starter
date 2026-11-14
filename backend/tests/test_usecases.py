import asyncio
import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.agents.instructions import DEFAULT_INSTRUCTIONS
from app.agents.orchestrator import MainAgent
from app.bootstrap import build_orchestrator
from app.config.settings import ConfigurationError, Settings
from app.tools.base import PublicCard
from app.tools.common.calculator import CALCULATOR_TOOL
from app.usecases.base import ConversationPolicies, apply_tool_policies
from app.usecases.examples.education.services import StudyPlanInput, StudyPlanService
from app.usecases.registry import UseCaseRegistry, registry


def env(**values):
    return {
        "LIVEKIT_URL": "wss://example.test",
        "LIVEKIT_API_KEY": "backend-livekit-key",
        "LIVEKIT_API_SECRET": "backend-secret",
        "DEEPGRAM_API_KEY": "backend-stt-key",
        "LLM_API_KEY": "backend-llm-key",
        "CARTESIA_API_KEY": "backend-tts-key",
        **values,
    }


def test_registry_defaults_and_validation():
    assert registry.get().id == "general_assistant"
    assert registry.get("").id == "general_assistant"
    with pytest.raises(ValueError, match="Unsupported"):
        registry.get("os.system")
    isolated = UseCaseRegistry()
    isolated.register(registry.get())
    with pytest.raises(ValueError, match="already registered"):
        isolated.register(registry.get())
    with pytest.raises(ValueError, match="provider options"):
        replace(registry.get(), provider_defaults={"LLM_API_KEY": "secret"})


def test_default_assistant_keeps_existing_prompt_tools_and_credentials():
    settings = Settings.from_env(env())
    assert settings.instructions == DEFAULT_INSTRUCTIONS
    orchestrator = build_orchestrator(settings)
    assert len(orchestrator.tools()) == 3
    assert orchestrator.public_use_case.name == "Voice Workbench"
    assert orchestrator.external_tools is None
    MainAgent(settings, orchestrator)


@pytest.mark.parametrize("name", tuple(registry.entries))
def test_each_example_composes_one_native_agent_without_network(name):
    settings = Settings.from_env(env(USE_CASE=name))
    orchestrator = build_orchestrator(settings)
    agent = MainAgent(settings, orchestrator)
    assert agent is not None and orchestrator.use_case.id == name
    public = orchestrator.public_use_case.model_dump_json()
    assert set(json.loads(public)) == {
        "schema_version",
        "id",
        "name",
        "description",
        "languages",
        "result_card_types",
        "notice",
    }
    for secret in (
        "backend-secret",
        "backend-llm-key",
        "backend-stt-key",
        "backend-tts-key",
    ):
        assert secret not in public
    assert "instructions" not in json.loads(public)


def test_settings_overrides_and_restrictions():
    settings = Settings.from_env(
        env(
            USE_CASE="education",
            AGENT_INSTRUCTIONS="New prompt",
            TOOL_ALLOWLIST="create_study_plan",
        )
    )
    assert settings.instructions == "New prompt"
    assert len(build_orchestrator(settings).tools()) == 1
    assert not build_orchestrator(
        Settings.from_env(env(USE_CASE="education", TOOL_ALLOWLIST=""))
    ).tools()
    for values in (
        {"USE_CASE": "missing"},
        {"USE_CASE": "finance", "STT_LANGUAGE": "te"},
        {"USE_CASE": "finance", "TOOL_ALLOWLIST": "create_study_plan"},
        {
            "USE_CASE": "healthcare",
            "STT_PROVIDER": "whisper",
            "STT_ALLOW_BATCH": "true",
            "OPENAI_API_KEY": "key",
        },
    ):
        with pytest.raises(ConfigurationError):
            Settings.from_env(env(**values))
    with pytest.raises(ConfigurationError, match="transcript"):
        Settings.from_env(
            env(
                USE_CASE="healthcare",
                PERSISTENCE_ENABLED="true",
                PERSIST_TRANSCRIPTS="true",
                DATABASE_URL="postgresql+asyncpg://local/db",
                DATA_REDACTION_KEY="s" * 32,
                PERSISTENCE_OWNER_NAMESPACE="test",
            )
        )


def test_education_service_and_real_executor_public_card():
    async def check():
        settings = Settings.from_env(env(USE_CASE="education"))
        orchestrator = build_orchestrator(settings)
        orchestrator.state.actor_id = "linked-user"
        events = []
        orchestrator.event_sink = events.append
        result = await orchestrator.executor.execute(
            "create_study_plan",
            {"topic": "Fractions", "days": 3, "minutes_per_day": 20},
            call_id="plan1",
        )
        assert result.status == "completed"
        public = [e for e in events if e["type"] == "result"][0]
        assert public["card_type"] == "study_plan"
        assert public["data"]["total_minutes"] == 60
        assert len(public["data"]["sessions"]) == 3
        assert "StudyPlanService" not in json.dumps(public)
        bad = await orchestrator.executor.execute(
            "create_study_plan", {"topic": "Fractions", "days": 1000}, call_id="bad"
        )
        assert bad.code == "invalid_arguments"
        await orchestrator.executor.close()

    asyncio.run(check())


def test_confirmation_policy_tightens_existing_executor(monkeypatch):
    profile = replace(
        registry.get("education"),
        id="education_approval",
        policies=ConversationPolicies(
            require_confirmation_for=("create_study_plan",), allow_side_effects=False
        ),
    )
    monkeypatch.setitem(registry.entries, profile.id, profile)

    async def check():
        orchestrator = build_orchestrator(Settings.from_env(env(USE_CASE=profile.id)))
        orchestrator.state.actor_id = "user"
        events = []
        orchestrator.event_sink = events.append
        task = asyncio.create_task(
            orchestrator.executor.execute(
                "create_study_plan",
                {"topic": "Fractions", "days": 2},
                call_id="approval",
            )
        )
        for _ in range(10):
            await asyncio.sleep(0)
            if orchestrator.executor.confirmations.pending:
                break
        event = next(e for e in events if e.get("status") == "confirmation_required")
        orchestrator.executor.confirmations.resolve(
            event["confirmation_id"], "user", False
        )
        result = await task
        assert result.code == "confirmation_denied"
        await orchestrator.executor.close()

    asyncio.run(check())


def test_confirmation_requires_explicit_reviewed_summary():
    profile = replace(
        registry.get(),
        policies=ConversationPolicies(require_confirmation_for=(CALCULATOR_TOOL.name,)),
    )
    with pytest.raises(ValueError, match="reviewed"):
        apply_tool_policies(profile, (CALCULATOR_TOOL,))

    write = replace(
        CALCULATOR_TOOL,
        side_effects=True,
        sensitive=True,
        cancellation_safe=False,
        permission="tools:write",
        confirmation_summary=lambda _args: "Reviewed test-only write metadata",
    )
    with pytest.raises(ValueError, match="side-effecting"):
        apply_tool_policies(registry.get("education"), (write,))


def test_domain_service_rejects_invalid_schema():
    with pytest.raises(ValidationError):
        StudyPlanInput(topic=" ", days=1)
    request = StudyPlanInput(topic="Algebra", days=7, minutes_per_day=120)
    assert StudyPlanService().create(request).total_minutes == 840


def test_specialized_mcp_scope_is_explicit_and_deferred(monkeypatch):
    pytest.importorskip("mcp")
    profile = replace(
        registry.get("education"),
        id="education_mcp",
        default_tools=("create_study_plan", "mcp_clock_get_current_time"),
        mcp_servers=("clock",),
        mcp_tool_allowlist=("mcp_clock_get_current_time",),
        mcp_config_file="mcp.demo.example.json",
    )
    monkeypatch.setitem(registry.entries, profile.id, profile)
    settings = Settings.from_env(env(USE_CASE=profile.id, MCP_ENABLED="true"))
    orchestrator = build_orchestrator(settings)
    assert [s.id for s in orchestrator.external_tools.servers] == ["clock"]
    assert "mcp_clock_get_current_time" not in orchestrator.allowlist
    assert orchestrator.external_tools.manager.clients["clock"].toolset is None
    with pytest.raises(ConfigurationError, match="MCP tool"):
        Settings.from_env(
            env(USE_CASE="education", TOOL_ALLOWLIST="mcp_clock_get_current_time")
        )
    monkeypatch.setitem(registry.entries, profile.id, replace(profile, mcp_servers=()))
    with pytest.raises(ValueError, match="not registered"):
        build_orchestrator(settings)


def test_public_presentation_failure_does_not_retry_or_fail_completed_operation():
    async def check():
        profile = registry.get("education")
        definition = replace(
            profile.tool_factory()[0],
            public_card=lambda _: PublicCard(
                card_type="not_approved", data={"private": "do-not-disclose"}
            ),
        )
        monkey = pytest.MonkeyPatch()
        altered = replace(
            profile, id="bad_card_demo", tool_factory=lambda: (definition,)
        )
        monkey.setitem(registry.entries, altered.id, altered)
        try:
            orchestrator = build_orchestrator(
                Settings.from_env(env(USE_CASE=altered.id))
            )
            orchestrator.state.actor_id = "user"
            events = []
            orchestrator.event_sink = events.append
            result = await orchestrator.executor.execute(
                "create_study_plan",
                {"topic": "Fractions", "days": 1},
                call_id="presentation",
            )
            assert result.status == "completed"
            assert not [e for e in events if e["type"] == "result"]
            await orchestrator.executor.close()
        finally:
            monkey.undo()

    asyncio.run(check())
