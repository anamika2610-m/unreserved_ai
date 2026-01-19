"""
SQLAlchemy models for conversation history.
UUID-safe, Postgres-native, production ready.
"""

import uuid
import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ENUM
from sqlalchemy.orm import relationship

from app.db.base import Base


# ----------------------------------------------------------------------
# Postgres ENUM mapping (must match DB enum exactly)
# ----------------------------------------------------------------------
class ConversationRole(enum.Enum):
    user = "user"
    bot = "bot"  # Database enum uses 'bot', not 'assistant'


# ----------------------------------------------------------------------
# Conversation model
# ----------------------------------------------------------------------
class Conversation(Base):
    """
    Represents a chat session between a user and the AI
    for a specific property listing.

    One conversation per (user_id, listing_id).
    """

    __tablename__ = "conversations"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    listing_id = Column(
        UUID(as_uuid=True),
        nullable=True,  # Allow NULL for generic conversations
        index=True,
    )

    user_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    message_count = Column(
        Integer,
        default=0,
        nullable=False,
    )

    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
    )

    meta_data = Column(
        "metadata",
        JSONB,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    # One conversation → many messages
    messages = relationship(
        "ChatMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )

    __table_args__ = (
        # Enforce ONE conversation per user + listing
        UniqueConstraint(
            "user_id",
            "listing_id",
            name="unique_conversation_per_user_and_listing",
        ),
        Index("idx_conversation_listing_user", "listing_id", "user_id"),
        Index("idx_conversation_active", "is_active"),
    )


# ----------------------------------------------------------------------
# ChatMessage model
# ----------------------------------------------------------------------
class ChatMessage(Base):
    """
    Stores individual user / AI messages within a conversation.
    Multiple messages per conversation.
    """

    __tablename__ = "chat_messages"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # IMPORTANT: must map to Postgres ENUM, NOT String
    role = Column(
        ENUM(
            ConversationRole,
            name="conversation_role",
            create_type=False,  # enum already exists in DB
        ),
        nullable=False,
    )

    content = Column(
        Text,
        nullable=False,
    )

    meta_data = Column(
        "metadata",
        JSONB,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    conversation = relationship(
        "Conversation",
        back_populates="messages",
    )

    __table_args__ = (
        Index("idx_message_conversation", "conversation_id", "created_at"),
        Index("idx_message_role", "role"),
    )
