"""Verified HTTP contract and native audio/cancellation; no real provider calls."""

import asyncio
import io
import wave

import aiohttp
import pytest
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
)

from app.config.settings import ConfigurationError, Settings
from app.providers.factory import create_tts, preload_provider_plugins
from app.providers.registry import registry
from tests.test_voice_profiles import environment


def settings(**values):
    return Settings.from_env(environment(VOICE_PROFILE="groq_nvidia", **values))


def wav_bytes(*, rate=44100, channels=1, width=2):
    target = io.BytesIO()
    with wave.open(target, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(width)
        audio.setframerate(rate)
        audio.writeframes(b"\x01" * (rate // 10 * channels * width))
    return target.getvalue()


class Response:
    def __init__(self, *, status=200, payload=None, mime="audio/wav", block=False):
        self.status = status
        self.payload = wav_bytes() if payload is None else payload
        self.headers = {"Content-Type": mime}
        self.content = self
        self.block = block
        self.entered = asyncio.Event()
        self.closed = False

    async def __aenter__(self):
        self.entered.set()
        return self

    async def __aexit__(self, *_args):
        self.closed = True

    async def iter_chunked(self, _size):
        if self.block:
            await asyncio.Event().wait()
        yield self.payload


class Client:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response

    async def close(self):
        self.closed = True


def test_profile_registration_key_isolation_and_preload():
    config = settings(GOOGLE_API_KEY="", LLM_API_KEY="wrong-key")
    assert config.stt.provider == config.llm.provider == "groq"
    assert config.tts.provider == "nvidia"
    assert config.tts.api_key == "synthetic-nvidia"
    assert config.llm.api_key == "synthetic-groq"
    assert config.tts.model == "magpie-tts-multilingual"
    assert config.tts.voice == "Magpie-Multilingual.EN-US.Aria"
    assert config.tts.language == "en-US"
    assert config.allow_batch_stt and not config.require_interim
    assert config.turn_detection == "vad"
    assert not config.google_api_version
    spec = registry.get("tts", "nvidia")
    assert not spec.capabilities.streaming and spec.capabilities.multilingual
    assert spec.plugin_module == "app.providers.tts.nvidia"
    preload_provider_plugins([config.tts])
    assert registry.get("llm", "nvidia").model == "meta/llama-3.3-70b-instruct"


@pytest.mark.parametrize(
    "overrides",
    [{"NVIDIA_API_KEY": ""}, {"TTS_VOICE": "unknown"}, {"TTS_LANGUAGE": "te"}],
)
def test_invalid_configuration(overrides):
    with pytest.raises(ConfigurationError):
        settings(**overrides)


def test_real_native_pcm_frames_and_request_contract():
    async def check():
        response = Response()
        client = Client(response)
        provider = create_tts(settings().tts)
        provider._session = client
        try:
            frames = []
            async with provider.synthesize("Hello.") as stream:
                async for event in stream:
                    frames.append(event.frame)
            assert frames
            assert all(f.sample_rate == 44100 and f.num_channels == 1 for f in frames)
            assert sum(f.samples_per_channel for f in frames) == 4410
            assert b"".join(bytes(f.data) for f in frames) == b"\x01" * 8820
            url, kwargs = client.calls[0]
            assert url == settings().tts.base_url + "/v1/audio/synthesize"
            assert kwargs["headers"]["Authorization"] == "Bearer synthetic-nvidia"
            assert kwargs["allow_redirects"] is False
            assert isinstance(kwargs["data"], aiohttp.FormData)
            fields = {part[0]["name"]: part[2] for part in kwargs["data"]._fields}
            assert fields == {
                "text": "Hello.",
                "language": "en-US",
                "voice": settings().tts.voice,
                "encoding": "LINEAR_PCM",
                "sample_rate_hz": "44100",
            }
            assert response.closed
        finally:
            await provider.aclose()
        assert client.closed

    asyncio.run(check())


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 429, 500])
def test_errors_are_sanitized_and_never_emit_provider_body(status):
    async def check():
        response = Response(status=status, payload=b"private transcript and api key")
        provider = create_tts(settings().tts)
        provider._session = client = Client(response)
        try:
            with pytest.raises(APIStatusError) as caught:
                async with provider.synthesize(
                    "private transcript", conn_options=APIConnectOptions(max_retry=0)
                ) as stream:
                    async for _ in stream:
                        pytest.fail("Error response emitted audio")
            assert caught.value.status_code == status
            assert caught.value.body is None
            assert "private" not in str(caught.value)
            assert len(client.calls) == 1
            assert response.closed
        finally:
            await provider.aclose()

    asyncio.run(check())


@pytest.mark.parametrize(
    "variant",
    ["bad_wav", "rate", "width", "channels", "mime", "truncated", "oversized"],
)
def test_invalid_audio_is_rejected_before_emitting(variant):
    async def check():
        payload = {
            "bad_wav": b"not audio",
            "rate": wav_bytes(rate=24000),
            "width": wav_bytes(width=1),
            "channels": wav_bytes(channels=2),
            "truncated": wav_bytes()[:-2],
            "oversized": b"x" * (16 * 1024 * 1024 + 1),
        }.get(variant, wav_bytes())
        response = Response(
            payload=payload,
            mime="application/json" if variant == "mime" else "audio/wav",
        )
        provider = create_tts(settings().tts)
        provider._session = Client(response)
        try:
            with pytest.raises(APIConnectionError):
                async with provider.synthesize(
                    "Hello.", conn_options=APIConnectOptions(max_retry=0)
                ) as stream:
                    async for _ in stream:
                        pytest.fail("Malformed audio emitted")
            assert response.closed
        finally:
            await provider.aclose()

    asyncio.run(check())


@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_and_cancellation_close_response(cancel):
    async def check():
        response = Response(block=True)
        provider = create_tts(settings().tts)
        provider._session = Client(response)
        stream = provider.synthesize(
            "Hello.", conn_options=APIConnectOptions(max_retry=0, timeout=0.05)
        )
        try:
            if cancel:
                await asyncio.wait_for(response.entered.wait(), timeout=2)
                await asyncio.wait_for(stream.aclose(), timeout=2)
            else:
                with pytest.raises(APITimeoutError):
                    async for _ in stream:
                        pass
            assert response.closed
        finally:
            await stream.aclose()
            await provider.aclose()

    asyncio.run(check())
