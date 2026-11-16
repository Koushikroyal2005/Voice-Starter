"""Small synchronous PCM16 stream contract, consumed by local evaluation."""

from dataclasses import dataclass
from typing import Protocol


class AudioProcessingError(RuntimeError):
    """Safe configuration, lifecycle or inference failure; no audio payloads."""


@dataclass(frozen=True)
class AudioFormat:
    sample_rate: int = 16000
    channels: int = 1

    def __post_init__(self):
        if type(self.sample_rate) is not int or self.sample_rate <= 0:
            raise AudioProcessingError("Sample rate must be a positive integer")
        if type(self.channels) is not int or self.channels not in (1, 2):
            raise AudioProcessingError("PCM16 supports one or two channels")


@dataclass(frozen=True)
class PCMChunk:
    """Interleaved signed little-endian 16-bit PCM; empty output means buffered."""

    data: bytes
    format: AudioFormat = AudioFormat()

    def __post_init__(self):
        if not isinstance(self.format, AudioFormat):
            raise AudioProcessingError("Audio format metadata is required")
        if not isinstance(self.data, bytes) or len(self.data) % (
            2 * self.format.channels
        ):
            raise AudioProcessingError("PCM16 bytes must contain whole channel frames")

    @property
    def samples_per_channel(self) -> int:
        return len(self.data) // (2 * self.format.channels)


class AudioProcessor(Protocol):
    """Buffered output is allowed. Enroll only when the implementation requires it.

    Call flush once at stream end, then close in finally. This is not a model
    for diarization results; add such a distinct contract only when needed.
    """

    @property
    def format(self) -> AudioFormat: ...
    def enroll(self, sample: PCMChunk) -> None: ...
    def process(self, chunk: PCMChunk) -> PCMChunk: ...
    def flush(self) -> PCMChunk: ...
    def close(self) -> None: ...
