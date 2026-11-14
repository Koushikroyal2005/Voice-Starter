from app.agents.conversation import ConversationState
from app.tools.base import ToolDefinition, ToolFailure


def require_permission(
    state: ConversationState, allowlist: frozenset[str], tool: ToolDefinition
) -> None:
    if state.closed or not state.actor_id:
        raise ToolFailure("session_unavailable", "The session is not available.")
    if tool.name not in allowlist or tool.permission not in state.permissions:
        raise ToolFailure(
            "permission_denied", "This action is not permitted in this session."
        )
