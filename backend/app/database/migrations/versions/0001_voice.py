"""Common voice metadata; deliberately no business tables or audio columns."""

import sqlalchemy as sa
from alembic import op

revision = "0001_voice"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "voice_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_key", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(24), nullable=False),
    )
    op.create_index(
        "ix_voice_conversations_owner_key", "voice_conversations", ["owner_key"]
    )
    op.create_table(
        "voice_turns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("voice_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id", "external_id"),
    )
    op.create_index(
        "ix_voice_turns_conversation_id", "voice_turns", ["conversation_id"]
    )
    op.create_table(
        "voice_tool_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("voice_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("call_id", sa.String(128), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id", "call_id"),
    )
    op.create_index(
        "ix_voice_tool_executions_conversation_id",
        "voice_tool_executions",
        ["conversation_id"],
    )


def downgrade():
    op.drop_table("voice_tool_executions")
    op.drop_table("voice_turns")
    op.drop_table("voice_conversations")
