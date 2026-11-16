"""Sustained replay contract tests; real audio acceptance stays opt-in."""

import wave

import pytest

from app.audio.interfaces import AudioFormat, AudioProcessingError, PCMChunk
from app.evaluation import rnnoise_sustained as replay


class Echo:
    format = AudioFormat(48000)
    clipped_samples = 0
    closed = False

    def process(self, chunk):
        return chunk

    def flush(self):
        return PCMChunk(b"", self.format)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True


def wav(path, data=b"\1\0", rate=48000, channels=1):
    with wave.open(str(path), "wb") as audio:
        audio.setparams((channels, 2, rate, 0, "NONE", ""))
        audio.writeframes(data)
    return path


@pytest.mark.parametrize("chunk_ms", [10, 20, 40])
def test_replay_repeats_short_source_and_writes_wav_pair(
    tmp_path, monkeypatch, chunk_ms
):
    monkeypatch.setattr(replay, "require_ignored", lambda _: None)
    source = wav(tmp_path / "input.wav")
    destination = tmp_path / "output"
    report = replay.run(
        source, destination, chunk_ms=chunk_ms, seconds=1, paced=False, factory=Echo
    )
    assert report["output_samples"] == 48000
    assert report["source_loop_boundaries"] == 47999
    assert report["latency"]["count"] == 1000 // chunk_ms
    assert report["human_listening"] is None
    assert report["latency"]["scheduled_completion_deadline_exceeded_count"] is None
    for name in ("original.wav", "processed.wav"):
        assert replay.read_recording(destination / name) == b"\1\0" * 48000
    with pytest.raises(FileExistsError):
        replay.run(source, destination, chunk_ms=chunk_ms, seconds=1, factory=Echo)


@pytest.mark.parametrize(
    "chunk_ms,seconds", [(5, 1), (10, 0), (20, 301), (40, float("nan"))]
)
def test_bounded_arguments(tmp_path, chunk_ms, seconds):
    with pytest.raises(ValueError, match="10/20/40"):
        replay.run(
            tmp_path / "missing.wav",
            tmp_path / "out",
            chunk_ms=chunk_ms,
            seconds=seconds,
        )


def test_percentiles_and_deadlines():
    report = replay.summarize(
        [0.001, 0.002, 0.03, 0.04], [0.01] * 4, [0, 0, 0.02, 0.03]
    )
    assert report["average_seconds"] == pytest.approx(0.01825)
    assert report["p95_seconds"] == report["p99_seconds"] == 0.04
    assert report["processing_budget_exceeded_count"] == 2
    assert report["scheduled_completion_deadline_exceeded_count"] == 2


def test_pacing_and_overruns_with_virtual_clock(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "require_ignored", lambda _: None)
    clock = [0.0]
    sleeps = []
    monkeypatch.setattr(replay.time, "perf_counter", lambda: clock[0])

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(replay.time, "sleep", sleep)

    class Slow(Echo):
        def process(self, chunk):
            clock[0] += 0.025
            return chunk

    report = replay.run(
        wav(tmp_path / "in.wav"), tmp_path / "out", chunk_ms=20, seconds=1, factory=Slow
    )
    assert len(sleeps) == 50
    assert report["latency"]["processing_budget_exceeded_count"] == 50
    assert report["latency"]["scheduled_completion_deadline_exceeded_count"] == 50
    assert report["processing_real_time_factor"] == pytest.approx(1.25)


def test_failed_processor_is_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "require_ignored", lambda _: None)

    class Broken(Echo):
        def process(self, chunk):
            raise AudioProcessingError("failure")

    processor = Broken()
    with pytest.raises(AudioProcessingError):
        replay.run(
            wav(tmp_path / "in.wav"),
            tmp_path / "out",
            chunk_ms=10,
            seconds=1,
            factory=lambda: processor,
        )
    assert processor.closed


@pytest.mark.parametrize(
    "rate,channels,data", [(16000, 1, b"\0\0"), (48000, 2, bytes(4)), (48000, 1, b"")]
)
def test_recording_format_rejection(tmp_path, rate, channels, data):
    with pytest.raises(ValueError):
        replay.read_recording(
            wav(tmp_path / "wrong.wav", data=data, rate=rate, channels=channels)
        )


def test_nonignored_outputs_rejected(tmp_path):
    with pytest.raises(ValueError, match="ignored"):
        replay.run(
            wav(tmp_path / "in.wav"),
            tmp_path / "out",
            chunk_ms=10,
            seconds=1,
            factory=Echo,
        )
