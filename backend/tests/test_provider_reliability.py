"""Native LiveKit stream/fallback tests against deterministic test-only providers."""

import asyncio

import pytest
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APITimeoutError,
    llm,
    tts,
)

CONNECT_OPTIONS = APIConnectOptions()


class MockLLM(llm.LLM):
    def __init__(self, failure=None, partial=False):
        super().__init__()
        self.failure, self.partial, self.attempts = failure, partial, 0

    def chat(self, *, chat_ctx, tools=None, conn_options=CONNECT_OPTIONS, **_kwargs):
        return MockLLMStream(
            self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options
        )


class MockLLMStream(llm.LLMStream):
    async def _run(self):
        self._llm.attempts += 1
        if self._llm.partial:
            self._event_ch.send_nowait(
                llm.ChatChunk(id="mock", delta=llm.ChoiceDelta(content="Partial"))
            )
            await asyncio.sleep(0.01)
        if self._llm.failure == "timeout":
            try:
                async with asyncio.timeout(0.001):
                    await asyncio.sleep(1)
            except TimeoutError:
                raise APITimeoutError("Mock model timeout") from None
        if self._llm.failure:
            raise APIConnectionError("Mock failure")
        self._event_ch.send_nowait(
            llm.ChatChunk(id="mock", delta=llm.ChoiceDelta(content="OK"))
        )


class MockTTS(tts.TTS):
    def __init__(self):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=16000,
            num_channels=1,
        )
        self.attempts = 0

    def synthesize(self, text, *, conn_options=CONNECT_OPTIONS):
        return MockTTSStream(tts=self, input_text=text, conn_options=conn_options)


class MockTTSStream(tts.ChunkedStream):
    async def _run(self, output_emitter):
        self._tts.attempts += 1
        raise APIConnectionError("Mock TTS failure")


def test_model_timeout_has_bounded_native_retries():
    async def check():
        model = MockLLM("timeout")
        errors = []
        model.on("error", errors.append)
        async with model.chat(
            chat_ctx=llm.ChatContext(),
            conn_options=APIConnectOptions(max_retry=1, retry_interval=0, timeout=0.01),
        ) as stream:
            with pytest.raises(APIConnectionError):
                async for _ in stream:
                    pass
        assert model.attempts == 2 and errors
        await model.aclose()

    asyncio.run(check())


def test_native_fallback_and_no_replay_after_partial_output():
    async def check(partial):
        primary, backup = MockLLM("unavailable", partial), MockLLM()
        adapter = llm.FallbackAdapter(
            [primary, backup],
            max_retry_per_llm=0,
            attempt_timeout=0.1,
            retry_on_chunk_sent=False,
            sticky=True,
        )
        try:
            async with adapter.chat(
                chat_ctx=llm.ChatContext(), conn_options=APIConnectOptions(max_retry=0)
            ) as stream:
                if partial:
                    with pytest.raises(APIConnectionError):
                        async for _ in stream:
                            pass
                else:
                    chunks = [chunk async for chunk in stream]
                    assert chunks[-1].delta.content == "OK"
            assert backup.attempts == (0 if partial else 1)
        finally:
            await adapter.aclose()

    asyncio.run(check(False))
    asyncio.run(check(True))


def test_tts_failure_is_bounded_and_emits_native_error():
    async def check():
        provider, errors = MockTTS(), []
        provider.on("error", errors.append)
        async with provider.synthesize(
            "test", conn_options=APIConnectOptions(max_retry=1, retry_interval=0)
        ) as stream:
            with pytest.raises(APIConnectionError):
                async for _ in stream:
                    pass
        assert provider.attempts == 2 and errors[-1].recoverable is False
        await provider.aclose()

    asyncio.run(check())
