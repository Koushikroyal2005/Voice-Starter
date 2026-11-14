"""Small authenticated LiveKit bridge; no vendor or business logic."""

import asyncio
import json
import logging
import time

from livekit import rtc
from livekit.agents import AgentSession, JobContext

from app.agents.orchestrator import Orchestrator
from app.tools.base import ToolFailure

logger = logging.getLogger("voice-starter.workbench")
TOPIC = "voice.workbench.v1"


async def install_workbench(
    ctx: JobContext,
    session: AgentSession,
    language: str,
    orchestrator: Orchestrator | None = None,
) -> None:
    tasks: set[asyncio.Task] = set()
    names: dict[str, str] = {}
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=128)

    async def publish(event: dict) -> None:
        participant = session.room_io.linked_participant
        if participant is None:
            return
        try:
            await ctx.room.local_participant.publish_data(
                json.dumps(event),
                reliable=True,
                topic=TOPIC,
                destination_identities=[participant.identity],
            )
        except Exception:
            logger.warning("Could not deliver workbench event")

    def emit(event: dict) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Workbench event queue full; event not delivered")

    async def sender():
        while True:
            await publish(await queue.get())

    task = asyncio.create_task(sender())
    tasks.add(task)
    task.add_done_callback(tasks.discard)

    def linked_caller(data):
        participant = session.room_io.linked_participant
        if participant is None or data.caller_identity != participant.identity:
            raise rtc.RpcError(2001, "Caller is not the linked session participant")
        return participant.identity

    if orchestrator:
        orchestrator.event_sink = emit

        @ctx.room.local_participant.register_rpc_method("voice.usecase_config")
        async def usecase_config(data: rtc.RpcInvocationData) -> str:
            linked_caller(data)
            return orchestrator.public_use_case.model_dump_json()

        @ctx.room.local_participant.register_rpc_method("voice.confirm_tool")
        async def confirm_tool(data: rtc.RpcInvocationData) -> str:
            actor = linked_caller(data)
            try:
                if len(data.payload) > 512:
                    raise ValueError
                payload = json.loads(data.payload)
                if (
                    not isinstance(payload, dict)
                    or set(payload) != {"confirmation_id", "approved"}
                    or type(payload["approved"]) is not bool
                    or not isinstance(payload["confirmation_id"], str)
                ):
                    raise ValueError
                orchestrator.executor.confirmations.resolve(
                    payload["confirmation_id"], actor, payload["approved"]
                )
                return '{"accepted":true}'
            except (ValueError, KeyError, TypeError, ToolFailure):
                raise rtc.RpcError(
                    2002, "Confirmation is invalid, expired or already answered"
                ) from None

        @ctx.room.local_participant.register_rpc_method("voice.tools_state")
        async def tools_state(data: rtc.RpcInvocationData) -> str:
            linked_caller(data)
            activities = list(orchestrator.activities.values())
            active = [
                a
                for a in activities
                if a["status"] in ("selected", "running", "confirmation_required")
            ]
            recent = [a for a in activities if a not in active][-8:]
            snapshot = []
            for activity in (active + recent)[-16:]:
                candidate = snapshot + [activity]
                if len(json.dumps(candidate, ensure_ascii=False).encode()) <= 14000:
                    snapshot = candidate
            return json.dumps(snapshot, ensure_ascii=False)

        @session.on("user_state_changed")
        def on_user_state(event):
            if event.new_state == "speaking":
                task = asyncio.create_task(orchestrator.executor.cancel_safe())
                tasks.add(task)
                task.add_done_callback(tasks.discard)

        def bind_actor():
            participant = session.room_io.linked_participant
            if participant:
                if orchestrator.state.actor_id is None:
                    orchestrator.state.actor_id = participant.identity
                elif orchestrator.state.actor_id != participant.identity:
                    # Never transfer pending actions/permissions to a replacement user.
                    orchestrator.state.closed = True
                    orchestrator.executor.confirmations.cancel_all()

        bind_actor()

        # RoomIO may select its linked participant after connection.
        @ctx.room.on("participant_connected")
        def on_participant(_participant):
            bind_actor()

    @ctx.room.local_participant.register_rpc_method("voice.interrupt")
    async def interrupt(data: rtc.RpcInvocationData) -> str:
        linked_caller(data)
        started = time.monotonic()
        if orchestrator:
            await orchestrator.executor.cancel_safe()
            if orchestrator.executor.running_writes:
                raise rtc.RpcError(
                    2003,
                    "A non-cancellable action is in progress; check its outcome",
                )
        # SDK cancellation clears queued speech and truncates interrupted history.
        try:
            async with asyncio.timeout(5):
                await session.interrupt(force=True)
        except TimeoutError:
            raise rtc.RpcError(
                2004, "Interruption timed out; reconnect the session"
            ) from None
        if orchestrator and orchestrator.telemetry:
            orchestrator.telemetry.event(
                "interruption_rpc", duration=time.monotonic() - started
            )
        return '{"interrupted":true}'

    @session.on("conversation_item_added")
    def on_item(event):
        if getattr(event.item, "interrupted", False):
            emit({"type": "interrupted"})

    @session.on("tool_execution_updated")
    def on_tool(event):
        update = event.update
        if update.type == "tool_call_started":
            call = update.function_call
            if orchestrator:
                bind_actor()
            try:
                definition = (
                    orchestrator.registry.get(call.name) if orchestrator else None
                )
            except ValueError:
                definition = None
            names[call.call_id] = definition.title if definition else "Agent action"
            emit(
                {
                    "type": "tool",
                    "id": call.call_id,
                    "name": names[call.call_id][:200],
                    "description": definition.description
                    if definition
                    else "An agent action was selected.",
                    "status": "selected" if orchestrator else "running",
                }
            )
        elif update.type == "tool_call_ended":
            if orchestrator and update.call_id in orchestrator.activities:
                names.pop(update.call_id, None)
                return  # Executor outcome overrides SDK transport success.
            emit(
                {
                    "type": "tool",
                    "id": update.call_id,
                    "name": names.pop(update.call_id, "Agent action")[:200],
                    "status": update.status,
                }
            )
        # Never forward raw arguments, tool results or provider exception details.

    async def cleanup() -> None:
        ctx.room.local_participant.unregister_rpc_method("voice.interrupt")
        if orchestrator:
            ctx.room.local_participant.unregister_rpc_method("voice.confirm_tool")
            ctx.room.local_participant.unregister_rpc_method("voice.tools_state")
            ctx.room.local_participant.unregister_rpc_method("voice.usecase_config")
            await orchestrator.executor.close()
            if orchestrator.external_tools:
                await orchestrator.external_tools.aclose()
            if orchestrator.close_infrastructure:
                await orchestrator.close_infrastructure()
        for task in list(tasks):
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    ctx.add_shutdown_callback(cleanup)
    attributes = {"voice.language": language}
    if orchestrator:
        attributes["voice.usecase"] = orchestrator.public_use_case.id
    await ctx.room.local_participant.set_attributes(attributes)
