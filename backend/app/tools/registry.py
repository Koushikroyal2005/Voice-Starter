"""Explicit server-owned registration; no dynamic imports or model-selected code."""

import re

from app.tools.base import ToolDefinition


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", tool.name):
            raise ValueError("Invalid tool name")
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def remove(self, name: str) -> None:
        del self._tools[name]

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError:
            raise ValueError(f"Tool is not registered: {name}") from None

    def selected(self, allowlist: frozenset[str]) -> list[ToolDefinition]:
        return [self.get(name) for name in sorted(allowlist)]
