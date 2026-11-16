"""Opt-in RNNoise WAV experiment; no provider calls or production wiring."""

import argparse
import hashlib
import json
import time
import wave
from datetime import UTC, datetime
from pathlib import Path

from app.audio.interfaces import PCMChunk
from app.audio.processors.rnnoise import RNNoiseProcessor
from app.evaluation.baseline import load_manifest, revision
from app.evaluation.resources import ResourceWindow, hardware
from app.evaluation.voxlock import compare_audio, measure_stream, require_ignored


def read_pcm(path: Path):
    # The existing baseline WAV reader intentionally requires 16kHz. RNNoise
    # needs 48kHz; do not silently resample or change that existing contract.
    with wave.open(str(path), "rb") as audio:
        frames = audio.getnframes()
        if (
            audio.getframerate() != 48000
            or audio.getnchannels() != 1
            or audio.getsampwidth() != 2
            or audio.getcomptype() != "NONE"
            or not 0 < frames <= 15 * 48000
        ):
            raise ValueError("Supply mono 48kHz PCM16 WAV, up to 15 seconds")
        data = audio.readframes(frames)
    if len(data) != frames * 2:
        raise ValueError("Truncated WAV")
    return PCMChunk(data, RNNoiseProcessor.format), {
        "sample_rate": 48000,
        "channels": 1,
        "frames": frames,
        "duration_seconds": frames / 48000,
        "pcm_sha256": hashlib.sha256(data).hexdigest(),
    }


def comparison(original, output, target, intervals):
    import numpy as np

    # Energy and SDR are sample-rate independent. Its interval helper is 16kHz:
    # convert only interval coordinates, not samples, for this reused function.
    scaled = [[start * 3, end * 3] for start, end in intervals]
    result = {"raw": compare_audio(original, output, target, scaled)}
    result["estimated_alignment_samples"] = None
    result["aligned"] = None
    if target is not None:
        reference = np.frombuffer(target, dtype="<i2").astype(np.float64)
        actual = np.frombuffer(output, dtype="<i2").astype(np.float64)
        # Bounded offline cross-correlation, 0..40ms; no timestamps invented.
        # Decimate by 4 only for lag estimation; retain full-rate SDR comparison.
        scores = [
            float(np.dot(reference[: len(actual) - lag : 4], actual[lag::4]))
            for lag in range(0, min(1920, len(actual) - 1) + 1, 4)
        ]
        if np.any(reference) and np.any(actual):
            lag = int(np.argmax(scores)) * 4
            result["estimated_alignment_samples"] = lag
            result["aligned"] = compare_audio(
                original[: len(original) - 2 * lag] if lag else original,
                output[2 * lag :],
                target[: len(target) - 2 * lag] if lag else target,
                [],
            )
    return result


def evaluate(item, base: Path):
    source, metadata = read_pcm(base / item["wav"])
    target = (
        read_pcm(base / item["target_wav"])[0].data if item.get("target_wav") else None
    )
    intervals = item.get("background_only_intervals", [])
    comparison(source.data, source.data, target, intervals)
    window = ResourceWindow()
    started = time.perf_counter()
    with RNNoiseProcessor() as processor:
        initialization = time.perf_counter() - started
        timing, data = measure_stream(processor, source, 40, time.perf_counter() + 60)
        resources = window.finish()  # Excludes offline quality scoring.
        clipped = processor.clipped_samples
    return {
        "id": item["id"],
        "category": item["category"],
        "status": "measured_local_native_cpu_inference",
        "input": metadata,
        "initialization_seconds": initialization,
        **timing,
        "resources": resources,
        "comparison": comparison(source.data, data, target, intervals),
        "clipped_samples": clipped,
        "native_frame_samples": 480,
        "chunk_ms": 40,
        "physical_audio_latency_seconds": None,
        "human_quality_judgment": None,
        "transcription_measurements": None,
    }, data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--case", required=True)
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
        report, data = evaluate(cases[0], args.manifest.parent)
        report.update(
            created_at_utc=datetime.now(UTC).isoformat(),
            git_commit=revision(),
            hardware=hardware(),
            implementation="pyrnnoise 0.4.5 bundled RNNoise native default model",
            measurement_kind="unpaced CPU stream; not microphone or paced realtime",
        )
        args.output_dir.mkdir(parents=True)
        with wave.open(str(args.output_dir / "output.wav"), "wb") as audio:
            audio.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
            audio.writeframes(data)
        (args.output_dir / "report.json").write_text(
            json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
        )
    except Exception as error:
        print(json.dumps({"status": "failed", "error_category": type(error).__name__}))
        raise SystemExit(1) from None
    print("Local RNNoise inference complete; audio/report saved in ignored directory.")


if __name__ == "__main__":
    main()
