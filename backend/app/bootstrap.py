"""Application composition root: add reviewed use-case tools here, not in the engine."""

from app.agents.orchestrator import Orchestrator
from app.config.settings import Settings


def build_orchestrator(settings: Settings) -> Orchestrator:
    return Orchestrator(settings, additional_tools=())
