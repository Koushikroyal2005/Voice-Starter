"""Explicit public disclosure, not automatic serialization of arbitrary tool results."""

from app.tools.base import PublicCard, ToolDefinition
from app.usecases.examples.education.services import (
    StudyPlan,
    StudyPlanInput,
    StudyPlanService,
)


def build_tools():
    service = StudyPlanService()  # One per composed agent; no global service container.

    async def create_plan(request: StudyPlanInput, _context):
        return service.create(request)

    return (
        ToolDefinition(
            name="create_study_plan",
            title="Create a study plan",
            description="Build a suggested 1–7 day study routine for a topic. "
            "This does not schedule events or save a student record.",
            input_schema=StudyPlanInput,
            output_schema=StudyPlan,
            handler=create_plan,
            confirmation_summary=lambda request: (
                f"Build a {request.days}-day suggested study "
                f"routine with {request.minutes_per_day} minutes per day? "
                "No records will be saved."
            ),
            public_result=lambda plan: (
                f"{len(plan.sessions)} sessions, {plan.total_minutes} minutes total."
            ),
            public_card=lambda plan: PublicCard(
                card_type="study_plan", data=plan.model_dump(mode="json")
            ),
        ),
    )
