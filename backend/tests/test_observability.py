import asyncio
import json
import logging
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.bootstrap import build_orchestrator
from app.config.settings import ConfigurationError, Settings
from app.evaluation.run import SCENARIOS
from app.evaluation.scoring import summarize, transcription_scores
from app.observability.config import ObservabilitySettings
from app.observability.health import check_readiness
from app.observability.logging import JsonFormatter
from app.observability.runtime import Telemetry
from app.observability.session import SessionObserver
from app.reliability.retry import retry_probe
from app.tools.base import ToolFailure


class Session:
    def __init__(self):
        self.callbacks = {}

    def on(self, name):
        def bind(callback):
            self.callbacks[name] = callback
            return callback

        return bind

    def emit(self, name, **values):
        self.callbacks[name](NS(**values))


class Capture:
    def __init__(self):
        self.events = []

    def event(self, stage, **values):
        self.events.append({"stage": stage, **values})


def observer():
    session, capture = Session(), Capture()
    orchestrator = build_orchestrator(NS(tool_allowlist=("calculate_expression",)))
    monitor = SessionObserver(session, orchestrator, capture, monotonic=lambda: 20)
    return session, orchestrator, capture, monitor


def speech(session, start=100):
    session.emit(
        "user_state_changed",
        old_state="listening",
        new_state="speaking",
        created_at=start,
    )
    session.emit(
        "user_input_transcribed",
        transcript="private",
        is_final=False,
        created_at=start + 0.2,
    )
    session.emit(
        "user_state_changed",
        old_state="speaking",
        new_state="listening",
        created_at=start + 1,
    )
    session.emit(
        "user_input_transcribed",
        transcript="private",
        is_final=True,
        created_at=start + 1.1,
    )
    session.emit(
        "conversation_item_added",
        item=NS(
            id=f"u{start}",
            role="user",
            created_at=start,
            metrics={
                "stopped_speaking_at": start + 1,
                "transcription_delay": 0.1,
                "end_of_turn_delay": 0.5,
            },
        ),
    )


def answer(session, start=100):
    session.emit(
        "conversation_item_added",
        item=NS(
            id=f"a{start}",
            role="assistant",
            interrupted=False,
            metrics={
                "started_speaking_at": start + 2,
                "stopped_speaking_at": start + 3,
                "e2e_latency": 1,
                "llm_node_ttft": 0.2,
                "tts_node_ttfb": 0.3,
            },
        ),
    )


def test_agent_handoff_is_not_treated_as_a_speech_message():
    from livekit.agents.llm import AgentHandoff

    session, _, capture, monitor = observer()
    session.emit(
        "conversation_item_added", item=AgentHandoff(new_agent_id="synthetic-agent")
    )
    assert not capture.events
    assert monitor.current is None


def test_stage_timings_and_late_turn_correlation():
    session, _, capture, _ = observer()
    speech(session)
    first_turn = capture.events[0]["turn_id"]
    speech(session, 104)  # Late assistant completion must not attach to latest turn.
    answer(session, 100)
    stages = {e["stage"]: e for e in capture.events if e["turn_id"] == first_turn}
    assert stages["stt_interim"]["duration"] == pytest.approx(0.2)
    assert stages["stt_final"]["duration"] == 0.1
    assert stages["end_of_turn"]["duration"] == 0.5
    assert stages["llm_ttft"]["duration"] == 0.2
    assert stages["tts_first_audio"]["duration"] == 0.3
    assert stages["response_first_audio"]["duration"] == 1
    assert stages["full_turn"]["duration"] == 2
    assert "private" not in repr(capture.events)


def test_unknown_correlation_is_not_guessed_and_duplicates_ignored():
    session, _, capture, _ = observer()
    answer(session)
    count = len(capture.events)
    answer(session)
    assert len(capture.events) == count
    assert all(e["turn_id"] is None for e in capture.events)


@pytest.mark.parametrize("category", ["stt", "llm", "tts"])
def test_provider_errors_are_safe_and_user_visible(category):
    session, orchestrator, capture, _ = observer()
    outgoing = []
    orchestrator.event_sink = outgoing.append
    session.emit(
        "error",
        error=NS(
            type=f"{category}_error",
            recoverable=False,
            message="secret credential + private transcript",
        ),
    )
    assert capture.events[-1]["category"] == category
    assert outgoing[-1]["code"] == "provider_unavailable"
    assert "secret" not in repr(outgoing + capture.events)


def test_interruption_and_tool_duration():
    session, orchestrator, capture, monitor = observer()
    speech(session)
    monitor.monotonic = lambda: 10
    for status in ("selected", "running"):
        orchestrator.emit(
            {"type": "tool", "id": "c1", "name": "Calculator", "status": status}
        )
    monitor.monotonic = lambda: 10.7
    orchestrator.emit(
        {"type": "tool", "id": "c1", "name": "Calculator", "status": "completed"}
    )
    event = capture.events[-1]
    assert event["tool_call_id"] == "c1" and event["duration"] == pytest.approx(0.7)
    session.emit("agent_state_changed", new_state="speaking", created_at=102)
    session.emit(
        "user_state_changed",
        old_state="listening",
        new_state="speaking",
        created_at=103,
    )
    session.emit("agent_state_changed", new_state="listening", created_at=103.1)
    assert capture.events[-1]["stage"] == "interruption_stop"
    assert capture.events[-1]["duration"] == pytest.approx(0.1)


def test_opentelemetry_export_and_json_privacy():
    exporter, provider = InMemorySpanExporter(), TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry = Telemetry("session1", ObservabilitySettings(), provider=provider)
    telemetry.event("llm_ttft", turn_id="turn1", duration=0.2)
    telemetry.event("llm_ttft", duration=-1)  # Not a zero latency observation.
    telemetry.event("provider_error", category="tts", status="error")
    telemetry.close()
    spans = exporter.get_finished_spans()
    assert [s.name for s in spans].count("voice.llm_ttft") == 1
    assert spans[0].attributes["session_id"] == "session1"
    assert spans[0].parent.span_id == spans[-1].context.span_id
    record = logging.LogRecord("voice-starter", 20, "", 1, "Safe event", (), None)
    record.session_id, record.secret = "session1", "do-not-log"
    payload = JsonFormatter().format(record)
    assert "session1" in payload and "do-not-log" not in payload


def test_retry_exponential_jitter_bounds_and_cancellation():
    async def check():
        operation = AsyncMock(side_effect=[OSError(), OSError(), "ok"])
        sleep, jitter = AsyncMock(), lambda low, high: high
        assert await retry_probe(operation, sleep=sleep, jitter=jitter) == "ok"
        assert [c.args[0] for c in sleep.call_args_list] == [0.1, 0.2]
        operation = AsyncMock(side_effect=TimeoutError())
        with pytest.raises(TimeoutError):
            await retry_probe(operation, attempts=2, sleep=AsyncMock())
        assert operation.await_count == 2
        with pytest.raises(asyncio.CancelledError):
            await retry_probe(AsyncMock(side_effect=asyncio.CancelledError()))

    asyncio.run(check())


def environment():
    return {
        "LIVEKIT_URL": "wss://example.test",
        "LIVEKIT_API_KEY": "key",
        "LIVEKIT_API_SECRET": "secret",
        "DEEPGRAM_API_KEY": "stt-key",
        "LLM_API_KEY": "llm-key",
        "CARTESIA_API_KEY": "tts-key",
    }


def test_fallback_configuration_and_missing_compatibility():
    env = environment() | {"LLM_FALLBACK_PROVIDER": "openai_compatible"}
    with pytest.raises(ConfigurationError, match="API_KEY"):
        Settings.from_env(env)
    env["LLM_FALLBACK_API_KEY"] = "backup-key"
    with pytest.raises(ConfigurationError, match="COMPATIBLE"):
        Settings.from_env(env)
    env["LLM_FALLBACK_COMPATIBLE"] = "true"
    fallback = Settings.from_env(env).fallbacks[0]
    assert fallback.api_key == "backup-key" and fallback.category == "llm"
    with pytest.raises(ConfigurationError, match="language"):
        Settings.from_env(env | {"LLM_FALLBACK_LANGUAGE": "te"})
    with pytest.raises(ConfigurationError):
        Settings.from_env(environment() | {"PROVIDER_MAX_RETRIES": "99"})


def test_readiness_disabled_services_do_not_connect():
    result = asyncio.run(check_readiness(Settings.from_env(environment())))
    assert result == {
        "configuration": "ok",
        "postgresql": "disabled",
        "redis": "disabled",
    }


@pytest.mark.parametrize(
    "env",
    [
        {"SENTRY_DSN": "private-secret"},
        {"VOICE_OTLP_ENDPOINT": "https://secret:password@host/v1/traces"},
        {"PROVIDER_TIMEOUT_SECONDS": "nan"},
        {"PROVIDER_MAX_RETRIES": "1.5"},
    ],
)
def test_telemetry_config_rejects_invalid_values_without_echo(env):
    with pytest.raises(ValueError) as error:
        ObservabilitySettings.from_env(env)
    assert "private-secret" not in str(error.value)
    assert "password@host" not in str(error.value)


def test_scores_distinguish_unmeasured_and_reviewed():
    assert summarize([])["tool_success_rate"] is None
    assert summarize([])["intent_accuracy"] is None
    assert transcription_scores("hello world", "hello")["word_error_rate"] == 0.5
    assert (
        transcription_scores("రెండు plus three", "రెండు plus three")["word_error_rate"]
        == 0
    )


def test_optional_prometheus_real_endpoint_has_bounded_labels():
    pytest.importorskip("prometheus_client")
    from urllib.request import urlopen

    telemetry = Telemetry(
        "private-session", ObservabilitySettings(prometheus_enabled=True)
    )
    try:
        telemetry.event("llm_ttft", turn_id="private-turn", duration=0.2)
        with urlopen(
            f"http://127.0.0.1:{telemetry.http.server_port}/metrics", timeout=2
        ) as response:
            body = response.read().decode()
        assert "voice_stage_seconds_count" in body
        assert "private-session" not in body and "private-turn" not in body
    finally:
        telemetry.close()


def test_optional_sentry_sends_only_explicit_safe_events(monkeypatch):
    sentry = pytest.importorskip("sentry_sdk")
    from unittest.mock import Mock

    client = Mock()
    factory = Mock(return_value=client)
    monkeypatch.setattr(sentry, "Client", factory)
    telemetry = Telemetry("session", ObservabilitySettings(sentry_dsn="test-only-dsn"))
    telemetry.event("provider_error", category="tts", status="error")
    assert factory.call_args.kwargs["default_integrations"] is False
    assert factory.call_args.kwargs["send_default_pii"] is False
    event = client.capture_event.call_args.args[0]
    assert set(event) == {"message", "level", "tags"}
    assert event["tags"]["session_id"] == "session"
    telemetry.close()


SCENARIO_DATA = json.loads(SCENARIOS.read_text(encoding="utf-8"))


@pytest.mark.parametrize("scenario", SCENARIO_DATA, ids=lambda s: s["id"])
def test_repeatable_scenarios_with_mocked_events(scenario):
    # These are deterministic instrumentation/contract tests, NOT acoustic benchmarks.
    sessions = scenario.get("sessions", 1)
    identifiers = []
    for _ in range(sessions):
        session, orchestrator, capture, _monitor = observer()
        identifiers.append(orchestrator.state.conversation_id)
        speech(session)
        if scenario.get("fault") in {"llm", "tts"}:
            category = scenario["fault"]
            session.emit("error", error=NS(type=f"{category}_error", recoverable=False))
            assert capture.events[-1]["status"] == "error"
        elif scenario.get("fault") == "tool":
            orchestrator.state.actor_id = "test-user"
            orchestrator.executor.rate_limit_check = AsyncMock(
                side_effect=ToolFailure("injected", "Safe failure")
            )
            result = asyncio.run(
                orchestrator.executor.execute(
                    "calculate_expression", {"expression": "2+3"}, call_id="fault"
                )
            )
            assert result.status == "failed"
        else:
            answer(session)
            assert summarize(capture.events)["first_audio_seconds"] == [1]
    assert len(set(identifiers)) == sessions


def test_concurrent_sessions_remain_isolated():
    async def one():
        session, orchestrator, capture, _ = observer()
        orchestrator.state.actor_id = "test-user"
        speech(session)
        result = await orchestrator.executor.execute(
            "calculate_expression", {"expression": "2+3"}, call_id="shared-call"
        )
        assert result.status == "completed"
        return orchestrator.state.conversation_id, capture.events[0]["turn_id"]

    async def check():
        identities = await asyncio.gather(*(one() for _ in range(4)))
        assert len({s for s, _ in identities}) == 4
        assert len({t for _, t in identities}) == 4

    asyncio.run(check())
