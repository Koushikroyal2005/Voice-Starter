"""Conversation scaffold only; no patient records, diagnosis or clinical workflows."""

from app.usecases.base import ConversationPolicies, UseCase

USE_CASE = UseCase(
    id="healthcare",
    name="Health Information Demo",
    description="An example module for general health-information conversations.",
    instructions="You are a health-information hackathon demo, not a clinician. "
    "Explain general terms, not diagnoses, treatment plans or medication doses. "
    "Do not request identifiers or patient records. For personal medical concerns, "
    "recommend a qualified professional. "
    "Do not claim this software is clinically validated.",
    provider_defaults={
        "STT_PROVIDER": "deepgram",
        "LLM_PROVIDER": "openai_compatible",
        "TTS_PROVIDER": "cartesia",
    },
    allowed_providers={
        "stt": ("deepgram", "assemblyai"),
        "llm": ("openai_compatible", "gemini"),
        "tts": ("cartesia", "elevenlabs", "murf"),
    },
    allowed_tools=("get_current_time", "calculate_expression", "time_and_calculate"),
    policies=ConversationPolicies(
        allow_transcript_storage=False, allow_side_effects=False
    ),
    notice="Example only. Not clinical care, a medical device, "
    "or a compliance guarantee.",
)
