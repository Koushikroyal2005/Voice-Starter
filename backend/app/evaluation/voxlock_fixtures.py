"""Build known mixtures from separately generated, local synthetic speaker stems."""

import argparse
import json
import wave
from pathlib import Path

from app.evaluation.artifacts import require_ignored
from app.evaluation.voxlock import read_pcm


def create_fixtures(raw: Path, destination: Path):
    import numpy as np

    require_ignored(destination)
    if destination.exists():
        raise ValueError("Use a new fixture directory")
    target = (
        np.frombuffer(read_pcm(raw / "target.wav")[0].data, dtype="<i2").astype(
            np.float64
        )
        / 32768
    )
    background = (
        np.frombuffer(read_pcm(raw / "background.wav")[0].data, dtype="<i2").astype(
            np.float64
        )
        / 32768
    )
    enrollment = read_pcm(raw / "enrollment.wav", enrollment=True)[0].data
    size = 12 * 16000

    def placed(values, offset):
        start = int(offset * 16000)
        if start + len(values) > size:
            raise ValueError("Synthetic phrase is too long; do not truncate speech")
        result = np.zeros(size)
        result[start : start + len(values)] = values
        return result

    target_stem = placed(target, 0.5)
    other_late = placed(background, 6)
    other_overlap = placed(background, 0.5)
    cases = [
        ("clean", "clean", 0.6 * target_stem, np.zeros(size), []),
        ("quiet", "quiet", 0.12 * target_stem, 0.35 * other_overlap, []),
        (
            "background",
            "multiple_speakers",
            0.6 * target_stem,
            0.35 * other_late,
            [[6, 6 + len(background) / 16000]],
        ),
        (
            "overlap",
            "overlapping_speakers",
            0.6 * target_stem,
            0.35 * other_overlap,
            [],
        ),
    ]
    if any(np.max(np.abs(t + b)) >= 1 for _, _, t, b, _ in cases):
        raise ValueError("Mixture would clip; refusing to change specified gains")
    destination.mkdir(parents=True)

    def write(name, data):
        with wave.open(str(destination / name), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(data)

    write("enrollment.wav", enrollment)
    fixtures = []
    for name, category, target_values, background_values, intervals in cases:
        write(
            name + ".wav",
            ((target_values + background_values) * 32768).astype("<i2").tobytes(),
        )
        write(name + "-target.wav", (target_values * 32768).astype("<i2").tobytes())
        fixtures.append(
            {
                "id": name,
                "category": category,
                "wav": name + ".wav",
                "enrollment": "enrollment.wav",
                "target_wav": name + "-target.wav",
                "background_only_intervals": intervals,
            }
        )
    (destination / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "fixture_kind": "offline_Windows_synthetic_voices",
                "fixtures": fixtures,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    create_fixtures(args.raw_dir, args.output_dir)
