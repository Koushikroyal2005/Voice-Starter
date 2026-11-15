"""Doctor uses native adapters; all inference/error responses here are mocked."""

import asyncio
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import httpx2 as httpx
import openai
import pytest
from livekit import rtc
from livekit.agents import APIConnectOptions, APIStatusError

from app.config.settings import Settings
from app.providers.doctor import classify_failure, live_report
from tests.test_voice_profiles import environment


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (401, "private audio", "invalid_credentials"),
        (400, "model_terms_required", "model_terms_required"),
        (403, "private input", "access_denied"),
        (429, "private input", "quota_exceeded"),
        (404, "private model", "model_unavailable"),
        (400, "unknown field speechConfig", "unsupported_request_format"),
        (422, "private input", "unsupported_request_format"),
        (500, "private input", "provider_error"),
    ],
)
def test_http_error_classification(status, body, expected):
    error = openai.APIStatusError(
        "private key",
        response=httpx.Response(
            status, request=httpx.Request("POST", "https://example.test")
        ),
        body={"message": body},
    )
    assert classify_failure(error) == expected


def test_native_wrapped_error_classification():
    assert (
        classify_failure(
            APIStatusError("client error", status_code=400, body="model_terms_required")
        )
        == "model_terms_required"
    )
    assert classify_failure(TimeoutError("private")) == "timeout"
    assert classify_failure(ConnectionError("private")) == "network_failure"


def test_actual_cli_offline_never_constructs_providers(capsys):
    from app.cli import main

    with (
        patch(
            "app.config.settings.load_settings",
            return_value=Settings.from_env(environment()),
        ),
        patch(
            "app.providers.doctor.create_tts",
            side_effect=AssertionError("Network forbidden"),
        ),
    ):
        assert main(["providers", "doctor", "--offline"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "offline" and all(
        s["inference"] == "not_tested" for s in report["stages"]
    )


def test_cli_sanitizes_missing_credentials_and_conflicts(capsys):
    from app.cli import main
    from app.config.validation import ConfigurationError

    for message, expected in [
        ("Missing required environment variables: GROQ_API_KEY", "missing_credentials"),
        (
            "VOICE_PROFILE conflicts with environment settings: STT_MODEL",
            "configuration_conflict",
        ),
    ]:
        with patch(
            "app.config.settings.load_settings", side_effect=ConfigurationError(message)
        ):
            assert main(["providers", "doctor"]) == 1
        assert json.loads(capsys.readouterr().out)["failure"] == expected


def test_live_groq_stt_and_llm_use_real_sdk_with_mocked_http():
    from app.providers.factory import create_llm, create_stt

    async def check():
        settings = Settings.from_env(environment())
        speech, model = create_stt(settings.stt), create_llm(settings.llm)
        requests = []

        def transport(request):
            requests.append(request)
            if request.url.path.endswith("/audio/transcriptions"):
                return httpx.Response(200, json={"text": "Private test transcript"})
            payload = {
                "id": "synthetic",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": settings.llm.model,
                "choices": [
                    {"index": 0, "delta": {"content": "Hello."}, "finish_reason": None}
                ],
            }
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content="data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n",
            )

        # Only transports are substituted; native LiveKit streams remain real.
        native_client = openai.AsyncOpenAI(
            api_key="synthetic",
            base_url="https://api.groq.com/openai/v1",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        )
        await speech._client.close()
        await model._client.close()
        speech._client = native_client
        model._client = native_client
        try:
            frame = rtc.AudioFrame(
                data=b"\0\0" * 1600,
                sample_rate=16000,
                num_channels=1,
                samples_per_channel=1600,
            )
            result = await speech.recognize(
                frame, conn_options=APIConnectOptions(max_retry=0)
            )
            assert result.alternatives[0].text == "Private test transcript"
            from livekit.agents import llm

            ctx = llm.ChatContext()
            ctx.add_message(role="user", content="Hello")
            async with model.chat(
                chat_ctx=ctx, conn_options=APIConnectOptions(max_retry=0)
            ) as stream:
                assert [event async for event in stream]
            assert len(requests) == 2
        finally:
            await speech.aclose()
            await model.aclose()
            await native_client.close()

    asyncio.run(check())


class TTS:
    sample_rate = 24000
    num_channels = 1

    def __init__(self):
        self.aclose = AsyncMock()

    def synthesize(self, *args, **kwargs):
        return Stream(
            [
                NS(
                    frame=rtc.AudioFrame(
                        data=b"\1\0" * 2400,
                        sample_rate=24000,
                        num_channels=1,
                        samples_per_channel=2400,
                    )
                )
            ]
        )


class Stream:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def __aiter__(self):
        return self.iterate()

    async def iterate(self):
        for event in self.events:
            yield event


def test_live_report_checks_each_stage_without_printing_transcript_or_keys():
    async def check():
        settings = Settings.from_env(environment())
        tts = TTS()
        speech = NS(
            capabilities=NS(streaming=False),
            recognize=AsyncMock(
                return_value=NS(alternatives=[NS(text="private transcript")])
            ),
            aclose=AsyncMock(),
        )
        model = NS(
            chat=lambda **_: Stream([NS(delta=NS(content="private reply"))]),
            aclose=AsyncMock(),
        )
        with (
            patch("app.providers.doctor.create_tts", return_value=tts),
            patch("app.providers.doctor.create_stt", return_value=speech),
            patch("app.providers.doctor.create_llm", return_value=model),
        ):
            result = await live_report(settings)
        assert result["result"] == "ready_for_browser_testing"
        assert "private" not in json.dumps(result)
        assert "synthetic-groq" not in json.dumps(result)
        for provider in [tts, speech, model]:
            provider.aclose.assert_awaited_once()

    asyncio.run(check())


def test_live_timeout_is_bounded_and_does_not_fake_stt_success():
    async def check():
        class Blocked(TTS):
            def synthesize(self, *args, **kwargs):
                class Waiting(Stream):
                    async def iterate(self):
                        await asyncio.Event().wait()
                        yield None

                return Waiting([])

        tts = Blocked()
        model = NS(chat=lambda **_: Stream([]), aclose=AsyncMock())
        with (
            patch("app.providers.doctor.create_tts", return_value=tts),
            patch("app.providers.doctor.create_llm", return_value=model),
        ):
            result = await live_report(Settings.from_env(environment()), timeout=0.01)
        assert result["result"] == "not_ready"
        stages = {s["stage"]: s for s in result["stages"]}
        assert stages["tts"]["failure"] == "timeout"
        assert stages["stt"]["inference"] == "not_tested_no_audio"
        tts.aclose.assert_awaited_once()

    asyncio.run(check())
