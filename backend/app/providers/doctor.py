"""Opt-in inference checks. No requests on import, profile resolution or startup."""

import asyncio
import wave
from pathlib import Path

from livekit import rtc
from livekit.agents import APIConnectOptions, llm, stt

from app.providers.factory import create_llm, create_stt, create_tts
from app.providers.registry import registry


def classify_failure(error: Exception) -> str:
    """Inspect untrusted bodies locally; output only a fixed classification."""
    text = (str(error) + " " + str(getattr(error, "body", ""))).lower()
    status = getattr(error, "status_code", None) or getattr(error, "code", None)
    if (
        isinstance(error, TimeoutError)
        or "timeout" in type(error).__name__.lower()
        or "timed out" in text
        or "readtimeout" in text
    ):
        return "timeout"
    if "model_terms_required" in text:
        return "model_terms_required"
    if status == 401 or "api_key_invalid" in text or "api key not valid" in text:
        return "invalid_credentials"
    if status == 429 or "resource_exhausted" in text:
        return "quota_exceeded"
    if status == 404 or "model_not_found" in text:
        return "model_unavailable"
    if status == 403:
        return "access_denied"
    if status in (400, 422):
        return "unsupported_request_format"
    if "connection" in type(error).__name__.lower() or isinstance(error, OSError):
        return "network_failure"
    return "provider_error"


def offline_report(settings):
    stages = []
    for category in ("stt", "llm", "tts"):
        config = getattr(settings, category)
        spec = registry.get(category, config.provider)
        placeholder = config.api_key.startswith(("replace-", "YOUR_", "CHANGE_ME"))
        metadata = spec.model_metadata.get(config.model)
        caps = spec.capabilities_for(config.model, base_url=config.base_url)
        stages.append(
            {
                "stage": category,
                "provider": spec.name,
                "model": config.model if metadata else "custom_model_not_catalogued",
                "credentials": "missing_credentials" if placeholder else "present",
                "configuration": "pass",
                "capabilities": {
                    "streaming": caps.streaming,
                    "interim_transcription": caps.interim_transcription,
                    "tool_calling": caps.tool_calling,
                },
                "inference": "not_tested",
            }
        )
    return {
        "profile": settings.voice_profile or "legacy_environment",
        "mode": "offline",
        "overrides": list(settings.profile_overrides),
        "stages": stages,
        "result": "configuration_valid_inference_not_tested"
        if all(s["credentials"] == "present" for s in stages)
        else "missing_credentials",
    }


def read_sample(path: Path):
    # User-supplied audio is explicitly opt-in; never log or store its contents.
    with wave.open(str(path), "rb") as source:
        if (source.getsampwidth(), source.getnchannels(), source.getframerate()) != (
            2,
            1,
            16000,
        ):
            raise ValueError("WAV must be mono signed 16-bit PCM at 16000 Hz")
        count = source.getnframes()
        if not 0 < count <= 16000 * 15:
            raise ValueError("WAV must contain at most 15 seconds of audio")
        data = source.readframes(count)
    return [
        rtc.AudioFrame(
            data=data, sample_rate=16000, num_channels=1, samples_per_channel=count
        )
    ]


async def live_report(settings, *, wav: Path | None = None, timeout: float = 15):
    report = offline_report(settings)
    report["mode"] = "live"
    if report["result"] == "missing_credentials":
        return report
    # Validate the fixture before making any billable request.
    audio = read_sample(wav) if wav else []
    options = APIConnectOptions(max_retry=0, timeout=min(timeout, 10))
    by_category = {s["stage"]: s for s in report["stages"]}
    for category in ("tts", "llm", "stt"):
        provider = None
        stage = by_category[category]
        try:
            if category == "stt" and not audio:
                stage["inference"] = "not_tested_no_audio"
                continue
            async with asyncio.timeout(timeout):
                provider = {"stt": create_stt, "llm": create_llm, "tts": create_tts}[
                    category
                ](getattr(settings, category))
                if category == "tts":
                    frames = []
                    async with provider.synthesize(
                        "Hello. This is a voice test.", conn_options=options
                    ) as stream:
                        async for event in stream:
                            frame = event.frame
                            if (
                                frame.sample_rate != provider.sample_rate
                                or frame.num_channels != provider.num_channels
                            ):
                                raise ValueError("Invalid audio metadata")
                            frames.append(frame)
                    if not frames or not any(any(f.data) for f in frames):
                        raise ValueError("No nonempty audio")
                    stage["audio_frames"] = len(frames)
                    stage["sample_rate"] = provider.sample_rate
                    if not wav:
                        # Synthetic diagnostic speech, not a private recording.
                        audio = frames
                elif category == "llm":
                    context = llm.ChatContext()
                    context.add_message(role="user", content="Reply with only hello.")
                    chunks = 0
                    async with provider.chat(
                        chat_ctx=context, conn_options=options
                    ) as stream:
                        async for event in stream:
                            if event.delta and event.delta.content:
                                chunks += 1
                    if not chunks:
                        raise ValueError("No LLM content")
                    stage["streaming"] = "pass"
                    stage["tool_calling"] = "not_tested"
                elif provider.capabilities.streaming:
                    transcripts = []
                    async with provider.stream(conn_options=options) as stream:
                        for frame in audio:
                            stream.push_frame(frame)
                        stream.end_input()
                        async for event in stream:
                            if (
                                event.type == stt.SpeechEventType.FINAL_TRANSCRIPT
                                and event.alternatives
                                and event.alternatives[0].text.strip()
                            ):
                                transcripts.append(True)
                    if not transcripts:
                        raise ValueError("No transcript")
                else:
                    event = await provider.recognize(audio, conn_options=options)
                    if not event.alternatives or not event.alternatives[0].text.strip():
                        raise ValueError("No transcript")
                stage["inference"] = "pass"
        except Exception as error:
            stage["inference"] = "failed"
            stage["failure"] = classify_failure(error)
            status = getattr(error, "status_code", None) or getattr(error, "code", None)
            if isinstance(status, int):
                stage["http_status"] = status
        finally:
            if provider:
                try:
                    async with asyncio.timeout(3):
                        await provider.aclose()
                except Exception:
                    stage["cleanup"] = "failed"
    report["result"] = (
        "ready_for_browser_testing"
        if all(
            s["inference"] == "pass" and s.get("cleanup") != "failed"
            for s in report["stages"]
        )
        else "not_ready"
    )
    return report
