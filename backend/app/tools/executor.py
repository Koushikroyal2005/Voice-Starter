"""Deterministic policy/execution boundary behind LiveKit's native tool loop."""

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable

from pydantic import ValidationError

from app.agents.conversation import ConversationState
from app.agents.state_manager import Operation, StateManager
from app.tools.base import ExecutionContext, ToolDefinition, ToolFailure, ToolResult
from app.tools.confirmation import ConfirmationManager
from app.tools.permissions import require_permission
from app.tools.registry import ToolRegistry

logger = logging.getLogger("voice-starter.tools")


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        state: ConversationState,
        allowlist: frozenset[str],
        emit: Callable[[dict], None],
    ):
        self.registry, self.state, self.allowlist, self.emit = (
            registry,
            state,
            allowlist,
            emit,
        )
        self.ledger = StateManager()
        self.confirmations = ConfirmationManager(emit)
        self.running_writes: set[str] = set()
        self.rate_limit_check = None

    def event(
        self,
        call_id: str,
        tool: ToolDefinition,
        status: str,
        description: str | None = None,
    ):
        self.emit(
            {
                "type": "tool",
                "id": call_id,
                "name": tool.title,
                "description": description or tool.description,
                "status": status,
            }
        )

    async def execute(
        self,
        name: str,
        arguments: dict,
        *,
        call_id: str,
        idempotency_key: str | None = None,
        ancestors: tuple[str, ...] = (),
    ) -> ToolResult:
        try:
            tool = self.registry.get(name)
        except ValueError:
            return ToolResult(
                call_id=call_id,
                tool=name,
                status="denied",
                code="unsupported_tool",
                message="This action is not available.",
            )
        self.event(call_id, tool, "selected")
        try:
            require_permission(self.state, self.allowlist, tool)
            if len(ancestors) >= 4 or name in ancestors:
                raise ToolFailure(
                    "workflow_recursion", "Workflow recursion is not allowed."
                )
            args = tool.input_schema.model_validate(arguments)
            if tool.side_effects and (
                not isinstance(idempotency_key, str)
                or not idempotency_key.strip()
                or len(idempotency_key) > 128
            ):
                raise ToolFailure(
                    "idempotency_required",
                    "This action requires a stable idempotency key.",
                )
            digest = hashlib.sha256(
                json.dumps(
                    args.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            key = f"{self.state.conversation_id}:{self.state.actor_id}:"
            key += f"{name}:{idempotency_key or call_id}"
            operation = self.ledger.operations.get(key)
            if operation and operation.digest != digest:
                raise ToolFailure(
                    "idempotency_conflict",
                    "The operation key was already used with different arguments.",
                )
            if operation is None:
                active = sum(
                    not op.task.done() for op in self.ledger.operations.values()
                )
                if active >= 8:
                    raise ToolFailure(
                        "too_many_actions", "Wait for current actions to finish."
                    )
                self.ledger.ensure_capacity()
                task = asyncio.create_task(
                    self._run(
                        tool, args, call_id, key, digest, idempotency_key, ancestors
                    )
                )
                operation = Operation(digest, task, tool.cancellation_safe)
                self.ledger.operations[key] = operation
            # A duplicate waiter must never cancel the shared operation by itself.
            async with asyncio.timeout(
                tool.timeout_seconds + self.confirmations.timeout
            ):
                result = await asyncio.shield(operation.task)
            if result.call_id != call_id:
                self.event(
                    call_id,
                    tool,
                    "completed" if result.status == "completed" else "failed",
                    "Existing operation result; no duplicate execution.",
                )
            return result.model_copy(update={"call_id": call_id})
        except asyncio.CancelledError:
            if (
                "operation" in locals()
                and operation
                and (operation.cancellation_safe or key not in self.running_writes)
            ):
                operation.task.cancel()
                await asyncio.gather(operation.task, return_exceptions=True)
            self.event(
                call_id,
                tool,
                "cancelled"
                if tool.cancellation_safe
                or "key" not in locals()
                or key not in self.running_writes
                else "unknown",
            )
            raise
        except ValidationError as error:
            fields = ", ".join(
                str(e["loc"][0]) for e in error.errors(include_input=False) if e["loc"]
            )
            return self._failure(
                tool,
                call_id,
                "invalid_arguments",
                f"Check the tool input fields: {fields[:200] or 'input'}.",
            )
        except ToolFailure as error:
            return self._failure(tool, call_id, error.code, error.message, "denied")
        except TimeoutError:
            return self._failure(
                tool,
                call_id,
                "operation_pending",
                "The action is still running or its outcome is unknown. "
                "Do not retry with a new key.",
                "unknown",
            )
        except ValueError:
            return self._failure(
                tool, call_id, "operation_limit", "Session operation limit reached."
            )

    def _failure(self, tool, call_id, code, message, status="failed"):
        self.event(
            call_id, tool, "unknown" if status == "unknown" else "failed", message
        )
        return ToolResult(
            call_id=call_id, tool=tool.name, status=status, code=code, message=message
        )

    async def _run(self, tool, args, call_id, key, digest, idempotency_key, ancestors):
        try:
            if self.rate_limit_check:
                await self.rate_limit_check()
            if tool.sensitive:
                approved = await self.confirmations.request(
                    self.state.actor_id,
                    digest,
                    call_id,
                    tool.title,
                    tool.confirmation_summary(args),
                )
                if not approved:
                    raise ToolFailure(
                        "confirmation_denied",
                        "The action was declined. Nothing was changed.",
                    )
            # Re-check after a human wait; registry and authorization may have changed.
            require_permission(self.state, self.allowlist, tool)
            if self.registry.get(tool.name) is not tool:
                raise ToolFailure(
                    "tool_changed",
                    "This action changed while waiting; request it again.",
                )

            async def run_child(name, arguments, **kwargs):
                return await self.execute(
                    name, arguments, ancestors=(*ancestors, tool.name), **kwargs
                )

            context = ExecutionContext(
                self.state.conversation_id,
                self.state.actor_id,
                call_id,
                idempotency_key,
                run_child,
            )
            self.event(call_id, tool, "running")
            if not tool.cancellation_safe:
                self.running_writes.add(key)
            async with asyncio.timeout(tool.timeout_seconds):
                output = tool.output_schema.model_validate(
                    await tool.handler(args, context)
                )
            data = output.model_dump(mode="json")
            self.event(call_id, tool, "completed")
            if tool.public_result:
                self.emit(
                    {
                        "type": "result",
                        "id": call_id,
                        "title": tool.title,
                        "text": tool.public_result(output)[:4000],
                    }
                )
            return ToolResult(
                call_id=call_id,
                tool=tool.name,
                status="completed",
                message="Action completed.",
                data=data,
            )
        except asyncio.CancelledError:
            self.event(
                call_id,
                tool,
                "cancelled"
                if tool.cancellation_safe or key not in self.running_writes
                else "unknown",
            )
            raise
        except TimeoutError:
            status = "unknown" if tool.side_effects else "timeout"
            return self._failure(
                tool,
                call_id,
                "timeout",
                "Action timed out. Check its external outcome before retrying."
                if tool.side_effects
                else "Action timed out.",
                status,
            )
        except ToolFailure as error:
            return self._failure(
                tool,
                call_id,
                error.code,
                error.message,
                "unknown" if tool.side_effects and error.outcome_unknown else "failed",
            )
        except Exception:
            # Avoid arguments, output, credentials and raw exception details.
            logger.warning(
                "Tool operation failed", extra={"tool": tool.name, "call_id": call_id}
            )
            return self._failure(
                tool,
                call_id,
                "operation_failed",
                "The action failed. No automatic retry was attempted.",
                "unknown"
                if tool.side_effects and key in self.running_writes
                else "failed",
            )
        finally:
            self.running_writes.discard(key)

    async def cancel_safe(self):
        self.confirmations.cancel_all()
        tasks = [
            op.task
            for key, op in self.ledger.operations.items()
            if not op.task.done()
            and (op.cancellation_safe or key not in self.running_writes)
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self):
        self.state.closed = True
        await self.cancel_safe()
        # Do not cancel writes on a transport disconnect. Wait only for their bounded
        # operation deadline. External adapters must enforce their own request timeout.
        writes = [
            op.task for op in self.ledger.operations.values() if not op.task.done()
        ]
        if writes:
            await asyncio.gather(*writes, return_exceptions=True)
