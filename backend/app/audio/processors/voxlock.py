"""Native VoxLock 1.3 INT8 streaming adapter; explicit enrollment and CPU only."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.audio.interfaces import AudioFormat, AudioProcessingError, PCMChunk

MODEL_REVISION = "2413b292bc2c337bfc19a9802aaf3e011e68e9c4"
# Official HF LFS SHA-256 and byte counts, not hashes of the Git LFS pointers.
MODEL_FILES = {
    "enroll.onnx": (
        21023799,
        "81f305c9b7a32f13d1401f53bb4c6301826a607c9e807e60912f36ef1b9fae29",
    ),
    "chunk_int8.onnx": (
        56560589,
        "c50ffdc8d723fd4f91cb08889f3d0143491f95967b705f35c444a0b4afe88172",
    ),
}


def verify_models(directory: Path) -> dict[str, str]:
    hashes = {}
    for name, (size, expected) in MODEL_FILES.items():
        path = directory / name
        if not path.is_file() or path.stat().st_size != size:
            raise AudioProcessingError(
                "Required local INT8 model file is missing or invalid"
            )
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != expected:
            raise AudioProcessingError("Local model integrity check failed")
        hashes[name] = digest
    return hashes


@dataclass(frozen=True)
class VoxLockConfig:
    model_dir: Path
    threads: int = 1

    def __post_init__(self):
        if not isinstance(self.model_dir, Path):
            raise AudioProcessingError("Supply an explicit local model directory")
        if type(self.threads) is not int or self.threads not in (1, 2):
            raise AudioProcessingError("Use one or two CPU threads")


def _dependencies():
    try:
        import numpy
        from voxlock import VoxLock
    except ImportError:
        raise AudioProcessingError(
            "VoxLock is optional; install requirements-voxlock.txt "
            "in an isolated environment"
        ) from None
    return numpy, VoxLock


class VoxLockProcessor:
    format = AudioFormat()

    def __init__(self, config: VoxLockConfig):
        self._model = self._stream = None
        self._closed = self._started = self._flushed = False
        self.clipped_samples = 0
        self.model_hashes = verify_models(config.model_dir)
        self._np, constructor = _dependencies()
        try:
            self._model = constructor(
                model_dir=config.model_dir, precision="int8", threads=config.threads
            )
            for session in (self._model.enroll, self._model.chunk):
                session.set_providers(["CPUExecutionProvider"])
                if session.get_providers() != ["CPUExecutionProvider"]:
                    raise AudioProcessingError("CPU execution could not be selected")
        except Exception:
            self.close()
            raise AudioProcessingError("VoxLock CPU initialization failed") from None

    def _validate(self, chunk: PCMChunk):
        if self._closed:
            raise AudioProcessingError("Processor is closed")
        if not isinstance(chunk, PCMChunk) or chunk.format != self.format:
            raise AudioProcessingError("VoxLock requires mono PCM16 at 16000 Hz")

    def _decode(self, chunk):
        return (
            self._np.frombuffer(chunk.data, dtype="<i2").astype(self._np.float32)
            / 32768
        )

    def _encode(self, samples):
        values = self._np.asarray(samples)
        if values.ndim != 1 or not self._np.isfinite(values).all():
            raise AudioProcessingError("VoxLock returned invalid audio")
        if len(values) > 32000:
            raise AudioProcessingError("Unexpectedly large buffered output")
        self.clipped_samples += int(
            self._np.sum((values < -1) | (values > 32767 / 32768))
        )
        data = (
            (self._np.clip(values, -1, 32767 / 32768) * 32768).astype("<i2").tobytes()
        )
        return PCMChunk(data, self.format)

    def enroll(self, sample: PCMChunk) -> None:
        self._validate(sample)
        if not 48000 <= sample.samples_per_channel <= 240000:
            raise AudioProcessingError(
                "Enrollment must contain 3 to 15 seconds of target speech"
            )
        if self._started and not self._flushed:
            raise AudioProcessingError("Flush the active stream before re-enrollment")
        try:
            self._stream = self._model.stream(self._decode(sample))
            self._started = self._flushed = False
        except Exception:
            self.close()
            raise AudioProcessingError("VoxLock enrollment failed") from None

    def process(self, chunk: PCMChunk) -> PCMChunk:
        self._validate(chunk)
        if self._stream is None or self._flushed:
            raise AudioProcessingError("Enroll a target before starting a new stream")
        if chunk.samples_per_channel > 16000:
            raise AudioProcessingError(
                "Each processing chunk must be at most one second"
            )
        if not chunk.data:
            return PCMChunk(b"", self.format)
        try:
            self._started = True
            return self._encode(self._stream.push(self._decode(chunk)))
        except Exception:
            self.close()
            raise AudioProcessingError(
                "VoxLock inference failed; stream closed"
            ) from None

    def flush(self) -> PCMChunk:
        self._validate(PCMChunk(b""))
        if self._flushed:
            return PCMChunk(b"", self.format)
        if self._stream is None:
            raise AudioProcessingError("No enrolled stream to flush")
        try:
            output = self._encode(self._stream.flush())
            self._flushed = True
            return output
        except Exception:
            self.close()
            raise AudioProcessingError("VoxLock flush failed; stream closed") from None

    def close(self) -> None:
        # ONNX Runtime has no public session.close(); release owned references.
        self._stream = self._model = None
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
