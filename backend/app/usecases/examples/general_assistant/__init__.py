from app.agents.instructions import DEFAULT_INSTRUCTIONS
from app.usecases.base import UseCase

USE_CASE = UseCase(
    id="general_assistant",
    name="Voice Workbench",
    description="A foundation for real conversations",
    instructions=DEFAULT_INSTRUCTIONS,
    restrict_languages=False,
    mcp_servers=None,
)
