"""Verified hosted Magpie HTTP transport using native LiveKit TTS events."""

import asyncio
import io
import wave

import aiohttp
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    tts,
    utils,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

MAX_AUDIO_BYTES = 16 * 1024 * 1024


class NvidiaMagpieTTS(tts.TTS):
    """Full-text HTTP synthesis; audio is emitted after validating the PCM WAV.

    This is not the Riva gRPC streaming API. Cancellation closes the HTTP response;
    already accepted remote inference may continue. No credentials enter errors.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        voice: str,
        language: str,
        base_url: str,
        http_session: aiohttp.ClientSession | None = None,
    ):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=44100,
            num_channels=1,
        )
        self._api_key = api_key
        self._model = model
        self.voice = voice
        self.language = "en-US" if language == "en" else language
        self._url = base_url.rstrip("/") + "/v1/audio/synthesize"
        self._session = http_session
        self._owns_session = http_session is None

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "nvidia"

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.ChunkedStream:
        return _SpeechStream(tts=self, input_text=text, conn_options=conn_options)

    async def aclose(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()


class _SpeechStream(tts.ChunkedStream):
    def __init__(self, *, tts: NvidiaMagpieTTS, input_text, conn_options):
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self.provider = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        provider = self.provider
        form = aiohttp.FormData()
        for name, value in {
            "text": self.input_text,
            "language": provider.language,
            "voice": provider.voice,
            "encoding": "LINEAR_PCM",
            "sample_rate_hz": str(provider.sample_rate),
        }.items():
            form.add_field(name, value, content_type="text/plain")
        if provider._session is None:
            provider._session = aiohttp.ClientSession()
        try:
            async with asyncio.timeout(self._conn_options.timeout):
                async with provider._session.post(
                    provider._url,
                    headers={"Authorization": "Bearer " + provider._api_key},
                    data=form,
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=self._conn_options.timeout),
                ) as response:
                    if response.status != 200:
                        raise APIStatusError(
                            "NVIDIA Magpie speech request failed",
                            status_code=response.status,
                            body=None,
                            retryable=response.status in (429, 500, 502, 503, 504),
                        )
                    if response.headers.get("Content-Type", "").split(";")[0] not in (
                        "audio/wav",
                        "audio/x-wav",
                    ):
                        raise ValueError
                    payload = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        payload.extend(chunk)
                        if len(payload) > MAX_AUDIO_BYTES:
                            raise ValueError
                    with wave.open(io.BytesIO(payload), "rb") as audio:
                        if (
                            audio.getcomptype() != "NONE"
                            or audio.getsampwidth() != 2
                            or audio.getnchannels() != provider.num_channels
                            or audio.getframerate() != provider.sample_rate
                            or audio.getnframes() == 0
                        ):
                            raise ValueError
                        pcm = audio.readframes(audio.getnframes())
                        if len(pcm) != audio.getnframes() * 2:
                            raise ValueError
            # PCM WAV data is signed 16-bit little-endian, exactly LiveKit's format.
            # Strip the validated container, retain 44.1kHz; LiveKit owns resampling.
            output_emitter.initialize(
                request_id=utils.shortuuid(),
                sample_rate=provider.sample_rate,
                num_channels=provider.num_channels,
                mime_type="audio/pcm",
            )
            output_emitter.push(pcm)
        except TimeoutError:
            raise APITimeoutError("NVIDIA Magpie speech request timed out") from None
        except aiohttp.ClientError:
            raise APIConnectionError("NVIDIA Magpie speech connection failed") from None
        except (ValueError, wave.Error, EOFError):
            raise APIConnectionError(
                "NVIDIA Magpie returned an invalid PCM WAV response", retryable=False
            ) from None
