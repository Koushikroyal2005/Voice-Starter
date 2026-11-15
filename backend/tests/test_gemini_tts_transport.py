"""Native pinned plugin + official SDK transport contracts, without real API calls."""

import asyncio
import base64
import json
from unittest.mock import patch

import httpx2 as httpx
import pytest
from google import genai
from google.genai import types
from livekit.agents import APIConnectionError, APIConnectOptions, APIStatusError

from app.providers.factory import create_tts
from tests.test_gemini_voice import configuration

PCM = b"\x01\x00" * 2400  # test-only mono signed int16, 0.1 s at 24 kHz


def response():
    data = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "audio/L16;codec=pcm;rate=24000",
                                "data": base64.b64encode(PCM).decode(),
                            }
                        }
                    ]
                },
                "finishReason": "STOP",
            }
        ]
    }
    return httpx.Response(
        200,
        headers={"Content-Type": "text/event-stream"},
        content="data: " + json.dumps(data) + "\n\n",
    )


def client_factory(transport):
    def build(**kwargs):
        return genai.Client(
            **kwargs,
            http_options=types.HttpOptions(
                async_client_args={"transport": httpx.MockTransport(transport)},
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    return build


def test_default_v1_vs_beta_is_only_request_path_difference(monkeypatch):
    async def check():
        requests = []

        def transport(request):
            requests.append((request.url.path, json.loads(request.content)))
            if request.url.path.startswith("/v1/"):
                return httpx.Response(
                    400,
                    json={
                        "error": {
                            "code": 400,
                            "status": "INVALID_ARGUMENT",
                            "message": "Unknown name speechConfig at generation_config",
                        }
                    },
                )
            return response()

        with patch(
            "livekit.plugins.google.beta.gemini_tts.Client",
            side_effect=client_factory(transport),
        ):
            for version in (None, "v1beta"):
                if version is None:
                    monkeypatch.delenv("GOOGLE_GENAI_API_VERSION", raising=False)
                else:
                    monkeypatch.setenv("GOOGLE_GENAI_API_VERSION", version)
                provider = create_tts(configuration().tts)
                try:
                    async with provider.synthesize(
                        "Public test sentence.",
                        conn_options=APIConnectOptions(max_retry=0),
                    ) as stream:
                        if version is None:
                            with pytest.raises(APIStatusError) as caught:
                                async for _ in stream:
                                    pass
                            assert caught.value.status_code == 400
                        else:
                            frames = [event.frame async for event in stream]
                            assert frames
                            assert all(f.sample_rate == 24000 for f in frames)
                            assert all(f.num_channels == 1 for f in frames)
                            assert all(
                                len(f.data) == f.samples_per_channel for f in frames
                            )
                            assert b"".join(f.data.tobytes() for f in frames) == PCM
                finally:
                    await provider.aclose()
        assert requests[0][0].startswith("/v1/")
        assert requests[1][0].startswith("/v1beta/")
        assert requests[0][1] == requests[1][1]
        config = requests[1][1]["generationConfig"]
        assert config["responseModalities"] == ["AUDIO"]
        assert config["speechConfig"]["voice_config"]["prebuilt_voice_config"] == {
            "voice_name": "Kore"
        }
        assert requests[1][0].endswith(
            "gemini-3.1-flash-tts-preview:streamGenerateContent"
        )

    asyncio.run(check())


@pytest.mark.parametrize(
    "model,voice",
    [
        ("gemini-3.8-flash-tts", "Kore"),
        ("gemini-3.8-flash-lite-tts", "Puck"),
        ("gemini-3.1-flash-tts-preview", "Kore"),
    ],
)
def test_model_voice_and_pcm_request_mapping(monkeypatch, model, voice):
    monkeypatch.setenv("GOOGLE_GENAI_API_VERSION", "v1beta")

    async def check():
        requests = []

        def transport(request):
            requests.append(request)
            return response()

        with patch(
            "livekit.plugins.google.beta.gemini_tts.Client",
            side_effect=client_factory(transport),
        ):
            provider = create_tts(configuration(TTS_MODEL=model, TTS_VOICE=voice).tts)
            try:
                async with provider.synthesize("Test.") as stream:
                    assert [event async for event in stream]
            finally:
                with patch.object(
                    provider._client.aio, "aclose", wraps=provider._client.aio.aclose
                ) as close:
                    await provider.aclose()
                    close.assert_awaited_once()
        assert requests[0].url.path.endswith(f"{model}:streamGenerateContent")
        config = json.loads(requests[0].content)["generationConfig"]
        assert config["speechConfig"]["voice_config"]["prebuilt_voice_config"] == {
            "voice_name": voice
        }

    asyncio.run(check())


def test_transport_timeout_maps_to_native_error(monkeypatch):
    monkeypatch.setenv("GOOGLE_GENAI_API_VERSION", "v1beta")

    async def check():
        calls = []

        def transport(request):
            calls.append(True)
            raise httpx.ReadTimeout("test timeout", request=request)

        with patch(
            "livekit.plugins.google.beta.gemini_tts.Client",
            side_effect=client_factory(transport),
        ):
            provider = create_tts(configuration().tts)
            try:
                with pytest.raises(APIConnectionError):
                    async with provider.synthesize(
                        "Test.", conn_options=APIConnectOptions(max_retry=0)
                    ) as stream:
                        async for _ in stream:
                            pass
                assert len(calls) == 1
            finally:
                await provider.aclose()

    asyncio.run(check())


def test_cancellation_reaches_transport_and_cleanup(monkeypatch):
    monkeypatch.setenv("GOOGLE_GENAI_API_VERSION", "v1beta")

    async def check():
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def transport(_request):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        with patch(
            "livekit.plugins.google.beta.gemini_tts.Client",
            side_effect=client_factory(transport),
        ):
            provider = create_tts(configuration().tts)
            stream = provider.synthesize("Test.")
            try:
                await asyncio.wait_for(entered.wait(), timeout=3)
                await asyncio.wait_for(stream.aclose(), timeout=3)
                assert cancelled.is_set()
            finally:
                await stream.aclose()
                await provider.aclose()

    asyncio.run(check())
