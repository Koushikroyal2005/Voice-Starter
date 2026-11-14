"""Vendor-independent composition using LiveKit's native session and adapters."""

from livekit.agents import (
    AgentSession,
    APIConnectOptions,
    SessionConnectOptions,
    TurnHandlingOptions,
    llm,
    stt,
    tts,
)
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
    language_model = create_llm(settings.llm)
    synthesis = create_tts(settings.tts)
    options = settings.observability
    # Native adapters retain streaming/cancellation and partial-output guards.
    for fallback in settings.fallbacks:
        if fallback.category == "stt":
            backup = create_stt(fallback)
            if not backup.capabilities.streaming or (
                settings.require_interim and not backup.capabilities.interim_results
            ):
                raise ProviderError("Fallback STT capabilities are incompatible")
            speech = stt.FallbackAdapter(
                [speech, backup],
                max_retry_per_stt=0,
                attempt_timeout=options.provider_timeout,
            )
        elif fallback.category == "llm":
            language_model = llm.FallbackAdapter(
                [language_model, create_llm(fallback)],
                max_retry_per_llm=0,
                attempt_timeout=options.provider_timeout,
                retry_on_chunk_sent=False,
                sticky=True,
            )
        else:
            synthesis = tts.FallbackAdapter(
                [synthesis, create_tts(fallback)], max_retry_per_tts=0
            )

    def connection(category):
        return APIConnectOptions(
            max_retry=0
            if any(f.category == category for f in settings.fallbacks)
            else options.provider_retries,
            timeout=options.provider_timeout,
            retry_interval=0.5,
        )

    return AgentSession(
        stt=speech,
        llm=language_model,
        tts=synthesis,
        conn_options=SessionConnectOptions(
            stt_conn_options=connection("stt"),
            llm_conn_options=connection("llm"),
            tts_conn_options=connection("tts"),
            max_unrecoverable_errors=2,
        ),
        vad=vad,
        turn_handling=TurnHandlingOptions(
            turn_detection=settings.turn_detection,
            interruption={"mode": "vad"},
            endpointing={"min_delay": 0 if settings.turn_detection == "stt" else 0.5},
        ),
    )
