"""Opt-in WAV replay through AgentSession; not browser or network-room timing."""

import asyncio
import time
import wave
from dataclasses import replace

from livekit import rtc
from livekit.agents.voice import io

from app.agents.orchestrator import MainAgent
from app.bootstrap import build_orchestrator
from app.observability.session import SessionObserver
from app.providers.pipeline import create_session


class ReplayInput(io.AudioInput):
    def __init__(self, filename):
        super().__init__(label="evaluation-wav")
        self.file = wave.open(str(filename), "rb")
        if (
            self.file.getsampwidth() != 2
            or self.file.getnchannels() != 1
            or self.file.getframerate() != 16000
        ):
            self.file.close()
            raise ValueError("Fixtures must be mono, 16-bit PCM, 16000 Hz WAV")
        if self.file.getnframes() > 16000 * 90:
            self.file.close()
            raise ValueError("Fixtures must be at most 90 seconds")
        self.silence_frames = 100

    async def __anext__(self):
        data = self.file.readframes(320)
        if not data:
            if not self.silence_frames:
                raise StopAsyncIteration
            self.silence_frames -= 1
            data = bytes(640)
        await asyncio.sleep(len(data) / 32000)
        return rtc.AudioFrame(
            data=data,
            sample_rate=16000,
            num_channels=1,
            samples_per_channel=len(data) // 2,
        )


class TimedSink(io.AudioOutput):
    """Pace real TTS frames without recording or using a playback device."""

    def __init__(self):
        super().__init__(
            label="evaluation-sink",
            capabilities=io.AudioOutputCapabilities(pause=False),
        )
        self.active = False
        self.duration = 0
        self.generation = 0

    async def capture_frame(self, frame):
        await super().capture_frame(frame)
        if not self.active:
            self.active = True
            self.duration = 0
            self.on_playback_started(created_at=time.time())
        generation = self.generation
        duration = frame.samples_per_channel / frame.sample_rate
        await asyncio.sleep(duration)
        if generation == self.generation:
            self.duration += duration

    def flush(self):
        super().flush()
        if self.active:
            self.active = False
            self.on_playback_finished(
                playback_position=self.duration, interrupted=False
            )

    def clear_buffer(self):
        self.generation += 1
        if self.active:
            self.active = False
            self.on_playback_finished(playback_position=self.duration, interrupted=True)


class Capture:
    def __init__(self, session_id):
        self.session_id = session_id
        self.events = []

    def event(self, stage, **values):
        self.events.append({"stage": stage, **values})

    def close(self):
        pass


async def run_voice(settings, filename, timeout=120, *, observe_session=None):
    session = create_session(settings)
    # Preserve roomless evaluation's no-MCP boundary even if operator settings
    # enable MCP. The runner supplies the safe builtin allowlist as before.
    orchestrator = build_orchestrator(replace(settings, mcp_enabled=False))
    orchestrator.state.actor_id = "evaluation-user"
    capture = Capture(orchestrator.state.conversation_id)
    observer = SessionObserver(session, orchestrator, capture)
    source, sink = ReplayInput(filename), TimedSink()
    session.input.audio, session.output.audio = source, sink
    transcripts = []

    @session.on("conversation_item_added")
    def item(event):
        if event.item.role == "user":
            transcripts.append(event.item.text_content or "")

    try:
        # Evaluation-only seam. Production sessions never import this runner.
        if observe_session is not None:
            observe_session(session)
        async with asyncio.timeout(timeout):
            await session.start(agent=MainAgent(settings, orchestrator), record=False)
            # Replay duration + trailing silence, then wait for settled agent output.
            duration = source.file.getnframes() / 16000 + 2
            await asyncio.sleep(duration)
            stable = 0
            while stable < 10:
                await asyncio.sleep(0.2)
                stable = (
                    stable + 1 if session.agent_state in {"listening", "idle"} else 0
                )
    finally:
        await session.aclose()
        await orchestrator.executor.close()
        source.file.close()
        await observer.close()
    return capture, " ".join(transcripts)
