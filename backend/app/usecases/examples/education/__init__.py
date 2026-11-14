from app.usecases.base import ConversationPolicies, UseCase
from app.usecases.examples.education.tools import build_tools

USE_CASE = UseCase(
    id="education",
    name="Study Companion",
    description="Try a suggested study routine, built by a deterministic demo tool.",
    instructions="You are Study Companion, an education hackathon demo. Explain "
    "concepts in plain English. When asked for a study plan, ask for the topic "
    "and number of days, then use create_study_plan. Make clear the routine is "
    "a suggestion, not a validated curriculum or a guarantee of learning. "
    "Do not request student identifiers, grades or private school records.",
    provider_defaults={
        "STT_PROVIDER": "deepgram",
        "LLM_PROVIDER": "openai_compatible",
        "TTS_PROVIDER": "cartesia",
    },
    default_tools=(
        "get_current_time",
        "calculate_expression",
        "time_and_calculate",
        "create_study_plan",
    ),
    allowed_tools=(
        "get_current_time",
        "calculate_expression",
        "time_and_calculate",
        "create_study_plan",
    ),
    tool_factory=build_tools,
    service_names=("StudyPlanService",),
    result_card_types=("text", "study_plan"),
    policies=ConversationPolicies(allow_side_effects=False),
    notice="Education demo only. No student records, calendar writes "
    "or validated curriculum.",
)
