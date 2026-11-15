"""Regression: registration must precede the Windows SDK job threads."""

import subprocess
import sys
from unittest.mock import patch

from app.config.settings import ProviderConfig
from app.providers.factory import preload_provider_plugins
from app.providers.registry import registry


def test_preloads_registered_native_plugins_without_constructing_providers():
    configs = [
        ProviderConfig(p.category, p.name, p.model, "synthetic", voice=p.voice)
        for category in ("stt", "llm", "tts")
        for p in registry.list(category)
    ]
    with patch("app.providers.factory.import_module") as load:
        preload_provider_plugins(configs)
        modules = [c.args[0] for c in load.call_args_list]
    assert set(modules) == {
        "livekit.plugins.openai",
        "livekit.plugins.google",
        "livekit.plugins.deepgram",
        "livekit.plugins.assemblyai",
        "livekit.plugins.cartesia",
        "livekit.plugins.elevenlabs",
        "livekit.plugins.murf",
        "app.providers.tts.nvidia",
    }
    assert len(modules) == len(set(modules))


def test_server_preloads_before_accepting_jobs(monkeypatch):
    from app import main
    from tests.test_groq_voice import configuration

    settings = configuration()
    order = []
    monkeypatch.setattr(main, "load_settings", lambda: settings)
    monkeypatch.setattr(main.sys, "argv", ["main", "dev"])
    with patch.object(main, "preload_provider_plugins") as preload:
        preload.side_effect = lambda configs: order.append(("plugins", configs))
        with patch.object(main, "AgentServer") as server:
            server.side_effect = lambda **kwargs: (
                order.append(("server", kwargs)) or server.return_value
            )
            main.create_server()
    assert [name for name, _ in order] == ["plugins", "server"]
    assert order[0][1] == (
        settings.stt,
        settings.llm,
        settings.tts,
        *settings.fallbacks,
    )


def test_fresh_interpreter_can_construct_pipeline_in_job_thread():
    code = """
import asyncio
from concurrent.futures import ThreadPoolExecutor
from app.config.settings import Settings
from app.providers.factory import preload_provider_plugins
from app.providers.pipeline import create_session
s = Settings.from_env({
    "LIVEKIT_URL": "ws://localhost:7880", "LIVEKIT_API_KEY": "synthetic",
    "LIVEKIT_API_SECRET": "synthetic", "GROQ_API_KEY": "synthetic",
    "LLM_API_KEY": "synthetic", "GOOGLE_API_KEY": "synthetic",
    "STT_PROVIDER": "groq", "STT_ALLOW_BATCH": "true", "TTS_PROVIDER": "gemini",
})
preload_provider_plugins((s.stt, s.llm, s.tts))
async def construct():
    session = create_session(s)
    await session.aclose()
    await session.stt.wrapped_stt.aclose()
    await session.stt.aclose()
    await session.llm.aclose()
    await session.tts.aclose()
with ThreadPoolExecutor(max_workers=1) as executor:
    executor.submit(lambda: asyncio.run(construct())).result()
print("thread construction passed")
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=45
    )
    assert result.returncode == 0, result.stderr
    assert "thread construction passed" in result.stdout
