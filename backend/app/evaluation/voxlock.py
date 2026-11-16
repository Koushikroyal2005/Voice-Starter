"""Opt-in local VoxLock experiment; no credentials, provider calls or LiveKit I/O."""

import argparse
import hashlib
import json
import math
import subprocess
import time
import urllib.request
import wave
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from app.audio.interfaces import AudioProcessingError, AudioProcessor, PCMChunk
from app.audio.processors.voxlock import (
    MODEL_FILES,
    MODEL_REVISION,
    VoxLockConfig,
    VoxLockProcessor,
    verify_models,
)
from app.evaluation.audio_scoring import compare_audio
from app.evaluation.baseline import load_manifest, revision, wav_metadata
from app.evaluation.resources import ResourceWindow, hardware, memory_snapshot


def require_ignored(directory: Path):
    """Refuse to write models/audio/reports into tracked or non-ignored locations."""
    for name in ("probe.wav", "probe.onnx", "probe.json", "probe.part"):
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", str(directory.resolve() / name)],
            capture_output=True,
            timeout=3,
        )
        if result.returncode != 0:
            raise ValueError("Use an ignored .local/ or evaluation.local/ directory")


def download_models(directory: Path):
    require_ignored(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, (size, expected) in MODEL_FILES.items():
        destination = directory / name
        if destination.exists():
            with destination.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            if destination.stat().st_size != size or digest != expected:
                raise ValueError("Existing model is invalid; not overwriting it")
            continue
        url = (
            "https://huggingface.co/arbazsiddiqui/voxlock/resolve/"
            f"{MODEL_REVISION}/onnx/v2/{name}"
        )
        temporary = directory / (name + ".part")
        # Exclusivity avoids deleting or overwriting another download's work.
        with temporary.open("xb") as output:
            try:
                started, total, digest = time.monotonic(), 0, hashlib.sha256()
                with urllib.request.urlopen(url, timeout=20) as response:
                    while chunk := response.read(1024 * 1024):
                        if (
                            time.monotonic() - started > 120
                            or total + len(chunk) > size
                        ):
                            raise ValueError(
                                "Download exceeded its time or size budget"
                            )
                        output.write(chunk)
                        digest.update(chunk)
                        total += len(chunk)
                if total != size or digest.hexdigest() != expected:
                    raise ValueError("Official model size/SHA-256 verification failed")
            except BaseException:
                output.close()
                temporary.unlink(missing_ok=True)
                raise
        temporary.rename(destination)
    return verify_models(directory)


def read_pcm(filename: Path, *, enrollment=False) -> tuple[PCMChunk, dict]:
    metadata = wav_metadata(filename)
    if metadata["duration_seconds"] > 15:
        raise ValueError("Limit each evaluation WAV to 15 seconds")
    if enrollment and metadata["duration_seconds"] < 3:
        raise ValueError("Target enrollment needs at least three seconds")
    with wave.open(str(filename), "rb") as audio:
        return PCMChunk(audio.readframes(audio.getnframes())), metadata


def measure_stream(
    processor: AudioProcessor, original: PCMChunk, chunk_ms: int, deadline: float
):
    """Consume only the processor interface; construction stays outside timing."""
    if not original.data or chunk_ms not in (40, 80):
        raise ValueError("Supply nonempty PCM and 40ms or 80ms chunks")
    fragments, timings, first_output_input_samples = [], [], None
    step = chunk_ms * original.format.sample_rate // 1000 * original.format.channels * 2
    processing_start = time.perf_counter()
    for offset in range(0, len(original.data), step):
        rss = memory_snapshot()["rss_bytes"]
        if time.perf_counter() > deadline or (rss and rss > 1024**3):
            raise AudioProcessingError(
                "Evaluation exceeded time or 1GiB working-set budget"
            )
        before = time.perf_counter()
        output = processor.process(
            PCMChunk(original.data[offset : offset + step], original.format)
        )
        if output.format != original.format:
            raise AudioProcessingError(
                "Processor output format changed during evaluation"
            )
        timings.append(time.perf_counter() - before)
        fragments.append(output.data)
        if output.data and first_output_input_samples is None:
            first_output_input_samples = min(offset + step, len(original.data)) // (
                2 * original.format.channels
            )
    before = time.perf_counter()
    tail = processor.flush()
    if tail.format != original.format:
        raise AudioProcessingError("Processor flush format changed during evaluation")
    fragments.append(tail.data)
    flush_seconds = time.perf_counter() - before
    elapsed = time.perf_counter() - processing_start
    ordered = sorted(timings)
    return {
        "processing_seconds": elapsed,
        "flush_seconds": flush_seconds,
        "real_time_factor": elapsed
        / (original.samples_per_channel / original.format.sample_rate),
        "chunk_processing_seconds": {
            "p50": ordered[math.ceil(len(ordered) * 0.5) - 1],
            "p95": ordered[math.ceil(len(ordered) * 0.95) - 1],
            "max": max(timings),
            "count": len(timings),
            "over_chunk_budget_count": sum(t > chunk_ms / 1000 for t in timings),
        },
        "first_output_after_input_samples": first_output_input_samples,
    }, b"".join(fragments)


def evaluate_case(item, base: Path, config: VoxLockConfig, chunk_ms: int):
    if chunk_ms not in (40, 80):
        raise ValueError("Choose 40ms or 80ms chunks")
    original, metadata = read_pcm(base / item["wav"])
    enrollment, enrollment_metadata = read_pcm(
        base / item["enrollment"], enrollment=True
    )
    reference = (
        read_pcm(base / item["target_wav"])[0] if item.get("target_wav") else None
    )
    intervals = item.get("background_only_intervals", [])
    # Validate reference/annotations before expensive model construction.
    compare_audio(
        original.data, original.data, reference.data if reference else None, intervals
    )
    window = ResourceWindow()
    deadline = time.perf_counter() + 120
    processor: VoxLockProcessor | None = None
    report = {
        "id": item["id"],
        "category": item["category"],
        "input": metadata,
        "enrollment": enrollment_metadata,
    }
    try:
        before = time.perf_counter()
        processor = VoxLockProcessor(config)
        report["initialization_seconds_including_hash_verification"] = (
            time.perf_counter() - before
        )
        report["model_sha256"] = processor.model_hashes
        before = time.perf_counter()
        processor.enroll(enrollment)
        report["enrollment_seconds"] = time.perf_counter() - before
        timing, data = measure_stream(processor, original, chunk_ms, deadline)
        report.update(timing)
        report.update(
            status="measured_local_cpu_inference",
            chunk_ms=chunk_ms,
            threads=config.threads,
            precision="int8",
            model_revision=MODEL_REVISION,
            clipped_samples=processor.clipped_samples,
            comparison=compare_audio(
                original.data, data, reference.data if reference else None, intervals
            ),
            physical_audio_latency_seconds=None,
        )
        return report, data
    finally:
        if processor:
            processor.close()
        report["resources"] = window.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    download = sub.add_parser("download")
    download.add_argument("--model-dir", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--model-dir", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--case", required=True)
    run.add_argument("--chunk-ms", type=int, choices=(40, 80), default=40)
    args = parser.parse_args()
    try:
        if args.command == "download":
            download_models(args.model_dir)
            print("Official INT8 models downloaded and SHA-256 verified.")
            return
        require_ignored(args.output_dir)
        if args.output_dir.exists():
            raise ValueError("Output directory already exists; no overwrites")
        matches = [x for x in load_manifest(args.manifest) if x["id"] == args.case]
        if len(matches) != 1:
            raise ValueError("Unknown fixture ID")
        report, data = evaluate_case(
            matches[0],
            args.manifest.parent,
            VoxLockConfig(args.model_dir),
            args.chunk_ms,
        )
        report.update(
            created_at_utc=datetime.now(UTC).isoformat(),
            git_commit=revision(),
            hardware=hardware(),
            voxlock_version=version("voxlock"),
            onnxruntime_version=version("onnxruntime"),
            measurement_kind="unpaced_enrolled_CPU_stream_not_microphone_timing",
        )
        args.output_dir.mkdir(parents=True)
        with wave.open(str(args.output_dir / "output.wav"), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(data)
        report["output"] = wav_metadata(args.output_dir / "output.wav")
        (args.output_dir / "report.json").write_text(
            json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
        )
    except Exception as error:
        # No raw paths, model diagnostics, user audio or arbitrary exception text.
        print(json.dumps({"status": "failed", "error_category": type(error).__name__}))
        raise SystemExit(1) from None
    print("Genuine local inference complete; private audio/report saved locally.")


if __name__ == "__main__":
    main()
