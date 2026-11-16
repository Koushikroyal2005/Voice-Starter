"""Contract tests with a fake native ABI, not fake benchmark inference."""

import math
import struct
import wave
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest

from app.audio.interfaces import AudioFormat, AudioProcessingError, PCMChunk
from app.audio.processors import rnnoise
from app.evaluation.rnnoise import comparison, read_pcm


class Native:
    def __init__(self):
        self.frames = []
        self.destroyed = []
        self.transform = lambda value: value
        self.probability = 0.5

    def rnnoise_get_frame_size(self):
        return 480

    def rnnoise_create(self, model):
        assert model is None
        return 123

    def rnnoise_destroy(self, state):
        self.destroyed.append(state)

    def rnnoise_process_frame(self, state, output, source):
        assert state == 123
        self.frames.append(list(source))
        for index, value in enumerate(source):
            output[index] = self.transform(value)
        return self.probability


@pytest.fixture
def native(monkeypatch):
    library = Native()
    monkeypatch.setattr(rnnoise, "_library", lambda: library)
    return library


def chunk(samples):
    return PCMChunk(struct.pack(f"<{len(samples)}h", *samples), AudioFormat(48000))


def test_pcm_units_buffering_padding_and_cleanup(native):
    with rnnoise.RNNoiseProcessor() as processor:
        first = chunk([-32768, 32767] * 200)
        assert processor.process(first).data == b""
        rest = chunk([123] * 81)
        result = processor.process(rest).data + processor.flush().data
        assert result == first.data + rest.data
        assert native.frames[0][:2] == [-32768, 32767]
        assert native.frames[1][1:] == [0] * 479
        assert processor.flush().data == b""
        with pytest.raises(AudioProcessingError, match="closed"):
            processor.process(chunk([0]))
    assert native.destroyed == [123]


@pytest.mark.parametrize("size", [0, 1, 479, 480, 481, 960, 48000])
def test_arbitrary_chunk_sizes_preserve_duration(native, size):
    with rnnoise.RNNoiseProcessor() as processor:
        source = chunk([1] * size)
        assert processor.process(source).data + processor.flush().data == source.data


@pytest.mark.parametrize("fmt", [AudioFormat(), AudioFormat(48000, 2)])
def test_reject_wrong_format_without_resampling(native, fmt):
    with rnnoise.RNNoiseProcessor() as processor:
        with pytest.raises(AudioProcessingError, match="48kHz"):
            processor.process(PCMChunk(bytes(2 * fmt.channels), fmt))


def test_limits_and_no_enrollment(native):
    with rnnoise.RNNoiseProcessor() as processor:
        with pytest.raises(AudioProcessingError, match="one second"):
            processor.process(chunk([0] * 48001))
        with pytest.raises(AudioProcessingError, match="enrollment"):
            processor.enroll(chunk([0]))
        assert processor.process(chunk([])).data == b""
    assert native.destroyed == [123]


@pytest.mark.parametrize("failure", ["nan", "probability", "exception"])
def test_native_failure_closes_and_sanitizes(native, failure):
    native.transform = lambda value: math.nan if failure == "nan" else value
    native.probability = 2 if failure == "probability" else 0.5
    if failure == "exception":
        native.transform = lambda _: 1 / 0
    processor = rnnoise.RNNoiseProcessor()
    with pytest.raises(AudioProcessingError, match="processing failed"):
        processor.process(chunk([1] * 480))
    processor.close()
    assert native.destroyed == [123]


def test_flush_failure_also_releases(native):
    processor = rnnoise.RNNoiseProcessor()
    processor.process(chunk([1]))
    native.probability = math.nan
    with pytest.raises(AudioProcessingError, match="flush failed"):
        processor.flush()
    assert native.destroyed == [123]


def test_output_clips_not_wraps(native):
    native.transform = lambda value: value * 2
    with rnnoise.RNNoiseProcessor() as processor:
        output = processor.process(chunk([-32768, 32767] * 240))
        assert output.data == chunk([-32768, 32767] * 240).data
        assert processor.clipped_samples == 480


def test_repeated_initialization_and_idempotent_cleanup(native):
    for _ in range(20):
        with rnnoise.RNNoiseProcessor() as processor:
            assert processor.process(chunk([0] * 481)).data == bytes(960)
            assert processor.flush().data == bytes(2)
            processor.close()
    assert len(native.destroyed) == 20


def test_independent_processors_can_be_called_concurrently(monkeypatch):
    # The contract is one owner per instance, not shared-instance thread safety.
    barrier = Barrier(2)

    def run(value):
        with rnnoise.RNNoiseProcessor() as processor:
            barrier.wait(timeout=5)
            source = chunk([value] * 481)
            return processor.process(source).data + processor.flush().data

    monkeypatch.setattr(rnnoise, "_library", Native)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, value) for value in (-32768, 32767)]
        results = [future.result(timeout=10) for future in futures]
    assert results == [chunk([value] * 481).data for value in (-32768, 32767)]


@pytest.mark.parametrize("failure", ["size", "allocation"])
def test_incompatible_native_library(native, failure):
    if failure == "size":
        native.rnnoise_get_frame_size = lambda: 160
    else:
        native.rnnoise_create = lambda _: None
    with pytest.raises(AudioProcessingError):
        rnnoise.RNNoiseProcessor()
    assert not native.destroyed


def test_missing_optional_distribution(monkeypatch):
    monkeypatch.setattr(rnnoise, "distribution", lambda _: 1 / 0)
    with pytest.raises(AudioProcessingError, match="optional pyrnnoise"):
        rnnoise._library()


def test_unverified_distribution(monkeypatch):
    monkeypatch.setattr(rnnoise, "distribution", lambda _: SimpleNamespace(version="0"))
    with pytest.raises(AudioProcessingError, match="optional pyrnnoise"):
        rnnoise._library()


@pytest.mark.parametrize(
    "rate,channels,width", [(16000, 1, 2), (48000, 2, 2), (48000, 1, 1)]
)
def test_evaluation_rejects_wrong_wav(tmp_path, rate, channels, width):
    path = tmp_path / "fixture.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setparams((channels, width, rate, 0, "NONE", ""))
        audio.writeframes(bytes(100 * channels * width))
    with pytest.raises(ValueError, match="48kHz"):
        read_pcm(path)


def test_comparison_uses_48khz_intervals_and_reports_alignment():
    np = pytest.importorskip("numpy")
    values = np.random.default_rng(4).integers(-1000, 1000, 9600, dtype="<i2")
    source = values.tobytes()
    output = (values // 2).astype("<i2").tobytes()
    result = comparison(source, output, source, [[0.1, 0.15]])
    assert result["raw"]["background_only_attenuation_db"][0] == pytest.approx(
        6.02, abs=0.02
    )
    assert result["estimated_alignment_samples"] == 0
    assert result["aligned"]["target_preserved_human_judgment"] is None
    delayed = (
        np.concatenate([np.zeros(960, dtype="<i2"), values[:-960]])
        .astype("<i2")
        .tobytes()
    )
    assert comparison(source, delayed, source, [])["estimated_alignment_samples"] == 960
