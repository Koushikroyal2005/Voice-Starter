"""Real provider plugins for the initial cascaded pipeline."""

from livekit.agents import AgentSession, TurnHandlingOptions
from livekit.plugins import cartesia, deepgram, openai, silero

from app.config.settings import Settings


def create_session(settings: Settings) -> AgentSession:
    return AgentSession(
        stt=deepgram.STT(
            api_key=settings.deepgram_api_key,
            model=settings.stt_model,
            language=settings.stt_language,
        ),
        # Chat Completions supports OpenAI-compatible endpoints via base_url.
        llm=openai.LLM(
            api_key=settings.openai_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
        ),
        tts=cartesia.TTS(
            api_key=settings.cartesia_api_key,
            model=settings.tts_model,
            voice=settings.tts_voice,
        ),
        vad=silero.VAD.load(),
        turn_handling=TurnHandlingOptions(
            turn_detection="vad", interruption={"mode": "vad"}
        ),
    )
