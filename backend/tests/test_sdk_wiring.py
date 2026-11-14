"""Offline checks against real installed SDK classes; no provider requests."""

import asyncio
import pickle

from livekit.agents import AgentSession

from app.agents.demo import DemoAgent
from app.config.settings import Settings
from app.main import voice_session
from app.providers.pipeline import create_session


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
