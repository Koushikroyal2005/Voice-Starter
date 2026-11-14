"""Common infrastructure only; application/domain tables belong elsewhere."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(UTC)


def identifier():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "voice_conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_key: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="active")


class Turn(Base):
    __tablename__ = "voice_turns"
    __table_args__ = (UniqueConstraint("conversation_id", "external_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("voice_conversations.id", ondelete="CASCADE"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ToolExecution(Base):
    __tablename__ = "voice_tool_executions"
    __table_args__ = (UniqueConstraint("conversation_id", "call_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("voice_conversations.id", ondelete="CASCADE"), index=True
    )
    call_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
