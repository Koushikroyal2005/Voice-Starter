"""Transaction boundary and privacy policy; repositories never see raw text."""

from app.database.repositories.voice import VoiceRepository


class ConversationService:
    def __init__(self, database, redactor, transcripts_enabled=False):
        self.database = database
        self.redactor = redactor
        self.transcripts_enabled = transcripts_enabled

    async def apply(self, owner_key, conversation_id, kind, data=None):
        async with self.database.transaction() as session:
            repo = VoiceRepository(session, owner_key)
            if kind == "start":
                await repo.create(conversation_id)
            elif kind == "close":
                await repo.close(conversation_id)
            elif kind == "tool":
                await repo.tool_event(
                    conversation_id,
                    {
                        "id": data["id"],
                        "name": self.redactor.text(data["name"]),
                        "status": data["status"],
                    },
                )
            elif kind == "turn" and self.transcripts_enabled:
                await repo.add_turn(
                    conversation_id,
                    data["id"],
                    data["role"],
                    self.redactor.text(data["text"]),
                )
            else:
                await repo.require(conversation_id)
