"""One-use approvals bound to a linked human, exact request and operation."""

import asyncio
import secrets
from collections.abc import Callable
from dataclasses import dataclass

from app.tools.base import ToolFailure


@dataclass
class PendingConfirmation:
    actor_id: str
    digest: str
    future: asyncio.Future[bool]


class ConfirmationManager:
    def __init__(self, emit: Callable[[dict], None], timeout: float = 45):
        self.pending: dict[str, PendingConfirmation] = {}
        self.emit = emit
        self.timeout = timeout

    async def request(
        self, actor_id: str, digest: str, call_id: str, title: str, summary: str
    ) -> bool:
        token = secrets.token_urlsafe(24)
        future = asyncio.get_running_loop().create_future()
        self.pending[token] = PendingConfirmation(actor_id, digest, future)
        self.emit(
            {
                "type": "tool",
                "id": call_id,
                "name": title,
                "description": summary[:500],
                "status": "confirmation_required",
                "confirmation_id": token,
            }
        )
        try:
            async with asyncio.timeout(self.timeout):
                return await future
        except TimeoutError:
            raise ToolFailure(
                "confirmation_expired", "Confirmation expired. No action was taken."
            ) from None
        finally:
            self.pending.pop(token, None)

    def resolve(self, token: str, actor_id: str, approved: bool) -> None:
        pending = self.pending.get(token)
        if not pending or pending.actor_id != actor_id or pending.future.done():
            raise ToolFailure(
                "confirmation_invalid", "Confirmation is no longer available."
            )
        pending.future.set_result(approved)

    def cancel_all(self) -> None:
        for pending in list(self.pending.values()):
            pending.future.cancel()
