"""Measure public SDK events. Never infer a missing metric or guess a late turn ID."""

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from uuid import uuid4

from livekit.agents.telemetry import set_tracer_provider

from app.observability.config import ObservabilitySettings
from app.observability.logging import correlation
from app.observability.runtime import Telemetry


@dataclass
class Turn:
    id: str
    started: float
    ended: float | None = None
    committed: bool = False
    interim: bool = False
    final: bool = False


class SessionObserver:
    def __init__(
        self,
        session,
        orchestrator,
        telemetry,
        *,
        clock=time.time,
        monotonic=time.monotonic,
    ):
        self.session, self.orchestrator, self.telemetry = (
            session,
            orchestrator,
            telemetry,
        )
        self.clock, self.monotonic = clock, monotonic
        self.turns = OrderedDict()
        self.current = None
        self.seen = OrderedDict()
        self.tools = OrderedDict()
        self.agent_speaking = False
        self.interruption_started = None
        self.closed = False
        self.bind()

    def emit(self, stage, turn=None, **kwargs):
        self.telemetry.event(stage, turn_id=turn.id if turn else None, **kwargs)

    def bind(self):
        @self.session.on("user_state_changed")
        def on_user(event):
            now = event.created_at
            if event.new_state == "speaking":
                if self.current is None or self.current.committed:
                    self.current = Turn(str(uuid4()), now)
                    self.turns[self.current.id] = self.current
                    while len(self.turns) > 64:
                        self.turns.popitem(last=False)
                    self.emit("user_speech_start", self.current)
                if self.agent_speaking:
                    self.interruption_started = (now, self.current)
            elif event.old_state == "speaking" and self.current:
                self.current.ended = now

        @self.session.on("user_input_transcribed")
        def on_transcript(event):
            turn = self.current
            if turn is None or turn.committed or not event.transcript.strip():
                return
            if event.is_final and not turn.final:
                turn.final = True
                self.emit(
                    "stt_final_from_speech_start",
                    turn,
                    duration=event.created_at - turn.started,
                )
            elif not event.is_final and not turn.interim:
                turn.interim = True
                self.emit("stt_interim", turn, duration=event.created_at - turn.started)

        @self.session.on("conversation_item_added")
        def on_item(event):
            item = event.item
            if item.id in self.seen:
                return
            self.seen[item.id] = True
            while len(self.seen) > 128:
                self.seen.popitem(last=False)
            metrics = item.metrics
            turn = None
            if item.role == "user":
                turn = self.current
                if turn and not turn.committed:
                    turn.committed = True
                    turn.ended = metrics.get("stopped_speaking_at", turn.ended)
                else:
                    # Text-only input has no VAD start. Do not fabricate audio latency.
                    turn = Turn(str(uuid4()), item.created_at, committed=True)
                    self.current = turn
                    self.turns[turn.id] = turn
                    while len(self.turns) > 64:
                        self.turns.popitem(last=False)
            elif item.role == "assistant":
                start = metrics.get("started_speaking_at")
                latency = metrics.get("e2e_latency")
                if start is not None and latency is not None:
                    anchor = start - latency
                    matches = [
                        t
                        for t in self.turns.values()
                        if t.ended is not None and abs(t.ended - anchor) < 0.05
                    ]
                    if len(matches) == 1:
                        turn = matches[0]
            stages = {
                "transcription_delay": "stt_final",
                "end_of_turn_delay": "end_of_turn",
                "llm_node_ttft": "llm_ttft",
                "tts_node_ttfb": "tts_first_audio",
                "e2e_latency": "response_first_audio",
            }
            for key, stage in stages.items():
                if key in metrics:
                    self.emit(stage, turn, duration=metrics[key])
            if item.role == "assistant" and turn and turn.ended is not None:
                end = metrics.get("stopped_speaking_at")
                if end is not None:
                    self.emit(
                        "full_turn",
                        turn,
                        duration=end - turn.ended,
                        status="interrupted" if item.interrupted else "ok",
                    )

        @self.session.on("agent_state_changed")
        def on_agent(event):
            was_speaking = self.agent_speaking
            self.agent_speaking = event.new_state == "speaking"
            if was_speaking and not self.agent_speaking and self.interruption_started:
                start, turn = self.interruption_started
                self.emit("interruption_stop", turn, duration=event.created_at - start)
                self.interruption_started = None

        @self.session.on("error")
        def on_error(event):
            kind = getattr(event.error, "type", "provider_error")
            category = {"stt_error": "stt", "llm_error": "llm", "tts_error": "tts"}.get(
                kind, "unknown"
            )
            module = type(getattr(event, "source", None)).__module__.split(".")
            provider = next(
                (
                    name
                    for name in module
                    if name
                    in {
                        "deepgram",
                        "assemblyai",
                        "openai",
                        "google",
                        "cartesia",
                        "elevenlabs",
                        "murf",
                    }
                ),
                "unknown",
            )
            self.emit(
                "provider_error",
                category=category,
                provider=provider,
                status="error",
                recoverable=bool(getattr(event.error, "recoverable", False)),
            )
            # Safe text feedback still works if TTS is down. No recursive spoken retry.
            self.orchestrator.emit(
                {
                    "type": "error",
                    "code": "provider_unavailable",
                    "message": "A voice service is unavailable. Try again shortly, "
                    "or reconnect if the session has ended.",
                }
            )

        @self.session.on("user_transcription_timeout")
        def on_timeout(_event):
            self.emit("transcription_timeout", self.current, status="error")
            self.orchestrator.emit(
                {
                    "type": "error",
                    "code": "transcription_timeout",
                    "message": "No speech transcript was received. Please try again, "
                    "check your microphone, or use text input.",
                }
            )

        self.orchestrator.event_listeners.append(self.on_tool)

    def on_tool(self, event):
        if event.get("type") != "tool":
            return
        key, status = event["id"], event["status"]
        if status == "selected" and key not in self.tools:
            self.tools[key] = {"turn": self.current, "start": None, "done": False}
            while len(self.tools) > 256:
                self.tools.popitem(last=False)
        record = self.tools.get(key)
        if not record or record["done"]:
            return
        if status == "running" and record["start"] is None:
            record["start"] = self.monotonic()
        elif status not in {"selected", "running", "confirmation_required"}:
            record["done"] = True
            duration = (
                self.monotonic() - record["start"]
                if record["start"] is not None
                else None
            )
            self.emit(
                "tool_execution",
                record["turn"],
                tool_call_id=key,
                duration=duration,
                status=status,
            )

    async def close(self):
        if self.closed:
            return
        self.closed = True
        await asyncio.to_thread(self.telemetry.close)


def install_observability(ctx, session, orchestrator, settings):
    request_id = getattr(getattr(ctx, "job", None), "id", None)
    telemetry = Telemetry(
        orchestrator.state.conversation_id,
        getattr(settings, "observability", ObservabilitySettings()),
        request_id=request_id,
    )
    set_tracer_provider(
        telemetry.provider,
        allow_pii=False,
        metadata={
            "session_id": orchestrator.state.conversation_id,
            "request_id": telemetry.request_id,
        },
    )
    correlation.set(
        {"session_id": telemetry.session_id, "request_id": telemetry.request_id}
    )
    observer = SessionObserver(session, orchestrator, telemetry)
    orchestrator.telemetry = telemetry

    async def shutdown_telemetry():
        # SDK shutdown callbacks run concurrently. Wait for native close and tool
        # cancellation before shutting down their exporter.
        try:
            await session.aclose()
            if orchestrator.workbench_installed:
                await orchestrator.cleanup_complete.wait()
            else:
                await orchestrator.executor.close()
        finally:
            await observer.close()

    ctx.add_shutdown_callback(shutdown_telemetry)
    return observer
