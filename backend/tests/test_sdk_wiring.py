"""Offline checks against real installed SDK classes; no provider requests."""

import asyncio
import pickle

from livekit.agents import AgentSession
from livekit.agents.stt import StreamAdapter

from app.agents.demo import DemoAgent
from app.config.settings import Settings
from app.main import voice_session
from app.providers.pipeline import create_session
from app.providers.registry import registry


def test_real_pipeline_constructs_locally():
    settings = Settings.from_env(
        {
            "LIVEKIT_URL": "wss://example.livekit.cloud",
            "LIVEKIT_API_KEY": "test-key",
            "LIVEKIT_API_SECRET": "test-secret",
            "DEEPGRAM_API_KEY": "test-deepgram",
            "OPENAI_API_KEY": "test-openai",
            "CARTESIA_API_KEY": "test-cartesia",
        }
    )

    async def check():
        session = create_session(settings)
        try:
            assert isinstance(session, AgentSession)
            assert DemoAgent(settings).instructions == settings.instructions
        finally:
            await session.aclose()
            await session.stt.aclose()
            await session.llm.aclose()
            await session.tts.aclose()

    asyncio.run(check())


def test_worker_callback_can_be_pickled_for_windows_spawn():
    assert pickle.loads(pickle.dumps(voice_session)) is voice_session


def test_batch_whisper_uses_sdk_adapter_without_claiming_native_streaming():
    settings = Settings.from_env(
        {
            "LIVEKIT_URL": "wss://example.livekit.cloud",
            "LIVEKIT_API_KEY": "test",
            "LIVEKIT_API_SECRET": "test",
            "STT_PROVIDER": "whisper",
            "OPENAI_API_KEY": "test",
            "CARTESIA_API_KEY": "test",
            "STT_ALLOW_BATCH": "true",
        }
    )

    async def check():
        session = create_session(settings)
        try:
            assert isinstance(session.stt, StreamAdapter)
            assert session.stt.capabilities.streaming is True
            assert session.stt.capabilities.interim_results is False
            assert session.stt.wrapped_stt.capabilities.streaming is False
            assert registry.get("stt", "whisper").capabilities.streaming is False
        finally:
            await session.aclose()
            await session.stt.wrapped_stt.aclose()
            await session.stt.aclose()
            await session.llm.aclose()
            await session.tts.aclose()

    asyncio.run(check())
