"""Minimal single-agent demo behavior."""

from livekit.agents import Agent

from app.config.settings import Settings


class DemoAgent(Agent):
    def __init__(self, settings: Settings) -> None:
        super().__init__(instructions=settings.instructions)
