"""Opt-in paced WAV replay, never a microphone callback or provider request."""

import argparse
import hashlib
import json
import math
import time
import wave
from datetime import UTC, datetime
from pathlib import Path

from app.audio.interfaces import AudioProcessingError, PCMChunk
from app.audio.processors.rnnoise import RNNoiseProcessor
from app.evaluation.artifacts import require_ignored
from app.evaluation.baseline import load_manifest, revision
from app.evaluation.resources import ResourceWindow, hardware, memory_snapshot


def read_recording(path):
    with wave.open(str(path), "rb") as audio:
        frames = audio.getnframes()
        if (
            audio.getframerate(),
            audio.getnchannels(),
            audio.getsampwidth(),
            audio.getcomptype(),
        ) != (48000, 1, 2, "NONE") or not 0 < frames <= 60 * 48000:
            raise ValueError("Use a nonempty mono 48kHz PCM16 WAV up to 60 seconds")
        data = audio.readframes(frames)
    if len(data) != frames * 2:
        raise ValueError("Truncated recording")
    return data


def summarize(timings, budgets, completions):
    ordered = sorted(timings)
    return {
        "count": len(timings),
        "average_seconds": sum(timings) / len(timings),
        "p95_seconds": ordered[math.ceil(len(ordered) * 0.95) - 1],
        "p99_seconds": ordered[math.ceil(len(ordered) * 0.99) - 1],
        "maximum_seconds": max(timings),
        "processing_budget_exceeded_count": sum(
            t > b for t, b in zip(timings, budgets, strict=True)
        ),
        "scheduled_completion_deadline_exceeded_count": sum(t > 0 for t in completions),
        "maximum_scheduled_completion_lateness_seconds": max(completions),
    }


def run(
    source, destination, *, chunk_ms, seconds, paced=True, factory=RNNoiseProcessor
):
    """One persistent native state; replay loops are explicitly reported."""
    if (
        chunk_ms not in (10, 20, 40)
        or not math.isfinite(seconds)
        or not 1 <= seconds <= 300
    ):
        raise ValueError("Choose 10/20/40ms chunks and 1..300 seconds")
    data = read_recording(source)
    require_ignored(destination)
    destination.mkdir(parents=True)  # No overwriting prior audio or reports.
    samples = round(seconds * 48000)
    step = chunk_ms * 48
    timings, budgets, lateness, rss = [], [], [], []
    emitted = clipped = 0
    before = time.perf_counter()
    with factory() as processor:
        initialization = time.perf_counter() - before
        window = ResourceWindow()
        origin = time.perf_counter()
        with (
            wave.open(str(destination / "original.wav"), "wb") as original,
            wave.open(str(destination / "processed.wav"), "wb") as output,
        ):
            for audio in (original, output):
                audio.setparams((1, 2, 48000, 0, "NONE", ""))
            for offset in range(0, samples, step):
                count = min(step, samples - offset)
                index = offset * 2 % len(data)
                # Handle source-loop boundaries without inserting fake silence.
                remaining = count * 2 - (len(data) - index)
                segment = (
                    (data[index:] + data * math.ceil(remaining / len(data)))[
                        : count * 2
                    ]
                    if remaining > 0
                    else data[index : index + count * 2]
                )
                scheduled = origin + offset / 48000
                if paced:
                    time.sleep(max(0, scheduled - time.perf_counter()))
                start = time.perf_counter()
                processed = processor.process(PCMChunk(segment, processor.format))
                finished = time.perf_counter()
                if processed.format != processor.format:
                    raise AudioProcessingError("Processor changed output format")
                timings.append(finished - start)
                budgets.append(count / 48000)
                lateness.append(
                    max(0, finished - (scheduled + count / 48000)) if paced else 0
                )
                original.writeframesraw(segment)
                output.writeframesraw(processed.data)
                emitted += len(processed.data) // 2
                if offset % 48000 < step:
                    snapshot = memory_snapshot()["rss_bytes"]
                    if snapshot is not None:
                        rss.append(snapshot)
                    if snapshot and snapshot > 1024**3:
                        raise AudioProcessingError(
                            "Evaluation exceeded 1GiB working set"
                        )
                if finished - origin > seconds + 60:
                    raise AudioProcessingError("Evaluation exceeded wall-time budget")
            start = time.perf_counter()
            tail = processor.flush()
            flush = time.perf_counter() - start
            if tail.format != processor.format:
                raise AudioProcessingError("Processor changed flush format")
            output.writeframesraw(tail.data)
            emitted += len(tail.data) // 2
            clipped = processor.clipped_samples
        resources = window.finish()
    if emitted != samples:
        raise AudioProcessingError("Processed duration differs from replay input")
    latency = summarize(timings, budgets, lateness)
    if not paced:
        latency["scheduled_completion_deadline_exceeded_count"] = None
        latency["maximum_scheduled_completion_lateness_seconds"] = None
    return {
        "chunk_ms": chunk_ms,
        "paced": paced,
        "audio_seconds": samples / 48000,
        "source_seconds": len(data) / 96000,
        "source_pcm_sha256": hashlib.sha256(data).hexdigest(),
        "source_loop_boundaries": (samples - 1) // (len(data) // 2),
        "initialization_seconds": initialization,
        "latency": latency,
        "processing_seconds_including_flush": sum(timings) + flush,
        "processing_real_time_factor": (sum(timings) + flush) / (samples / 48000),
        "flush_seconds": flush,
        "resources": resources,
        "sampled_rss_min_bytes": min(rss) if rss else None,
        "sampled_rss_max_bytes": max(rss) if rss else None,
        "sampled_rss_last_minus_first_bytes": rss[-1] - rss[0] if rss else None,
        "rss_sampling_interval_seconds_of_audio": 1,
        "clipped_samples": clipped,
        "output_samples": emitted,
        "human_listening": None,
        "transcription_accuracy": None,
        "physical_latency": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--chunk-ms", type=int, choices=(10, 20, 40), required=True)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--unpaced", action="store_true")
    args = parser.parse_args()
    try:
        matches = [x for x in load_manifest(args.manifest) if x["id"] == args.case]
        if len(matches) != 1:
            raise ValueError("Unknown fixture")
        item = matches[0]
        reference = (
            args.manifest.parent / item["reference_file"]
            if item.get("reference_file")
            else None
        )
        if reference and (not reference.is_file() or reference.stat().st_size > 65536):
            raise ValueError("Reference transcript must be a local text file <=64KiB")
        report = run(
            args.manifest.parent / item["wav"],
            args.output_dir,
            chunk_ms=args.chunk_ms,
            seconds=args.seconds,
            paced=not args.unpaced,
        )
        report.update(
            implementation="pyrnnoise 0.4.5 native default model; mono PCM16 48kHz",
            id=item["id"],
            category=item["category"],
            fixture_kind=json.loads(args.manifest.read_text(encoding="utf-8")).get(
                "fixture_kind", "unspecified_not_verified"
            ),
            created_at_utc=datetime.now(UTC).isoformat(),
            git_commit=revision(),
            hardware=hardware(),
            reference_transcript_available=reference is not None,
            reference_transcript_scope=(
                "source clip only, not expanded for replay loops"
            ),
            measurement_kind="local paced WAV replay"
            if not args.unpaced
            else "local unpaced WAV replay",
        )
        if reference:
            (args.output_dir / "reference.txt").write_bytes(reference.read_bytes())
        (args.output_dir / "report.json").write_text(
            json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
        )
    except Exception as error:
        print(json.dumps({"status": "failed", "error_category": type(error).__name__}))
        raise SystemExit(1) from None
    print("Local replay complete. Private WAV pair/report saved; listening is manual.")


if __name__ == "__main__":
    main()
