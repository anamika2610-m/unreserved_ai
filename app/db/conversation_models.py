"""
Database models for conversation history storage.
"""

from sqlalchemy import Column, String, Text, DateTime, Boolean, JSON, Integer
from sqlalchemy.sql import func
from app.db.base import Base


class ConversationMessage(Base):
    """
    Store individual messages in a conversation.
    """
    __tablename__ = "conversation_messages"
    
    id = Column(String, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    listing_id = Column(String, index=True, nullable=False)
    
    # Message content
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    
    # Metadata
    needs_vendor_contact = Column(Boolean, default=False)
    nearby_properties = Column(JSON, default=[])
    nearby_amenities = Column(JSON, default=[])
    
    # Model information
    model_version = Column(String, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    def to_dict(self):
        """Convert to dictionary."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "listing_id": self.listing_id,
            "question": self.question,
            "answer": self.answer,
            "needs_vendor_contact": self.needs_vendor_contact,
            "nearby_properties": self.nearby_properties or [],
            "nearby_amenities": self.nearby_amenities or [],
            "model_version": self.model_version,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class ConversationSession(Base):
    """
    Store conversation session metadata.
    """
    __tablename__ = "conversation_sessions"
    
    session_id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    listing_id = Column(String, index=True, nullable=False)
    
    # Session metadata
    message_count = Column(Integer, default=0)
    first_message_at = Column(DateTime(timezone=True), server_default=func.now())
    last_message_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Status
    is_active = Column(Boolean, default=True)
    
    def to_dict(self):
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "listing_id": self.listing_id,
            "message_count": self.message_count,
            "first_message_at": self.first_message_at.isoformat() if self.first_message_at else None,
            "last_message_at": self.last_message_at.isoformat() if self.last_message_at else None,
            "is_active": self.is_active
        }

