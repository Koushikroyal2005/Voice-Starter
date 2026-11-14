"""Scaffold without orders, bookings, customer records or external integrations."""

from app.usecases.base import ConversationPolicies, UseCase

USE_CASE = UseCase(
    id="small_business",
    name="Business Ideas Demo",
    description="A scaffold for discussing small-business ideas and simple arithmetic.",
    instructions="You are a small-business hackathon demo. Help brainstorm checklists "
    "and explain arithmetic. Never claim a booking, order, payment, customer lookup "
    "or inventory update occurred: no such integrations exist in this module. "
    "Do not request payment credentials or personal customer records.",
    provider_defaults={
        "STT_PROVIDER": "deepgram",
        "LLM_PROVIDER": "openai_compatible",
        "TTS_PROVIDER": "cartesia",
    },
    allowed_tools=("get_current_time", "calculate_expression", "time_and_calculate"),
    policies=ConversationPolicies(allow_side_effects=False),
    notice="Example scaffold only. No live orders, payments, bookings "
    "or customer data.",
)
