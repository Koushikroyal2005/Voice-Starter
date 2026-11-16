"""Batch adapter and shared scoring contracts; no model download in tests."""

import hashlib
import subprocess
import sys
import wave
from pathlib import Path

import pytest

from app.audio.interfaces import AudioFormat, AudioProcessingError, PCMChunk
from app.audio.processors import deepfilternet as df
from app.evaluation.audio_scoring import compare_audio, comparison
from app.evaluation.resources import run_measured_child


@pytest.fixture
def executable(tmp_path, monkeypatch):
    path = tmp_path / "fake.exe"
    path.write_bytes(b"test fixture, not a real native binary")
    monkeypatch.setattr(df, "EXECUTABLE_SIZE", path.stat().st_size)
    monkeypatch.setattr(
        df, "EXECUTABLE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest()
    )
    return path


def echo_runner(command, **kwargs):
    assert kwargs["timeout"] == 60 and kwargs["check"]
    source, output = Path(command[1]), Path(command[3])
    output.mkdir()
    (output / "input.wav").write_bytes(source.read_bytes())
    return subprocess.CompletedProcess(command, 0)


@pytest.mark.parametrize("samples", [0, 1, 479, 480, 481, 48000])
def test_buffering_padding_duration_and_cleanup(executable, samples):
    locations = []

    def runner(command, **kwargs):
        locations.append(Path(command[1]).parent)
        return echo_runner(command, **kwargs)

    with df.DeepFilterNetProcessor(executable, runner=runner) as processor:
        data = b"\x01\0" * samples
        assert processor.process(PCMChunk(data, processor.format)).data == b""
        assert processor.flush().data == data
        assert processor.flush().data == b""
        with pytest.raises(AudioProcessingError, match="closed"):
            processor.process(PCMChunk(b"", processor.format))
    assert all(not path.exists() for path in locations)


def test_limits_formats_enrollment_and_close(executable):
    processor = df.DeepFilterNetProcessor(executable, runner=echo_runner)
    with pytest.raises(AudioProcessingError, match="48kHz"):
        processor.process(PCMChunk(b"\0\0"))
    with pytest.raises(AudioProcessingError, match="48kHz"):
        processor.process(PCMChunk(b"\0" * 4, AudioFormat(48000, 2)))
    with pytest.raises(AudioProcessingError, match="one second"):
        processor.process(PCMChunk(bytes(96002), processor.format))
    with pytest.raises(AudioProcessingError, match="enrollment"):
        processor.enroll(PCMChunk(b""))
    for _ in range(15):
        processor.process(PCMChunk(bytes(96000), processor.format))
    with pytest.raises(AudioProcessingError, match="15 seconds"):
        processor.process(PCMChunk(b"\0\0", processor.format))
    processor.close()
    processor.close()
    assert processor.flush().data == b"" and not processor._pending


@pytest.mark.parametrize("failure", ["timeout", "exit", "rate", "duration", "missing"])
def test_failed_native_process_closes_and_removes_audio(executable, failure):
    locations = []

    def runner(command, **kwargs):
        locations.append(Path(command[1]).parent)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 60)
        if failure == "exit":
            raise subprocess.CalledProcessError(1, command)
        if failure == "missing":
            return
        output = Path(command[3])
        output.mkdir()
        with wave.open(str(output / "input.wav"), "wb") as audio:
            audio.setparams(
                (1, 2, 16000 if failure == "rate" else 48000, 0, "NONE", "")
            )
            audio.writeframes(bytes(960 if failure == "rate" else 2))

    processor = df.DeepFilterNetProcessor(executable, runner=runner)
    processor.process(PCMChunk(bytes(960), processor.format))
    with pytest.raises(AudioProcessingError, match="failed or timed out"):
        processor.flush()
    assert processor._closed and not processor._pending
    assert all(not path.exists() for path in locations)


@pytest.mark.parametrize("failure", ["missing", "size", "hash"])
def test_unverified_executable_is_never_run(executable, failure):
    if failure == "missing":
        executable.unlink()
    elif failure == "size":
        executable.write_bytes(b"changed size")
    else:
        executable.write_bytes(b"x" * executable.stat().st_size)
    with pytest.raises(AudioProcessingError, match="Verified official"):
        df.DeepFilterNetProcessor(executable)


@pytest.mark.parametrize("rate", [16000, 48000])
def test_scoring_intervals_are_sample_rate_aware(rate):
    np = pytest.importorskip("numpy")
    data = np.ones(rate, dtype="<i2") * 100
    output = data.copy()
    output[rate // 2 :] //= 2
    result = compare_audio(
        data.tobytes(), output.tobytes(), None, [[0.5, 1]], sample_rate=rate
    )
    assert result["background_only_attenuation_db"][0] == pytest.approx(6.0206)
    assert (
        comparison(data.tobytes(), output.tobytes(), None, [], sample_rate=rate)[
            "aligned"
        ]
        is None
    )


def test_default_voxlock_scoring_stays_16khz():
    np = pytest.importorskip("numpy")
    source = (np.ones(16000, dtype="<i2") * 100).tobytes()
    assert compare_audio(source, source, source, [[0.5, 1]])[
        "background_only_attenuation_db"
    ] == [0]


def test_measured_child_success_and_timeout():
    result, metrics = run_measured_child(
        [sys.executable, "-c", "print('not captured')"],
        timeout=5,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert result.returncode == 0 and metrics["wall_seconds"] > 0
    with pytest.raises(subprocess.TimeoutExpired):
        run_measured_child(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            timeout=0.05,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
