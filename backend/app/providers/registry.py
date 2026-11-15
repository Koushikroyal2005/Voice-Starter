"""Metadata registry; LiveKit objects remain the actual provider interfaces."""

from dataclasses import dataclass
from typing import Literal

Category = Literal["stt", "llm", "tts"]


class ProviderError(ValueError):
    """Invalid provider selection or capability requirement."""


@dataclass(frozen=True)
class Capabilities:
    # None means model/endpoint dependent or not applicable, never guaranteed.
    streaming: bool
    interim_transcription: bool | None = None
    turn_detection: bool | None = None
    multilingual: bool | None = None
    cancellation: bool = True
    tool_calling: bool | None = None
    notes: str = "Cancellation closes local streams; remote billing may continue."


@dataclass(frozen=True)
class ProviderSpec:
    category: Category
    name: str
    builder: str
    api_key_env: str
    model: str
    capabilities: Capabilities
    voice: str = ""
    base_url: str = ""
    docs: str = ""
    models: tuple[str, ...] = ()  # Empty: defer model availability to provider API.


class ProviderRegistry:
    def __init__(self) -> None:
        self._entries: dict[tuple[Category, str], ProviderSpec] = {}

    def register(self, spec: ProviderSpec) -> None:
        if spec.category not in ("stt", "llm", "tts") or not spec.name:
            raise ProviderError("Provider requires a valid category and name")
        key = (spec.category, spec.name)
        if key in self._entries:
            raise ProviderError(f"Duplicate provider: {spec.category}/{spec.name}")
        self._entries[key] = spec

    def get(self, category: Category, name: str) -> ProviderSpec:
        try:
            return self._entries[(category, name)]
        except KeyError:
            supported = ", ".join(p.name for p in self.list(category))
            raise ProviderError(
                f"Unsupported {category} provider {name!r}. Supported: {supported}"
            ) from None

    def list(self, category: Category) -> tuple[ProviderSpec, ...]:
        return tuple(p for p in self._entries.values() if p.category == category)

    def require(self, category: Category, name: str, capability: str) -> None:
        caps = self.get(category, name).capabilities
        if capability not in Capabilities.__dataclass_fields__ or capability == "notes":
            raise ProviderError(f"Unknown capability: {capability}")
        if getattr(caps, capability) is not True:
            raise ProviderError(
                f"{category}/{name} does not guarantee {capability}; "
                "check the selected model/endpoint"
            )


registry = ProviderRegistry()

for spec in (
    ProviderSpec(
        "stt",
        "groq",
        "app.providers.stt:groq",
        "GROQ_API_KEY",
        "whisper-large-v3-turbo",
        Capabilities(False, False, False, True),
        docs="https://console.groq.com/docs/speech-to-text",
        models=("whisper-large-v3-turbo", "whisper-large-v3"),
    ),
    ProviderSpec(
        "tts",
        "groq",
        "app.providers.tts:groq_tts",
        "GROQ_API_KEY",
        "canopylabs/orpheus-v1-english",
        Capabilities(False, multilingual=False),
        voice="troy",
        docs="https://console.groq.com/docs/text-to-speech/orpheus",
        models=("canopylabs/orpheus-v1-english",),
    ),
    ProviderSpec(
        "stt",
        "gemini",
        "app.providers.stt:gemini",
        "GOOGLE_API_KEY",
        "gemini-3.5-transcribe-live",
        Capabilities(True, True, False, None),
        docs="https://docs.livekit.io/agents/models/stt/gemini/",
        models=("gemini-3.5-transcribe-live",),
    ),
    ProviderSpec(
        "tts",
        "gemini",
        "app.providers.tts:gemini",
        "GOOGLE_API_KEY",
        "gemini-3.1-flash-tts-preview",
        Capabilities(
            False,
            multilingual=None,
            notes="Non-streaming text input; native chunked audio output. "
            "AgentSession uses its sentence StreamAdapter. Local cancellation only.",
        ),
        voice="Kore",
        docs="https://docs.livekit.io/agents/models/tts/gemini/",
        models=(
            "gemini-2.5-flash-preview-tts",
            "gemini-2.5-pro-preview-tts",
            "gemini-3.1-flash-tts-preview",
            "gemini-3.8-flash-tts",
            "gemini-3.8-flash-lite-tts",
        ),
    ),
    ProviderSpec(
        "stt",
        "deepgram",
        "app.providers.stt:deepgram",
        "DEEPGRAM_API_KEY",
        "nova-3",
        Capabilities(True, True, False, None),
        docs="https://docs.livekit.io/agents/models/stt/deepgram/",
        models=("nova-3", "nova-2"),
    ),
    ProviderSpec(
        "stt",
        "assemblyai",
        "app.providers.stt:assemblyai",
        "ASSEMBLYAI_API_KEY",
        "universal-3-6-pro",
        Capabilities(True, True, True, None),
        docs="https://docs.livekit.io/agents/models/stt/assemblyai/",
        models=(
            "universal-3-6-pro",
            "universal-3-5-pro",
            "universal-streaming-english",
            "universal-streaming-multilingual",
        ),
    ),
    ProviderSpec(
        "stt",
        "whisper",
        "app.providers.stt:whisper",
        "OPENAI_API_KEY",
        "whisper-1",
        Capabilities(False, False, False, True),
        base_url="https://api.openai.com/v1",
        docs="https://docs.livekit.io/agents/models/stt/openai/",
        models=("whisper-1",),
    ),
    ProviderSpec(
        "llm",
        "openai_compatible",
        "app.providers.llm:openai_compatible",
        "LLM_API_KEY",
        "gpt-4.1-mini",
        Capabilities(True, multilingual=None, tool_calling=None),
        base_url="https://api.openai.com/v1",
        docs="https://docs.livekit.io/agents/models/llm/openai/",
    ),
    ProviderSpec(
        "llm",
        "gemini",
        "app.providers.llm:gemini",
        "GOOGLE_API_KEY",
        "gemini-3.5-flash",
        Capabilities(True, multilingual=None, tool_calling=None),
        docs="https://docs.livekit.io/agents/models/llm/gemini/",
    ),
    ProviderSpec(
        "tts",
        "cartesia",
        "app.providers.tts:cartesia",
        "CARTESIA_API_KEY",
        "sonic-3",
        Capabilities(True, multilingual=None),
        voice="f786b574-daa5-4673-aa0c-cbe3e8534c02",
        docs="https://docs.livekit.io/agents/models/tts/cartesia/",
    ),
    ProviderSpec(
        "tts",
        "elevenlabs",
        "app.providers.tts:elevenlabs",
        "ELEVEN_API_KEY",
        "eleven_multilingual_v2",
        Capabilities(True, multilingual=None),
        voice="ODq5zmih8GrVes37Dizd",
        docs="https://docs.livekit.io/agents/models/tts/elevenlabs/",
    ),
    ProviderSpec(
        "tts",
        "murf",
        "app.providers.tts:murf",
        "MURF_API_KEY",
        "FALCON",
        Capabilities(True, multilingual=None),
        voice="en-US-matthew",
        docs="https://docs.livekit.io/agents/models/tts/murf/",
    ),
):
    registry.register(spec)
