"""Explicit reviewed imports only. USE_CASE never becomes an import path."""

from app.usecases.base import UseCase
from app.usecases.examples.education import USE_CASE as EDUCATION
from app.usecases.examples.finance import USE_CASE as FINANCE
from app.usecases.examples.general_assistant import USE_CASE as GENERAL
from app.usecases.examples.healthcare import USE_CASE as HEALTHCARE
from app.usecases.examples.small_business import USE_CASE as BUSINESS


class UseCaseRegistry:
    def __init__(self):
        self.entries: dict[str, UseCase] = {}

    def register(self, use_case: UseCase):
        if use_case.id in self.entries:
            raise ValueError("Use case is already registered")
        self.entries[use_case.id] = use_case

    def get(self, name="general_assistant"):
        try:
            return self.entries[name or "general_assistant"]
        except KeyError:
            raise ValueError(
                "Unsupported USE_CASE; supported: " + ", ".join(sorted(self.entries))
            ) from None


registry = UseCaseRegistry()
for use_case in (GENERAL, EDUCATION, HEALTHCARE, FINANCE, BUSINESS):
    registry.register(use_case)
