"""Compatibility import: there is only one main agent implementation."""

from app.agents.orchestrator import MainAgent as DemoAgent

__all__ = ["DemoAgent"]
