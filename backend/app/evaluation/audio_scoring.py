"""Provider-independent PCM16 scoring with sample-rate-aware intervals."""

import math

from app.audio.interfaces import AudioProcessingError


def compare_audio(
    original: bytes,
    processed: bytes,
    target: bytes | None,
    intervals,
    *,
    sample_rate=16000,
):
    """Known-reference signal error and labeled background-only energy, not ASR."""
    import numpy as np

    def samples(data):
        return np.frombuffer(data, dtype="<i2").astype(np.float64) / 32768

    source, output = samples(original), samples(processed)
    if len(source) != len(output):
        raise AudioProcessingError("Output duration differs from input")

    def energy(values):
        return float(np.mean(values**2))

    def db_ratio(numerator, denominator):
        return (
            10 * math.log10(numerator / denominator)
            if numerator and denominator
            else None
        )

    result = {
        "input_rms": math.sqrt(energy(source)),
        "output_rms": math.sqrt(energy(output)),
        "scale_sensitive_sdr_input_db": None,
        "scale_sensitive_sdr_output_db": None,
        "background_only_attenuation_db": [],
        "target_preserved_human_judgment": None,
        "background_suppressed_human_judgment": None,
    }
    if target is not None:
        expected = samples(target)
        if len(expected) != len(source):
            raise ValueError("Target reference must be sample-aligned and equal length")
        for label, values in (("input", source), ("output", output)):
            result[f"scale_sensitive_sdr_{label}_db"] = db_ratio(
                energy(expected), energy(values - expected)
            )
    for start, end in intervals:
        start_sample, end_sample = int(start * sample_rate), int(end * sample_rate)
        if not 0 <= start_sample < end_sample <= len(source):
            raise ValueError("Invalid background-only interval")
        result["background_only_attenuation_db"].append(
            db_ratio(
                energy(source[start_sample:end_sample]),
                energy(output[start_sample:end_sample]),
            )
        )
    return result


def comparison(original, output, target, intervals, *, sample_rate=48000):
    import numpy as np

    result = {
        "raw": compare_audio(
            original, output, target, intervals, sample_rate=sample_rate
        )
    }
    result["estimated_alignment_samples"] = None
    result["aligned"] = None
    if target is not None:
        reference = np.frombuffer(target, dtype="<i2").astype(np.float64)
        actual = np.frombuffer(output, dtype="<i2").astype(np.float64)
        # Bounded offline cross-correlation, 0..40ms; no timestamps invented.
        # Decimate by 4 only for lag estimation; retain full-rate SDR comparison.
        scores = [
            float(np.dot(reference[: len(actual) - lag : 4], actual[lag::4]))
            for lag in range(0, min(int(sample_rate * 0.04), len(actual) - 1) + 1, 4)
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
