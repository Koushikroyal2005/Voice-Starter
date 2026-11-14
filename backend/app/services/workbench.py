"""Small authenticated LiveKit bridge; no vendor or business logic."""

import asyncio
import json
import logging

from livekit import rtc
from livekit.agents import AgentSession, JobContext

logger = logging.getLogger("voice-starter.workbench")
TOPIC = "voice.workbench.v1"


async def install_workbench(
    ctx: JobContext, session: AgentSession, language: str
) -> None:
    tasks: set[asyncio.Task] = set()
    names: dict[str, str] = {}

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
        task = asyncio.create_task(publish(event))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    @ctx.room.local_participant.register_rpc_method("voice.interrupt")
    async def interrupt(data: rtc.RpcInvocationData) -> str:
        participant = session.room_io.linked_participant
        if participant is None or data.caller_identity != participant.identity:
            raise rtc.RpcError(1403, "Caller is not the linked session participant")
        # SDK cancellation clears queued speech and truncates interrupted history.
        await session.interrupt(force=True)
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
            names[call.call_id] = call.name
            emit(
                {
                    "type": "tool",
                    "id": call.call_id,
                    "name": call.name[:200],
                    "status": "running",
                }
            )
        elif update.type == "tool_call_ended":
            emit(
                {
                    "type": "tool",
                    "id": update.call_id,
                    "name": names.pop(update.call_id, "Tool")[:200],
                    "status": update.status,
                }
            )
        # Never forward raw arguments, tool results or provider exception details.

    async def cleanup() -> None:
        ctx.room.local_participant.unregister_rpc_method("voice.interrupt")
        for task in list(tasks):
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    ctx.add_shutdown_callback(cleanup)
    await ctx.room.local_participant.set_attributes({"voice.language": language})
