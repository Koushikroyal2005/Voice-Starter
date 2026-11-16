"""Optional CPU RNNoise experiment. No resampling, enrollment or LiveKit wiring."""

import ctypes
import math
import platform
import struct
from importlib.metadata import distribution

from app.audio.interfaces import AudioFormat, AudioProcessingError, PCMChunk


def _library():
    # Locate only the packaged native library: importing pyrnnoise also imports
    # its unrelated file-conversion/plotting stack. No arbitrary DLL search path.
    try:
        package = distribution("pyrnnoise")
        if package.version != "0.4.5":
            raise ValueError("Unverified RNNoise distribution version")
        name = {
            "Windows": "rnnoise.dll",
            "Linux": "librnnoise.so",
            "Darwin": "librnnoise.dylib",
        }[platform.system()]
        lib = ctypes.CDLL(str(package.locate_file("pyrnnoise/" + name)))
        lib.rnnoise_get_frame_size.restype = ctypes.c_int
        lib.rnnoise_create.argtypes = [ctypes.c_void_p]
        lib.rnnoise_create.restype = ctypes.c_void_p
        lib.rnnoise_destroy.argtypes = [ctypes.c_void_p]
        lib.rnnoise_destroy.restype = None
        lib.rnnoise_process_frame.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.POINTER(ctypes.c_float),
        ]
        lib.rnnoise_process_frame.restype = ctypes.c_float
        return lib
    except Exception:
        raise AudioProcessingError(
            "Install the optional pyrnnoise 0.4.5 native wheel for this platform"
        ) from None


class RNNoiseProcessor:
    """Single-stream, mono 48kHz PCM16; buffers incomplete 480-sample frames.

    Returns native delayed audio, not delay-compensated audio. Flush pads only
    the last partial frame, trims padding, and releases the state. Native filter
    tail beyond the input duration is not emitted. Not thread-safe.
    """

    format = AudioFormat(sample_rate=48000)
    frame_samples = 480

    def __init__(self):
        self._state = None
        self._pending = b""
        self._closed = False
        self._flushed = False
        self.clipped_samples = 0
        self._lib = _library()
        if self._lib.rnnoise_get_frame_size() != self.frame_samples:
            raise AudioProcessingError("Unsupported RNNoise native frame size")
        self._state = self._lib.rnnoise_create(None)
        if not self._state:
            raise AudioProcessingError("RNNoise state allocation failed")

    def enroll(self, sample: PCMChunk) -> None:
        raise AudioProcessingError("RNNoise does not support target-speaker enrollment")

    def _frame(self, data: bytes) -> bytes:
        # C API expects float samples in PCM16 units, NOT normalized [-1, 1].
        source = (ctypes.c_float * 480)(*struct.unpack("<480h", data))
        output = (ctypes.c_float * 480)()
        probability = self._lib.rnnoise_process_frame(self._state, output, source)
        if not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError("Invalid native speech probability")
        values = []
        for value in output:
            if not math.isfinite(value):
                raise ValueError("Invalid native audio")
            self.clipped_samples += int(value < -32768 or value > 32767)
            values.append(round(max(-32768, min(32767, value))))
        return struct.pack("<480h", *values)

    def process(self, chunk: PCMChunk) -> PCMChunk:
        if self._closed or self._flushed:
            raise AudioProcessingError("RNNoise stream is closed or flushed")
        if chunk.format != self.format or chunk.samples_per_channel > 48000:
            raise AudioProcessingError(
                "Use mono 48kHz PCM16 chunks of at most one second"
            )
        try:
            data = self._pending + chunk.data
            end = len(data) // 960 * 960
            result = b"".join(
                self._frame(data[i : i + 960]) for i in range(0, end, 960)
            )
            self._pending = data[end:]
            return PCMChunk(result, self.format)
        except Exception:
            self.close()
            raise AudioProcessingError("RNNoise frame processing failed") from None

    def flush(self) -> PCMChunk:
        if self._closed or self._flushed:
            return PCMChunk(b"", self.format)
        try:
            data = (
                self._frame(self._pending.ljust(960, b"\0"))[: len(self._pending)]
                if self._pending
                else b""
            )
            self._flushed = True
            return PCMChunk(data, self.format)
        except Exception:
            raise AudioProcessingError("RNNoise flush failed") from None
        finally:
            self.close()

    def close(self) -> None:
        state, self._state = self._state, None
        self._pending = b""
        self._closed = True
        if state:
            self._lib.rnnoise_destroy(state)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
