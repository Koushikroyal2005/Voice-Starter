"""A workflow is deterministic backend sequencing, not another LLM/agent."""

from typing import Protocol

from app.tools.base import ExecutionContext, Schema


class Workflow(Protocol):
    async def run(self, args: Schema, context: ExecutionContext) -> Schema: ...
