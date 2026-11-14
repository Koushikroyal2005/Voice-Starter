"""Application execution state only; LiveKit owns the conversation/chat history."""

from dataclasses import dataclass, field


@dataclass
class ConversationState:
    conversation_id: str
    actor_id: str | None = None
    # Granted by trusted backend composition, never tool arguments or the LLM.
    permissions: frozenset[str] = field(
        default_factory=lambda: frozenset({"tools:read"})
    )
    closed: bool = False
