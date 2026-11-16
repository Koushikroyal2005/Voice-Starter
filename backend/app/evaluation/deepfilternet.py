"""Opt-in DFN3 batch experiment, reusing the RNNoise fixtures/timing framework."""

import argparse
import json
import time
import wave
from datetime import UTC, datetime
from pathlib import Path

from app.audio.processors.deepfilternet import EXECUTABLE_SHA256, DeepFilterNetProcessor
from app.evaluation.audio_scoring import comparison
from app.evaluation.baseline import load_manifest, revision
from app.evaluation.resources import ResourceWindow, hardware, run_measured_child
from app.evaluation.rnnoise import read_pcm
from app.evaluation.voxlock import measure_stream, require_ignored


def evaluate(item, base: Path, executable: Path):
    source, metadata = read_pcm(base / item["wav"])
    target = (
        read_pcm(base / item["target_wav"])[0].data if item.get("target_wav") else None
    )
    intervals = item.get("background_only_intervals", [])
    comparison(source.data, source.data, target, intervals, sample_rate=48000)
    children = []

    def runner(command, **kwargs):
        result, metrics = run_measured_child(command, **kwargs)
        children.append(metrics)
        return result

    window = ResourceWindow()
    started = time.perf_counter()
    with DeepFilterNetProcessor(executable, runner=runner) as processor:
        preparation = time.perf_counter() - started
        timing, data = measure_stream(processor, source, 40, time.perf_counter() + 90)
        resources = window.finish()
    # Do not label process() buffer-copy timings as per-chunk neural inference.
    buffering = timing.pop("chunk_processing_seconds")
    return {
        "id": item["id"],
        "category": item["category"],
        "input": metadata,
        "status": "measured_local_official_cpu_batch_inference",
        "streaming": False,
        "binary_verification_seconds": preparation,
        **timing,
        "chunk_buffering_seconds_not_inference": buffering,
        "inference_chunk_processing_seconds": None,
        "model_initialization_seconds": None,
        "initialization_note": (
            "Model load is inside the child/flush, not separately exposed"
        ),
        "parent_resources": resources,
        "inference_child_resources": children[0],
        "comparison": comparison(
            source.data, data, target, intervals, sample_rate=48000
        ),
        "human_quality_judgment": None,
        "transcription_measurements": None,
        "physical_audio_latency_seconds": None,
    }, data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        require_ignored(args.output_dir)
        if args.output_dir.exists():
            raise ValueError("Output directory exists; no overwrites")
        cases = [
            item for item in load_manifest(args.manifest) if item["id"] == args.case
        ]
        if len(cases) != 1:
            raise ValueError("Unknown fixture ID")
        report, data = evaluate(cases[0], args.manifest.parent, args.executable)
        report.update(
            created_at_utc=datetime.now(UTC).isoformat(),
            git_commit=revision(),
            hardware=hardware(),
            executable_sha256=EXECUTABLE_SHA256,
            implementation=(
                "official Windows v0.5.6 CLI, embedded DeepFilterNet3; "
                "default thresholds; no postfilter or delay compensation"
            ),
        )
        args.output_dir.mkdir(parents=True)
        with wave.open(str(args.output_dir / "output.wav"), "wb") as audio:
            audio.setparams((1, 2, 48000, 0, "NONE", ""))
            audio.writeframes(data)
        (args.output_dir / "report.json").write_text(
            json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
        )
    except Exception as error:
        print(json.dumps({"status": "failed", "error_category": type(error).__name__}))
        raise SystemExit(1) from None
    print("Genuine local DFN3 batch inference complete; outputs remain ignored.")


if __name__ == "__main__":
    main()
