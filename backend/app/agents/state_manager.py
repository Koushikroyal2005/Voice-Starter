"""Bounded per-session idempotency ledger. Not a durable exactly-once store."""

import asyncio
from dataclasses import dataclass

from app.tools.base import ToolResult


@dataclass
class Operation:
    digest: str
    task: asyncio.Task[ToolResult]
    cancellation_safe: bool
    call_id: str = ""


class StateManager:
    def __init__(self, limit: int = 256):
        self.operations: dict[str, Operation] = {}
        self.limit = limit

    def ensure_capacity(self):
        # Never evict a write's deduplication key just to make room for another.
        if len(self.operations) >= self.limit:
            raise ValueError("Session operation limit reached; start a new session")
