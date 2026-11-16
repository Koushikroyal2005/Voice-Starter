"""Offline fixture inventory or explicitly authorized existing AgentSession replay."""

import argparse
import asyncio
import hashlib
import json
import logging
import math
import os
import re
import subprocess
import wave
from dataclasses import replace
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from app.evaluation.artifacts import require_ignored_file
from app.evaluation.resources import ResourceWindow, hardware
from app.evaluation.scoring import summarize

CATEGORIES = (
    "clean",
    "quiet",
    "fan",
    "television",
    "music_chanting",
    "multiple_speakers",
    "overlapping_speakers",
)
STAGES = (
    "stt_final",
    "stt_final_from_speech_start",
    "stt_interim",
    "end_of_turn",
    "llm_ttft",
    "tts_first_audio",
    "response_first_audio",
    "full_turn",
    "interruption_stop",
    "tool_execution",
)
JUDGMENTS = (
    "false_speech_activations",
    "false_accepted_user_turns",
    "false_interruptions",
    "missed_genuine_speech",
)


def load_manifest(filename):
    data = json.loads(filename.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Manifest version must be 1")
    fixtures = data.get("fixtures")
    if not isinstance(fixtures, list) or not 1 <= len(fixtures) <= 50:
        raise ValueError("Supply between 1 and 50 fixtures")
    seen = set()
    for item in fixtures:
        if not isinstance(item, dict):
            raise ValueError("Invalid fixture")
        key = item.get("id", "")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9_-]{1,64}", key):
            raise ValueError("Fixture IDs must be short non-private identifiers")
        if key in seen or item.get("category") not in CATEGORIES:
            raise ValueError("Duplicate fixture ID or unsupported category")
        seen.add(key)
        for field in ("wav", "reference_file"):
            if field in item and (
                not isinstance(item[field], str) or not item[field].strip()
            ):
                raise ValueError("Fixture paths must be nonempty strings")
        if "wav" not in item:
            raise ValueError("Each fixture needs a WAV path")
    return fixtures


def wav_metadata(filename):
    with wave.open(str(filename), "rb") as audio:
        rate, frames = audio.getframerate(), audio.getnframes()
        if (
            audio.getcomptype() != "NONE"
            or audio.getnchannels() != 1
            or audio.getsampwidth() != 2
            or rate != 16000
            or not 0 < frames <= rate * 90
        ):
            raise ValueError("Use nonempty mono PCM16 16kHz WAV, at most 90 seconds")
        if len(audio.readframes(frames)) != frames * 2:
            raise ValueError("Truncated WAV")
    with filename.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return {
        "sha256": digest,
        "sample_rate_hz": rate,
        "channels": 1,
        "sample_width_bytes": 2,
        "frames": frames,
        "duration_seconds": frames / rate,
    }


def latency_summary(events):
    result = {}
    for stage in STAGES:
        selected = [event for event in events if event.get("stage") == stage]
        samples = [
            event.get("duration")
            for event in selected
            if isinstance(event.get("duration"), (int, float))
            and not isinstance(event.get("duration"), bool)
            and math.isfinite(event["duration"])
            and event["duration"] >= 0
        ]
        ordered = sorted(samples)
        result[stage] = {
            "samples_seconds": samples,
            "sample_context": [
                {
                    "status": event.get("status", "ok"),
                    "turn_id": event.get("turn_id"),
                    "tool_call_id": event.get("tool_call_id"),
                }
                for event in selected
                if isinstance(event.get("duration"), (int, float))
                and not isinstance(event.get("duration"), bool)
                and math.isfinite(event["duration"])
                and event["duration"] >= 0
            ],
            "count": len(samples),
            "invalid_or_missing_count": len(selected) - len(samples),
            "p50_seconds": ordered[math.ceil(len(ordered) * 0.5) - 1]
            if ordered
            else None,
            "p95_seconds": ordered[math.ceil(len(ordered) * 0.95) - 1]
            if ordered
            else None,
        }
    return result


def review_scores(review):
    if not isinstance(review, dict):
        raise ValueError("Review must be an object")
    result = {}
    for key in JUDGMENTS:
        count = review.get(key)
        if count is not None and (type(count) is not int or count < 0):
            raise ValueError("Human review counts must be nonnegative integers or null")
        result[key] = count
    return {"source": "human_review_not_automatic_classification", **result}


class Observations:
    def __init__(self):
        self.counts = {
            "speech_starts": 0,
            "accepted_user_turns": 0,
            "interrupted_assistant_turns": 0,
        }
        self._items = set()

    def bind(self, session):
        @session.on("user_state_changed")
        def speech(event):
            if event.new_state == "speaking" and event.old_state != "speaking":
                self.counts["speech_starts"] += 1

        @session.on("conversation_item_added")
        def item(event):
            message = event.item
            if getattr(message, "type", "message") != "message":
                return
            if message.id in self._items:
                return
            self._items.add(message.id)
            if message.role == "user":
                self.counts["accepted_user_turns"] += 1
            elif message.role == "assistant" and message.interrupted:
                self.counts["interrupted_assistant_turns"] += 1


def configuration(settings):
    # Deliberate allowlist. Never serialize Settings, endpoints, prompts or keys.
    return {
        "voice_profile": settings.voice_profile,
        "profile_overrides": list(settings.profile_overrides),
        "use_case": settings.use_case,
        "providers": {
            name: {
                field: getattr(getattr(settings, name), field)
                for field in ("provider", "model", "language", "voice")
            }
            for name in ("stt", "llm", "tts")
        },
        "turn_detection": settings.turn_detection,
        "require_interim": settings.require_interim,
        "allow_batch_stt": settings.allow_batch_stt,
        "controlled_replay": {
            "mcp": False,
            "fallbacks": False,
            "room": False,
            "persistence_installed": False,
            "audio_recording": False,
            "tools": ["get_current_time", "calculate_expression", "time_and_calculate"],
        },
    }


def revision():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def source_fingerprints():
    files = {
        "baseline": Path(__file__),
        "replay": Path(__file__).with_name("voice.py"),
        "resources": Path(__file__).with_name("resources.py"),
        "pipeline": Path(__file__).parent.parent / "providers" / "pipeline.py",
    }
    return {
        key: hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in files.items()
    }


async def run(args):
    if args.replay and (
        not args.allow_provider_calls or os.getenv("RUN_REAL_VOICE_EVAL") != "true"
    ):
        raise ValueError(
            "Replay requires --allow-provider-calls and RUN_REAL_VOICE_EVAL=true"
        )
    if not 1 <= args.repeats <= 10:
        raise ValueError("Repeats must be between 1 and 10")
    fixtures = load_manifest(args.manifest)
    reviews = (
        json.loads(args.reviews.read_text(encoding="utf-8")) if args.reviews else {}
    )
    if not isinstance(reviews, dict):
        raise ValueError("Reviews must be an object keyed by fixture-id:repeat-index")
    settings = None
    if args.replay:
        from app.config.settings import load_settings
        from app.evaluation.voice import run_voice
        from app.providers.factory import preload_provider_plugins

        settings = replace(
            load_settings(),
            mcp_enabled=False,
            fallbacks=(),
            tool_allowlist=(
                "get_current_time",
                "calculate_expression",
                "time_and_calculate",
            ),
        )
        preload_provider_plugins((settings.stt, settings.llm, settings.tts))
    results = []
    for fixture in fixtures:
        for index in range(args.repeats):
            identifier = f"{fixture['id']}:{index}"
            result = {
                "id": identifier,
                "category": fixture["category"],
                "human_judgments": review_scores(reviews.get(identifier, {})),
            }
            results.append(result)
            filename = args.manifest.parent / fixture["wav"]
            try:
                result["audio"] = wav_metadata(filename)
                reference = (
                    (args.manifest.parent / fixture["reference_file"])
                    .read_text(encoding="utf-8")
                    .strip()
                    if "reference_file" in fixture
                    else None
                )
            except (OSError, ValueError, wave.Error, EOFError):
                result.update(
                    status="invalid_fixture", failure="missing_or_invalid_local_fixture"
                )
                continue
            if not args.replay:
                result.update(status="inventory_only", latencies=latency_summary([]))
                continue
            observations = Observations()
            resources = ResourceWindow()
            try:
                capture, transcript = await run_voice(
                    settings, filename, observe_session=observations.bind
                )
                result.update(
                    status="observed_server_replay"
                    if any(e["stage"] == "response_first_audio" for e in capture.events)
                    and not any(e["stage"] == "provider_error" for e in capture.events)
                    else "incomplete_or_failed",
                    session_id=capture.session_id,
                    latencies=latency_summary(capture.events),
                    scores=summarize(
                        capture.events, reference=reference, transcript=transcript
                    ),
                    provider_error_count=sum(
                        e["stage"] == "provider_error" for e in capture.events
                    ),
                )
            except Exception:
                result.update(status="failed", failure="provider_or_replay_failure")
            finally:
                result["resources"] = resources.finish()
                result["observations"] = observations.counts
    return {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "git_commit": revision(),
        "source_sha256": source_fingerprints(),
        "livekit_agents_version": version("livekit-agents"),
        "mode": "roomless_provider_replay" if args.replay else "offline_inventory",
        "hardware": hardware(),
        "configuration": configuration(settings) if settings else None,
        "execution": {
            "concurrency": 1,
            "repeats": args.repeats,
            "timeout_per_replay_seconds": 120,
        },
        "unmeasured": {
            "vad_speech_start_detection_delay": (
                "No calibrated acoustic onset timestamp"
            ),
            "interruption_to_physical_audio_stop": (
                "interruption_stop is SDK state transition only"
            ),
            "microphone_to_speaker_latency": (
                "Roomless sink has no microphone, network or speaker"
            ),
        },
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("evaluation.local/baseline.json")
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--allow-provider-calls", action="store_true")
    args = parser.parse_args()
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)  # SDK errors can contain private payloads.
    try:
        if args.output.suffix.lower() != ".json" or args.output.exists():
            raise ValueError("Choose a new JSON output file; overwrites are refused")
        require_ignored_file(args.output)
        report = asyncio.run(run(args))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(json.dumps(report, indent=2, allow_nan=False))
    except Exception:
        parser.exit(
            2,
            "Baseline failed: check consent flags, files, configuration and a new "
            "JSON output path; details withheld.\n",
        )
    finally:
        logging.disable(previous)
    print("Baseline JSON written locally; no audio or transcript included.")
    if any(
        r["status"] in {"failed", "incomplete_or_failed", "invalid_fixture"}
        for r in report["results"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
