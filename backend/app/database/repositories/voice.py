"""Repositories require server-derived ownership for every operation; no commits."""

from sqlalchemy import select

from app.database.models import Conversation, ToolExecution, Turn, now


class RecordUnavailable(PermissionError):
    pass


class VoiceRepository:
    def __init__(self, session, owner_key: str):
        if len(owner_key) != 64:
            raise ValueError("A server-derived owner key is required")
        self.session = session
        self.owner_key = owner_key

    async def require(self, conversation_id):
        record = await self.session.scalar(
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.owner_key == self.owner_key,
            )
            .with_for_update()
        )
        if record is None:
            raise RecordUnavailable("Conversation unavailable")
        return record

    async def create(self, conversation_id):
        self.session.add(Conversation(id=conversation_id, owner_key=self.owner_key))
        await self.session.flush()

    async def close(self, conversation_id):
        record = await self.require(conversation_id)
        record.status, record.ended_at = "closed", now()

    async def add_turn(self, conversation_id, external_id, role, text):
        await self.require(conversation_id)
        if role not in {"user", "assistant"}:
            raise ValueError("Unsupported transcript role")
        existing = await self.session.scalar(
            select(Turn).where(
                Turn.conversation_id == conversation_id, Turn.external_id == external_id
            )
        )
        if existing is None:
            self.session.add(
                Turn(
                    conversation_id=conversation_id,
                    external_id=external_id[:128],
                    role=role,
                    text=text,
                )
            )

    async def tool_event(self, conversation_id, event):
        await self.require(conversation_id)
        record = await self.session.scalar(
            select(ToolExecution).where(
                ToolExecution.conversation_id == conversation_id,
                ToolExecution.call_id == event["id"],
            )
        )
        if record is None:
            record = ToolExecution(
                conversation_id=conversation_id, call_id=event["id"][:128]
            )
            self.session.add(record)
        record.title = event["name"][:200]
        record.status = event["status"][:32]
        record.updated_at = now()

    async def turns(self, conversation_id, limit=100):
        await self.require(conversation_id)
        return list(
            await self.session.scalars(
                select(Turn)
                .where(Turn.conversation_id == conversation_id)
                .order_by(Turn.created_at)
                .limit(max(1, min(limit, 100)))
            )
        )

    async def tools(self, conversation_id, limit=100):
        await self.require(conversation_id)
        return list(
            await self.session.scalars(
                select(ToolExecution)
                .where(ToolExecution.conversation_id == conversation_id)
                .order_by(ToolExecution.updated_at)
                .limit(max(1, min(limit, 100)))
            )
        )
