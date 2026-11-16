"""Mocked processor contracts and benchmark plumbing, never model-quality tests."""

import hashlib
import io
import sys
import time
import wave
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import numpy as np
import pytest

from app.audio.interfaces import AudioFormat, AudioProcessingError, PCMChunk
from app.audio.processors import voxlock
from app.evaluation import voxlock as evaluation


@pytest.fixture
def processor_setup(monkeypatch, tmp_path):
    stream = Mock()
    stream.push.side_effect = lambda values: values
    stream.flush.return_value = np.array([], dtype=np.float32)
    model = Mock()
    model.enroll.get_providers.return_value = ["CPUExecutionProvider"]
    model.chunk.get_providers.return_value = ["CPUExecutionProvider"]
    model.stream.return_value = stream
    constructor = Mock(return_value=model)
    monkeypatch.setattr(voxlock, "verify_models", lambda _: {"test": "unit-only"})
    monkeypatch.setattr(voxlock, "_dependencies", lambda: (np, constructor))
    return voxlock.VoxLockConfig(tmp_path), model, stream, constructor


def enrolled(processor_setup):
    config, model, stream, _ = processor_setup
    processor = voxlock.VoxLockProcessor(config)
    processor.enroll(PCMChunk(bytes(96000)))
    return processor, model, stream


@pytest.mark.parametrize("rate,channels", [(0, 1), (True, 1), (16000.0, 1), (16000, 3)])
def test_format_validation(rate, channels):
    with pytest.raises(AudioProcessingError):
        AudioFormat(rate, channels)


@pytest.mark.parametrize(
    "data,format",
    [
        (b"x", AudioFormat()),
        (b"xx", AudioFormat(channels=2)),
        (bytearray(4), AudioFormat()),
        (b"", None),
    ],
)
def test_pcm_validation(data, format):
    with pytest.raises(AudioProcessingError):
        PCMChunk(data, format)


@pytest.mark.parametrize("threads", [0, 3, True, 1.5])
def test_configuration_thread_budget(threads):
    with pytest.raises(AudioProcessingError):
        voxlock.VoxLockConfig(Path("unused"), threads)


def test_cpu_constructor_and_lifecycle(processor_setup):
    config, model, stream, constructor = processor_setup
    with voxlock.VoxLockProcessor(config) as processor:
        constructor.assert_called_once_with(
            model_dir=config.model_dir, precision="int8", threads=1
        )
        model.enroll.set_providers.assert_called_once_with(["CPUExecutionProvider"])
        model.chunk.set_providers.assert_called_once_with(["CPUExecutionProvider"])
        with pytest.raises(AudioProcessingError, match="Enroll"):
            processor.process(PCMChunk(bytes(640)))
        processor.enroll(PCMChunk(bytes(96000)))
        assert processor.process(PCMChunk(bytes(640))).samples_per_channel == 320
        with pytest.raises(AudioProcessingError, match="Flush"):
            processor.enroll(PCMChunk(bytes(96000)))
        processor.flush()
        assert processor.flush().data == b""
        stream.flush.assert_called_once()
        with pytest.raises(AudioProcessingError, match="Enroll"):
            processor.process(PCMChunk(bytes(640)))
        processor.enroll(PCMChunk(bytes(96000)))
    assert processor._model is None and processor._stream is None
    processor.close()
    with pytest.raises(AudioProcessingError, match="closed"):
        processor.flush()


@pytest.mark.parametrize("rate,channels", [(8000, 1), (48000, 1), (16000, 2)])
def test_no_implicit_resampling(processor_setup, rate, channels):
    processor, _, _ = enrolled(processor_setup)
    with pytest.raises(AudioProcessingError, match="16000"):
        processor.process(PCMChunk(bytes(640), AudioFormat(rate, channels)))
    processor.close()


@pytest.mark.parametrize("samples", [0, 47999, 240001])
def test_enrollment_duration(processor_setup, samples):
    processor = voxlock.VoxLockProcessor(processor_setup[0])
    with pytest.raises(AudioProcessingError, match="Enrollment"):
        processor.enroll(PCMChunk(bytes(samples * 2)))
    processor.close()


def test_chunk_budget_and_empty_input(processor_setup):
    processor, _, stream = enrolled(processor_setup)
    assert processor.process(PCMChunk(b"")).data == b""
    stream.push.assert_not_called()
    with pytest.raises(AudioProcessingError, match="one second"):
        processor.process(PCMChunk(bytes(32002)))
    processor.close()


def test_initialization_failure_is_sanitized(processor_setup):
    config, _, _, constructor = processor_setup
    constructor.side_effect = RuntimeError("private/path/native/provider/payload")
    with pytest.raises(AudioProcessingError, match="CPU initialization") as error:
        voxlock.VoxLockProcessor(config)
    assert "private" not in str(error.value)


def test_optional_dependency_error(monkeypatch, tmp_path):
    monkeypatch.setattr(voxlock, "verify_models", lambda _: {})
    monkeypatch.setitem(sys.modules, "voxlock", None)
    with pytest.raises(AudioProcessingError, match="optional"):
        voxlock.VoxLockProcessor(voxlock.VoxLockConfig(tmp_path))


@pytest.mark.parametrize("operation", ["push", "flush", "enrollment", "nan"])
def test_native_failures_close_stream(processor_setup, operation):
    processor, model, stream = enrolled(processor_setup)
    if operation == "push":
        stream.push.side_effect = RuntimeError("private audio")
    elif operation == "nan":
        stream.push.side_effect = lambda _: np.array([np.nan])
    elif operation == "flush":
        stream.flush.side_effect = RuntimeError("native")
    else:
        model.stream.side_effect = RuntimeError("native")
    with pytest.raises(AudioProcessingError):
        if operation == "enrollment":
            processor.enroll(PCMChunk(bytes(96000)))
        elif operation == "flush":
            processor.flush()
        else:
            processor.process(PCMChunk(bytes(640)))
    assert processor._model is None and processor._stream is None


def test_clipping_is_counted_not_wrapped(processor_setup):
    processor, _, stream = enrolled(processor_setup)
    stream.push.side_effect = lambda _: np.array([2, -2], dtype=np.float32)
    result = np.frombuffer(processor.process(PCMChunk(bytes(640))).data, dtype="<i2")
    assert result.tolist() == [32767, -32768]
    assert processor.clipped_samples == 2
    processor.close()


def test_model_integrity_and_missing_files(monkeypatch, tmp_path):
    monkeypatch.setattr(
        voxlock, "MODEL_FILES", {"test.onnx": (4, hashlib.sha256(b"real").hexdigest())}
    )
    with pytest.raises(AudioProcessingError, match="missing"):
        voxlock.verify_models(tmp_path)
    (tmp_path / "test.onnx").write_bytes(b"real")
    assert (
        voxlock.verify_models(tmp_path)["test.onnx"]
        == hashlib.sha256(b"real").hexdigest()
    )
    (tmp_path / "test.onnx").write_bytes(b"fake")
    with pytest.raises(AudioProcessingError, match="integrity"):
        voxlock.verify_models(tmp_path)


def write_wav(path, seconds):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(bytes(32000 * seconds))


def test_benchmark_generation_and_cleanup(processor_setup, tmp_path, monkeypatch):
    for name, duration in (("input.wav", 1), ("enroll.wav", 3)):
        write_wav(tmp_path / name, duration)
    processor, _, _ = enrolled(processor_setup)
    monkeypatch.setattr(evaluation, "VoxLockProcessor", lambda _: processor)
    item = {
        "id": "clean",
        "category": "clean",
        "wav": "input.wav",
        "enrollment": "enroll.wav",
    }
    report, data = evaluation.evaluate_case(item, tmp_path, processor_setup[0], 40)
    assert report["status"] == "measured_local_cpu_inference"
    assert len(data) == 32000
    assert report["chunk_processing_seconds"]["count"] == 25
    assert report["physical_audio_latency_seconds"] is None
    assert report["comparison"]["target_preserved_human_judgment"] is None
    assert report["resources"]["cpu_seconds"] >= 0
    assert processor._model is None


def test_numeric_comparison_is_not_identity_judgment():
    signal = (np.sin(np.arange(16000) / 10) * 10000).astype("<i2")
    result = evaluation.compare_audio(
        signal.tobytes(), (signal // 2).astype("<i2").tobytes(), None, [[0, 1]]
    )
    assert 5.9 < result["background_only_attenuation_db"][0] < 6.1
    assert result["target_preserved_human_judgment"] is None


def test_download_is_explicit_and_integrity_checked(tmp_path, monkeypatch):
    data = b"unit-test-bytes-not-a-model"
    files = {"unit.onnx": (len(data), hashlib.sha256(data).hexdigest())}
    monkeypatch.setattr(evaluation, "MODEL_FILES", files)
    monkeypatch.setattr(voxlock, "MODEL_FILES", files)
    monkeypatch.setattr(evaluation, "require_ignored", lambda _: None)
    request = Mock(side_effect=lambda *_, **__: io.BytesIO(data))
    monkeypatch.setattr(evaluation.urllib.request, "urlopen", request)
    assert (
        evaluation.download_models(tmp_path)["unit.onnx"]
        == hashlib.sha256(data).hexdigest()
    )
    evaluation.download_models(tmp_path)
    request.assert_called_once()
    assert not (tmp_path / "unit.onnx.part").exists()


def test_bad_download_is_removed_not_used(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "MODEL_FILES", {"unit.onnx": (4, "invalid")})
    monkeypatch.setattr(evaluation, "require_ignored", lambda _: None)
    monkeypatch.setattr(
        evaluation.urllib.request, "urlopen", lambda *_, **__: io.BytesIO(b"test")
    )
    with pytest.raises(ValueError, match="verification"):
        evaluation.download_models(tmp_path)
    assert not (tmp_path / "unit.onnx").exists()
    assert not (tmp_path / "unit.onnx.part").exists()


def test_nonignored_artifacts_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation.subprocess, "run", lambda *_, **__: NS(returncode=1))
    with pytest.raises(ValueError, match="ignored"):
        evaluation.require_ignored(tmp_path)


def test_deadline_and_memory_guard_close_processor(
    processor_setup, tmp_path, monkeypatch
):
    for name, duration in (("input.wav", 1), ("enroll.wav", 3)):
        write_wav(tmp_path / name, duration)
    processor, _, _ = enrolled(processor_setup)
    monkeypatch.setattr(evaluation, "VoxLockProcessor", lambda _: processor)
    monkeypatch.setattr(
        evaluation, "memory_snapshot", lambda: {"rss_bytes": 2 * 1024**3}
    )
    item = {
        "id": "clean",
        "category": "clean",
        "wav": "input.wav",
        "enrollment": "enroll.wav",
    }
    with pytest.raises(AudioProcessingError, match="budget"):
        evaluation.evaluate_case(item, tmp_path, processor_setup[0], 40)
    assert processor._model is None


def test_generic_processor_deadline(processor_setup):
    processor, _, _ = enrolled(processor_setup)
    with pytest.raises(AudioProcessingError, match="budget"):
        evaluation.measure_stream(
            processor, PCMChunk(bytes(640)), 40, time.perf_counter() - 1
        )
    processor.close()


def test_generated_formats_are_not_accepted_implicitly(processor_setup):
    processor, _, stream = enrolled(processor_setup)
    stream.push.side_effect = lambda _: np.zeros(33000)
    with pytest.raises(AudioProcessingError):
        processor.process(PCMChunk(bytes(640)))
    assert processor._model is None
