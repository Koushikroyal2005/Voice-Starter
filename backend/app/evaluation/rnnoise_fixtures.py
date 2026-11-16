"""Prepare ignored 48kHz synthetic fixtures from existing local 16kHz references."""

import argparse
import json
import wave
from pathlib import Path

from app.evaluation.artifacts import require_ignored
from app.evaluation.voxlock import read_pcm


def prepare(source: Path, destination: Path):
    import numpy as np
    import soxr

    require_ignored(destination)
    if destination.exists():
        raise ValueError("Fixture directory already exists; no overwrites")
    # Read and validate before creating output. No recording, network or TTS.
    originals = {
        name: read_pcm(source / f"{name}.wav")[0].data
        for name in ("clean-target", "background", "overlap")
    }
    clean = np.frombuffer(originals["clean-target"], dtype="<i2").astype(np.float64)
    signals = {"clean": clean, "quiet": clean * 0.2}
    rng = np.random.default_rng(20261116)
    # Explicit synthetic stationary noise, NOT an actual fan recording.
    noise = rng.normal(0, 1000, len(clean))
    noise = np.convolve(noise, np.ones(5) / 5, mode="same")
    signals["noise"] = clean + noise
    for name in ("background", "overlap"):
        signals[name] = np.frombuffer(originals[name], dtype="<i2").astype(np.float64)
    destination.mkdir(parents=True)
    items = []
    categories = {
        "clean": "clean",
        "quiet": "quiet",
        "noise": "fan",
        "background": "multiple_speakers",
        "overlap": "overlapping_speakers",
    }
    for name, signal in signals.items():
        for suffix, values in (
            ("", signal),
            ("-target", clean * (0.2 if name == "quiet" else 1)),
        ):
            samples = np.clip(
                np.rint(soxr.resample(values, 16000, 48000)), -32768, 32767
            )
            with wave.open(str(destination / f"{name}{suffix}.wav"), "wb") as audio:
                audio.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
                audio.writeframes(samples.astype("<i2").tobytes())
        item = {
            "id": name,
            "category": categories[name],
            "wav": f"{name}.wav",
            "target_wav": f"{name}-target.wav",
        }
        if name in ("noise", "background"):
            item["background_only_intervals"] = [[6, 11]]
        items.append(item)
    (destination / "manifest.json").write_text(
        json.dumps(
            {"version": 1, "fixture_kind": "synthetic_not_recorded", "fixtures": items},
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.source, args.output_dir)
