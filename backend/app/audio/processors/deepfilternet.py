"""Optional official Windows CPU executable adapter; deliberately batch-only."""

import hashlib
import subprocess
import tempfile
import wave
from pathlib import Path

from app.audio.interfaces import AudioFormat, AudioProcessingError, PCMChunk

EXECUTABLE_SHA256 = "75e11fa16445f560cb6b021521ddb89e89270d13b83089705d98776f58fd7915"
EXECUTABLE_SIZE = 26912256


class DeepFilterNetProcessor:
    """Buffers <=15s and runs genuine DFN3 inference at flush, not per chunk.

    The official v0.5.6 executable embeds DFN3. No implicit download, model
    substitution, resampling, enrollment or live-session integration is allowed.
    Runner is the standard subprocess.run callable seam for bounded evaluation.
    """

    format = AudioFormat(48000)
    streaming = False

    def __init__(self, executable: Path, *, runner=subprocess.run):
        try:
            if executable.stat().st_size != EXECUTABLE_SIZE:
                raise ValueError("Unexpected binary size")
            with executable.open("rb") as source:
                if (
                    hashlib.file_digest(source, "sha256").hexdigest()
                    != EXECUTABLE_SHA256
                ):
                    raise ValueError("Unexpected binary hash")
        except Exception:
            raise AudioProcessingError(
                "Verified official DeepFilterNet v0.5.6 Windows executable required"
            ) from None
        self._executable = executable.resolve()
        self._runner = runner
        self._pending = bytearray()
        self._closed = False

    def enroll(self, sample: PCMChunk) -> None:
        raise AudioProcessingError(
            "DeepFilterNet does not support target-speaker enrollment"
        )

    def process(self, chunk: PCMChunk) -> PCMChunk:
        if self._closed:
            raise AudioProcessingError("DeepFilterNet stream is closed")
        if chunk.format != self.format or chunk.samples_per_channel > 48000:
            raise AudioProcessingError(
                "Use mono 48kHz PCM16 chunks of at most one second"
            )
        if len(self._pending) + len(chunk.data) > 15 * 48000 * 2:
            raise AudioProcessingError("Batch experiment is limited to 15 seconds")
        self._pending.extend(chunk.data)
        return PCMChunk(b"", self.format)

    def flush(self) -> PCMChunk:
        if self._closed:
            return PCMChunk(b"", self.format)
        try:
            if not self._pending:
                return PCMChunk(b"", self.format)
            length = len(self._pending)
            # CLI processes full 480-sample hops only. Pad one partial hop and
            # preserve raw native delay; trim only that padding, like RNNoise.
            padded = bytes(self._pending).ljust((length + 959) // 960 * 960, b"\0")
            with tempfile.TemporaryDirectory(prefix="voice-dfn-") as temporary:
                base = Path(temporary)
                with wave.open(str(base / "input.wav"), "wb") as audio:
                    audio.setparams((1, 2, 48000, 0, "NONE", ""))
                    audio.writeframes(padded)
                self._runner(
                    [
                        str(self._executable),
                        str(base / "input.wav"),
                        "--output-dir",
                        str(base / "out"),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                    check=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                with wave.open(str(base / "out" / "input.wav"), "rb") as audio:
                    if (
                        audio.getframerate(),
                        audio.getnchannels(),
                        audio.getsampwidth(),
                        audio.getnframes(),
                    ) != (48000, 1, 2, len(padded) // 2):
                        raise ValueError("Unexpected native audio format or duration")
                    data = audio.readframes(audio.getnframes())
                if len(data) != len(padded):
                    raise ValueError("Truncated native audio")
                return PCMChunk(data[:length], self.format)
        except Exception:
            raise AudioProcessingError(
                "DeepFilterNet batch inference failed or timed out"
            ) from None
        finally:
            self.close()

    def close(self) -> None:
        self._pending.clear()
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
