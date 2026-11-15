"""Groq WAV transport seam; native LiveKit owns decoding, events and cancellation.

The installed OpenAI TTS plugin sends stream_format, rejected by Groq. Keep this
small adapter until the upstream plugin supports that request difference.
"""

import asyncio
from textwrap import wrap

import openai
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    tts,
    utils,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS


class GroqTTS(tts.TTS):
    def __init__(self, *, api_key: str, model: str, voice: str):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=24000,
            num_channels=1,
        )
        self._model = model
        self.voice = voice
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
            max_retries=0,
        )

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "groq"

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> tts.ChunkedStream:
        return _SpeechStream(tts=self, input_text=text, conn_options=conn_options)

    async def aclose(self) -> None:
        await self.client.close()


class _SpeechStream(tts.ChunkedStream):
    def __init__(
        self, *, tts: GroqTTS, input_text: str, conn_options: APIConnectOptions
    ):
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self.provider = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=self.provider.sample_rate,
            num_channels=1,
            mime_type="audio/wav",
            stream=True,
        )
        # Groq documents a 200-character limit. Each response is a separate WAV;
        # native emitter segments reset the decoder between independent WAV files.
        # This does not make the provider accept streaming text input.
        for text in wrap(self.input_text, width=200, break_on_hyphens=False):
            try:
                output_emitter.start_segment(segment_id=utils.shortuuid())
                async with asyncio.timeout(self._conn_options.timeout):
                    async with (
                        self.provider.client.audio.speech.with_streaming_response.create(
                            input=text,
                            model=self.provider.model,
                            voice=self.provider.voice,
                            response_format="wav",
                            timeout=self._conn_options.timeout,
                        ) as response
                    ):
                        async for chunk in response.iter_bytes():
                            output_emitter.push(chunk)
                output_emitter.end_segment()
            except (TimeoutError, openai.APITimeoutError):
                raise APITimeoutError("Groq speech request timed out") from None
            except openai.APIStatusError as error:
                # Do not propagate provider bodies: they may echo private input.
                raise APIStatusError(
                    "Groq speech request failed",
                    status_code=error.status_code,
                    body=None,
                    retryable=error.status_code in (429, 500, 502, 503, 504),
                ) from None
            except openai.APIConnectionError:
                raise APIConnectionError("Groq speech connection failed") from None
