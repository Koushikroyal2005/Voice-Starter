"""Educational scaffold, not an advisor, transaction processor or financial product."""

from app.usecases.base import ConversationPolicies, UseCase

USE_CASE = UseCase(
    id="finance",
    name="Money Concepts Demo",
    description="An example assistant for explaining basic financial concepts.",
    instructions="You explain general financial concepts for a hackathon demo. "
    "Do not offer personalized investment, tax, legal or lending advice. "
    "Use the calculator for arithmetic. Do not claim access to market prices "
    "or accounts. Never ask for account credentials or execute transactions.",
    provider_defaults={
        "STT_PROVIDER": "deepgram",
        "LLM_PROVIDER": "openai_compatible",
        "TTS_PROVIDER": "cartesia",
    },
    allowed_tools=("get_current_time", "calculate_expression", "time_and_calculate"),
    policies=ConversationPolicies(
        allow_transcript_storage=False, allow_side_effects=False
    ),
    notice="Educational example only. Not personalized financial advice "
    "or a regulated product.",
)
