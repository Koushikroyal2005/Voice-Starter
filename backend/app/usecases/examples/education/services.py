"""Deterministic demo planning rules, with no model/provider/database dependency."""

from pydantic import Field

from app.tools.base import Schema


class StudyPlanInput(Schema):
    topic: str = Field(min_length=1, max_length=80, pattern=r".*\S.*")
    days: int = Field(ge=1, le=7)
    minutes_per_day: int = Field(default=30, ge=10, le=120)


class StudySession(Schema):
    day: int = Field(ge=1, le=7)
    focus: str = Field(max_length=100)
    minutes: int = Field(ge=10, le=120)


class StudyPlan(Schema):
    topic: str = Field(max_length=80)
    total_minutes: int = Field(ge=10, le=840)
    sessions: list[StudySession] = Field(min_length=1, max_length=7)


class StudyPlanService:
    def create(self, request: StudyPlanInput) -> StudyPlan:
        phases = (
            "Review the basics",
            "Practice worked examples",
            "Recall and self-check",
        )
        return StudyPlan(
            topic=request.topic.strip(),
            total_minutes=request.days * request.minutes_per_day,
            sessions=[
                StudySession(
                    day=day,
                    focus=phases[(day - 1) % len(phases)],
                    minutes=request.minutes_per_day,
                )
                for day in range(1, request.days + 1)
            ],
        )
