"""Offline scoring contracts; these do not measure perceptual quality."""

import json
import struct

import pytest

from app.audio.interfaces import AudioProcessingError
from app.evaluation.audio_scoring import compare_audio, comparison


@pytest.mark.parametrize("rate", [0, -1, True, 16000.0, float("nan"), None])
def test_scoring_rejects_invalid_sample_rate(rate):
    with pytest.raises(ValueError, match="sample rate"):
        compare_audio(bytes(4), bytes(4), None, [], sample_rate=rate)


@pytest.mark.parametrize("data", [b"", b"x"])
def test_scoring_rejects_empty_or_partial_pcm(data):
    with pytest.raises(AudioProcessingError, match="PCM16"):
        compare_audio(data, data, None, [])


def test_silent_audio_has_finite_json_and_no_invented_alignment():
    result = comparison(bytes(960), bytes(960), bytes(960), [[0, 0.01]])
    assert result["raw"]["input_rms"] == 0
    assert result["raw"]["output_rms"] == 0
    assert result["raw"]["background_only_attenuation_db"] == [None]
    assert result["estimated_alignment_samples"] is None
    json.dumps(result, allow_nan=False)


def test_pcm_boundaries_are_signed_little_endian():
    data = struct.pack("<2h", -32768, 32767)
    result = compare_audio(data, data, data, [])
    assert result["input_rms"] == pytest.approx(0.9999847413)
    assert result["output_rms"] == result["input_rms"]


@pytest.mark.parametrize("target", [b"x", bytes(2)])
def test_invalid_reference_is_rejected(target):
    with pytest.raises((AudioProcessingError, ValueError)):
        compare_audio(bytes(4), bytes(4), target, [])
