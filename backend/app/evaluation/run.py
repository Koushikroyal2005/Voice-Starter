"""Opt-in real-provider evaluation; print scores and metadata, not conversation text."""

import argparse
import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path

from app.config.settings import load_settings
from app.evaluation.scoring import summarize
from app.evaluation.voice import run_voice

SCENARIOS = Path(__file__).with_name("scenarios.json")


async def run(args):
    scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    if args.scenario and args.scenario not in {s["id"] for s in scenarios}:
        raise ValueError("Unknown scenario")
    if args.list:
        return {"scenarios": scenarios, "results": "not run"}
    if os.environ.get("RUN_REAL_VOICE_EVAL") != "true":
        raise ValueError(
            "Set RUN_REAL_VOICE_EVAL=true; real calls incur provider charges"
        )
    if args.fixtures is None:
        raise ValueError("--fixtures is required; no audio fixtures are bundled")
    settings = load_settings()
    reviews = (
        json.loads(args.reviews.read_text(encoding="utf-8")) if args.reviews else {}
    )
    semaphore = asyncio.Semaphore(args.concurrency)

    async def one(scenario, index):
        identifier = f"{scenario['id']}:{index}"
        filename = args.fixtures / f"{scenario['id']}.wav"
        if scenario["mode"] == "mock_fault":
            return {
                "id": identifier,
                "status": "not_run",
                "reason": "unit-test fault scenario",
            }
        if not filename.is_file():
            return {
                "id": identifier,
                "status": "not_run",
                "reason": "missing WAV fixture",
            }
        async with semaphore:
            configured = replace(
                settings,
                stt=replace(settings.stt, language=scenario["language"]),
                fallbacks=(),
                tool_allowlist=(
                    "get_current_time",
                    "calculate_expression",
                    "time_and_calculate",
                ),
            )
            try:
                capture, transcript = await run_voice(configured, filename)
                reference_file = args.fixtures / f"{scenario['id']}.txt"
                reference = (
                    reference_file.read_text(encoding="utf-8").strip()
                    if reference_file.is_file()
                    else scenario["reference"]
                )
                return {
                    "id": identifier,
                    "status": "measured_server_replay"
                    if any(e["stage"] == "response_first_audio" for e in capture.events)
                    and not any(e["stage"] == "provider_error" for e in capture.events)
                    else "failed",
                    "session_id": capture.session_id,
                    "events": capture.events,
                    "scores": summarize(
                        capture.events,
                        reference=reference,
                        transcript=transcript,
                        review=reviews.get(identifier),
                    ),
                }
            except Exception:
                return {
                    "id": identifier,
                    "status": "failed",
                    "reason": "provider or replay error; inspect safe telemetry",
                }

    results = await asyncio.gather(
        *(
            one(s, i)
            for s in scenarios
            for i in range(s.get("sessions", 1))
            if not args.scenario or s["id"] == args.scenario
        )
    )
    return {
        "measurement_kind": "real_provider_roomless_replay",
        "results": results,
        "targets": "none configured; no benchmark or pass threshold assumed",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--fixtures", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--scenario")
    parser.add_argument("--concurrency", type=int, choices=range(1, 9), default=4)
    args = parser.parse_args()
    try:
        report = asyncio.run(run(args))
    except ValueError as error:
        parser.error(str(error))
    # Preserve Unicode JSON data even on legacy Windows console encodings.
    print(json.dumps(report))
    if any(
        r["status"] == "failed"
        for r in report.get("results", [])
        if isinstance(r, dict)
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
