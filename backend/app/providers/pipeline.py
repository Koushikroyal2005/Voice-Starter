"""Vendor-independent composition using LiveKit's native session and adapters."""

from livekit.agents import AgentSession, TurnHandlingOptions
from livekit.agents.stt import StreamAdapter
from livekit.plugins import silero

from app.config.settings import Settings
from app.providers.factory import create_llm, create_stt, create_tts
from app.providers.registry import ProviderError


def create_session(settings: Settings) -> AgentSession:
    vad = silero.VAD.load(activation_threshold=0.3)
    speech = create_stt(settings.stt)
    if settings.require_interim and not speech.capabilities.interim_results:
        raise ProviderError("Installed STT plugin does not support interim results")
    if not speech.capabilities.streaming:
        if not settings.allow_batch_stt:
            raise ProviderError("Batch STT requires STT_ALLOW_BATCH=true")
        # This segments utterances; it does NOT make Whisper natively streaming.
        speech = StreamAdapter(stt=speech, vad=vad)
    return AgentSession(
        stt=speech,
        llm=create_llm(settings.llm),
        tts=create_tts(settings.tts),
        vad=vad,
        turn_handling=TurnHandlingOptions(
            turn_detection=settings.turn_detection,
            interruption={"mode": "vad"},
            endpointing={"min_delay": 0 if settings.turn_detection == "stt" else 0.5},
        ),
    )
