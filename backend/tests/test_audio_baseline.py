"""Synthetic metadata and mocked replay only; no paid providers or model downloads."""

import asyncio
import json
import math
import sys
import wave
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

from app.config.providers import ProviderConfig
from app.config.settings import Settings
from app.evaluation import baseline
from app.evaluation.resources import ResourceWindow, hardware, memory_snapshot


@pytest.fixture
def manifest(tmp_path):
    wav = tmp_path / "clean.wav"
    with wave.open(str(wav), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(bytes(32000))
    (tmp_path / "clean.txt").write_text("private reference", encoding="utf-8")
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "fixtures": [
                    {
                        "id": "clean",
                        "category": "clean",
                        "wav": "clean.wav",
                        "reference_file": "clean.txt",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def args(manifest, **values):
    return NS(
        manifest=manifest,
        reviews=None,
        replay=False,
        allow_provider_calls=False,
        repeats=1,
        **values,
    )


def settings():
    return Settings(
        livekit_url="ws://localhost:7880",
        livekit_api_key="private-key",
        livekit_api_secret="private-secret",
        stt=ProviderConfig("stt", "groq", "whisper-large-v3-turbo", "private-stt"),
        llm=ProviderConfig("llm", "groq", "openai/gpt-oss-20b", "private-llm"),
        tts=ProviderConfig("tts", "nvidia", "magpie-tts-multilingual", "private-tts"),
        voice_profile="groq_nvidia",
        allow_batch_stt=True,
    )


def test_inventory_is_offline_and_contains_no_private_text(manifest, monkeypatch):
    def forbidden():
        raise AssertionError("Inventory must not load settings or construct providers")

    monkeypatch.setattr("app.config.settings.load_settings", forbidden)
    report = asyncio.run(baseline.run(args(manifest)))
    record = report["results"][0]
    assert record["status"] == "inventory_only"
    assert record["audio"]["duration_seconds"] == 1
    assert len(record["audio"]["sha256"]) == 64
    assert report["configuration"] is None
    assert record["latencies"]["llm_ttft"]["p95_seconds"] is None
    assert all(record["human_judgments"][key] is None for key in baseline.JUDGMENTS)
    assert "private reference" not in json.dumps(report)
    assert str(manifest.parent) not in json.dumps(report)


@pytest.mark.parametrize("flag,env", [(False, None), (True, None), (False, "true")])
def test_live_requires_both_consent_controls(manifest, monkeypatch, flag, env):
    monkeypatch.delenv("RUN_REAL_VOICE_EVAL", raising=False)
    if env:
        monkeypatch.setenv("RUN_REAL_VOICE_EVAL", env)
    options = args(manifest)
    options.replay, options.allow_provider_calls = True, flag
    with pytest.raises(ValueError, match="requires"):
        asyncio.run(baseline.run(options))


@pytest.mark.parametrize("mode", ["success", "error", "no_audio", "provider_error"])
def test_mocked_replay_sanitizes_and_preserves_failures(manifest, monkeypatch, mode):
    monkeypatch.setenv("RUN_REAL_VOICE_EVAL", "true")
    monkeypatch.setattr("app.config.settings.load_settings", settings)
    monkeypatch.setattr(
        "app.providers.factory.preload_provider_plugins", lambda _: None
    )
    events = [
        {"stage": "llm_ttft", "duration": 0.2},
        {"stage": "response_first_audio", "duration": 0.8},
        {"stage": "tool_execution", "duration": 0.1, "status": "completed"},
    ]
    if mode == "no_audio":
        events = []
    if mode == "provider_error":
        events.append({"stage": "provider_error"})
    replay = AsyncMock(
        return_value=(NS(session_id="test-session", events=events), "private reference")
    )
    if mode == "error":
        replay.side_effect = RuntimeError("private-stt private transcript")
    monkeypatch.setattr("app.evaluation.voice.run_voice", replay)
    options = args(manifest)
    options.replay = options.allow_provider_calls = True
    report = asyncio.run(baseline.run(options))
    record = report["results"][0]
    assert record["status"] == {
        "success": "observed_server_replay",
        "error": "failed",
    }.get(mode, "incomplete_or_failed")
    assert "private" not in json.dumps(report)
    assert report["configuration"]["controlled_replay"]["mcp"] is False
    assert record["resources"]["cpu_seconds"] >= 0
    assert "vad_speech_start_detection_delay" in report["unmeasured"]
    if mode == "success":
        assert record["scores"]["transcription"]["word_error_rate"] == 0
        assert record["scores"]["tool_success_rate"] == 1
        assert record["latencies"]["response_first_audio"]["count"] == 1


def test_real_listener_shapes_count_without_classifying():
    callbacks = {}

    def bind(name):
        def register(callback):
            callbacks[name] = callback

        return register

    observations = baseline.Observations()
    observations.bind(NS(on=bind))
    callbacks["user_state_changed"](NS(new_state="speaking", old_state="listening"))
    for message in [
        NS(id="u", role="user"),
        NS(id="u", role="user"),
        NS(id="a", role="assistant", interrupted=True),
        NS(type="agent_handoff"),
    ]:
        callbacks["conversation_item_added"](NS(item=message))
    assert observations.counts == {
        "speech_starts": 1,
        "accepted_user_turns": 1,
        "interrupted_assistant_turns": 1,
    }


def test_latency_statistics_do_not_invent_missing_values():
    result = baseline.latency_summary(
        [
            {"stage": "llm_ttft", "duration": value}
            for value in [1, 2, 3, 4, -1, math.nan, math.inf, None, True]
        ]
    )
    assert result["llm_ttft"]["count"] == 4
    assert result["llm_ttft"]["invalid_or_missing_count"] == 5
    assert result["llm_ttft"]["p50_seconds"] == 2
    assert result["llm_ttft"]["p95_seconds"] == 4
    assert result["tts_first_audio"]["p50_seconds"] is None


@pytest.mark.parametrize("value", [-1, True, "1", 1.2])
def test_human_counts_strict(value):
    with pytest.raises(ValueError):
        baseline.review_scores({"false_interruptions": value})


def test_human_zero_is_not_missing():
    report = baseline.review_scores({"false_interruptions": 0})
    assert report["false_interruptions"] == 0
    assert report["missed_genuine_speech"] is None


@pytest.mark.parametrize("change", ["category", "duplicate", "version", "wav"])
def test_manifest_rejects_invalid_shapes(manifest, change):
    data = json.loads(manifest.read_text())
    if change == "category":
        data["fixtures"][0]["category"] = "fake"
    elif change == "duplicate":
        data["fixtures"] *= 2
    elif change == "version":
        data["version"] = 2
    else:
        data["fixtures"][0]["wav"] = 123
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        baseline.load_manifest(manifest)


def test_missing_fixture_is_not_a_success(manifest):
    manifest.with_name("clean.wav").unlink()
    report = asyncio.run(baseline.run(args(manifest)))
    assert report["results"][0]["status"] == "invalid_fixture"


@pytest.mark.parametrize(
    "rate,channels,width,frames",
    [
        (8000, 1, 2, 100),
        (16000, 2, 2, 100),
        (16000, 1, 1, 100),
        (16000, 1, 2, 0),
        (16000, 1, 2, 16000 * 91),
    ],
)
def test_unsupported_audio_is_not_silently_converted(
    tmp_path, rate, channels, width, frames
):
    path = tmp_path / "invalid.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(width)
        audio.setframerate(rate)
        audio.writeframes(bytes(frames * channels * width))
    with pytest.raises(ValueError):
        baseline.wav_metadata(path)


def test_latency_outcomes_remain_separable():
    result = baseline.latency_summary(
        [
            {
                "stage": "full_turn",
                "duration": 1,
                "status": "interrupted",
                "turn_id": "a",
            },
            {"stage": "full_turn", "duration": 2, "status": "ok", "turn_id": "b"},
        ]
    )["full_turn"]
    assert result["samples_seconds"] == [1, 2]
    assert [item["status"] for item in result["sample_context"]] == [
        "interrupted",
        "ok",
    ]


def test_resource_measurements_are_real_and_scoped():
    report = ResourceWindow().finish()
    assert report["wall_seconds"] >= 0
    assert report["cpu_seconds"] >= 0
    assert "rss_bytes" in memory_snapshot()
    assert hardware()["logical_cpu_count"] is not None


def test_cli_refuses_overwrite_without_touching_file(manifest, monkeypatch):
    original = manifest.read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        ["baseline", "--manifest", str(manifest), "--output", str(manifest)],
    )
    with pytest.raises(SystemExit) as exit_info:
        baseline.main()
    assert exit_info.value.code == 2
    assert manifest.read_bytes() == original


@pytest.mark.parametrize("raise_in_hook", [False, True])
def test_replay_observation_seam_preserves_cleanup(monkeypatch, raise_in_hook):
    from app.evaluation import voice

    session = NS(
        input=NS(audio=None),
        output=NS(audio=None),
        on=lambda _: lambda callback: callback,
        agent_state="listening",
        start=AsyncMock(),
        aclose=AsyncMock(),
    )
    orchestrator = NS(state=NS(conversation_id="test"), executor=NS(close=AsyncMock()))
    source_file = NS(getnframes=lambda: 0, close=Mock())
    observer = NS(close=AsyncMock())
    hook = Mock(side_effect=RuntimeError("test") if raise_in_hook else None)
    monkeypatch.setattr(voice, "create_session", lambda _: session)
    monkeypatch.setattr(voice, "build_orchestrator", lambda _: orchestrator)
    monkeypatch.setattr(voice, "MainAgent", lambda *_: object())
    monkeypatch.setattr(voice, "ReplayInput", lambda _: NS(file=source_file))
    monkeypatch.setattr(voice, "TimedSink", object)
    monkeypatch.setattr(voice, "SessionObserver", lambda *_: observer)
    monkeypatch.setattr(voice.asyncio, "sleep", AsyncMock())
    if raise_in_hook:
        with pytest.raises(RuntimeError, match="test"):
            asyncio.run(voice.run_voice(settings(), "unused", observe_session=hook))
    else:
        asyncio.run(voice.run_voice(settings(), "unused", observe_session=hook))
        session.start.assert_awaited_once()
    hook.assert_called_once_with(session)
    session.aclose.assert_awaited_once()
    orchestrator.executor.close.assert_awaited_once()
    observer.close.assert_awaited_once()
    source_file.close.assert_called_once()
