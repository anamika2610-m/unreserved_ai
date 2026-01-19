"""
Repository for managing conversations and chat messages.
"""

import uuid
from typing import Optional, List, Dict, Any
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import select, desc, and_

from app.db.models.conversation import (
    Conversation,
    ChatMessage,
    ConversationRole,
)
from app.db.postgres.repositories.base_repository import BaseRepository


class ConversationRepository(BaseRepository[Conversation]):
    """
    Repository for conversation management.
    """

    def __init__(self, session: Session):
        super().__init__(Conversation, session)
        self.session = session

    def get_or_create_conversation(
        self,
        user_id: UUID,
        listing_id: UUID,
        conversation_id: Optional[UUID] = None,
    ) -> Conversation:
        """
        Get an existing conversation or create a new one.
        
        Args:
            user_id: User ID (required)
            listing_id: Listing ID (required)
            conversation_id: Optional conversation ID to continue existing conversation
            
        Returns:
            Conversation instance
        """
        with self._handle_errors():
            # Continue explicit conversation
            if conversation_id:
                conversation = self.get_by_id(conversation_id)
                if conversation:
                    return conversation

            # Reuse existing conversation for user + listing
            query = select(Conversation).where(
                and_(
                    Conversation.user_id == user_id,
                    Conversation.listing_id == listing_id,
                    Conversation.is_active.is_(True),
                )
            )
            
            result = self.session.execute(query)
            conversation = result.scalar_one_or_none()
            
            if conversation:
                return conversation

            # Create new conversation
            conversation = Conversation(
                id=uuid.uuid4(),
                listing_id=listing_id,
                user_id=user_id,
                message_count=0,
                is_active=True,
                meta_data={},
            )

            self.session.add(conversation)
            self.session.commit()
            self.session.refresh(conversation)

            return conversation

    # ------------------------------------------------------------------
    # Add message + increment message_count (ATOMIC)
    # ------------------------------------------------------------------
    def add_message(
        self,
        conversation_id: UUID,
        role: ConversationRole,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ChatMessage:
        """
        Add a message to a conversation and increment message_count atomically.
        
        Args:
            conversation_id: Conversation ID
            role: Message role (enum)
            content: Message content
            metadata: Optional message metadata
            
        Returns:
            Created ChatMessage instance
            
        Raises:
            ValueError: If conversation_id is None
        """
        if conversation_id is None:
            raise ValueError("conversation_id cannot be None")

        with self._handle_errors():
            message = ChatMessage(
                id=uuid.uuid4(),
                conversation_id=conversation_id,
                role=role,
                content=content,
                meta_data=metadata or {},
            )

            self.session.add(message)

            # Atomic counter update using update() statement
            from sqlalchemy import update
            stmt = (
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(message_count=Conversation.message_count + 1)
            )
            self.session.execute(stmt)

            self.session.commit()
            self.session.refresh(message)

            return message

 
    def _format_message(
        self,
        msg: ChatMessage,
        include_metadata: bool = False
    ) -> Dict[str, Any]:
        """
        Format a ChatMessage for LLM context.
        
        Args:
            msg: ChatMessage instance
            include_metadata: Whether to include metadata
            
        Returns:
            Formatted message dictionary
        """
        item = {
            "role": msg.role.value,  # enum → string
            "content": msg.content,
        }
        if include_metadata and msg.meta_data:
            item["metadata"] = msg.meta_data
        return item

    # ------------------------------------------------------------------
    # Get messages formatted for LLM context
    # ------------------------------------------------------------------
    def get_conversation_messages(
        self,
        conversation_id: UUID,
        limit: Optional[int] = None,
        include_metadata: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Get all messages for a conversation, formatted for LLM context.
        
        Args:
            conversation_id: Conversation ID
            limit: Optional limit on number of messages
            include_metadata: Whether to include message metadata
            
        Returns:
            List of formatted message dictionaries
        """
        with self._handle_errors():
            query = (
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(ChatMessage.created_at)
            )

            if limit:
                query = query.limit(limit)

            result = self.session.execute(query)
            messages = result.scalars().all()

            return [
                self._format_message(msg, include_metadata)
                for msg in messages
            ]

    # ------------------------------------------------------------------
    # Get most recent N messages (chronological order)
    # ------------------------------------------------------------------
    def get_recent_messages(
        self,
        conversation_id: UUID,
        n_messages: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get the most recent N messages for a conversation in chronological order.
        
        Args:
            conversation_id: Conversation ID
            n_messages: Number of recent messages to retrieve
            
        Returns:
            List of formatted message dictionaries in chronological order
        """
        with self._handle_errors():
            query = (
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(desc(ChatMessage.created_at))
                .limit(n_messages)
            )

            result = self.session.execute(query)
            messages = list(result.scalars().all())
            messages.reverse()  # Reverse to get chronological order

            return [
                self._format_message(msg, include_metadata=False)
                for msg in messages
            ]

    def deactivate_conversation(self, conversation_id: UUID) -> bool:
        """
        Deactivate a conversation by setting is_active to False.
        
        Args:
            conversation_id: Conversation ID
            
        Returns:
            True if deactivated, False if conversation not found
        """
        with self._handle_errors():
            conversation = self.get_by_id(conversation_id)
            if not conversation:
                return False

            conversation.is_active = False
            self.session.commit()
            return True

    # ------------------------------------------------------------------
    # Get conversations for a user
    # ------------------------------------------------------------------
    def get_user_conversations(
        self,
        user_id: UUID,
        listing_id: Optional[UUID] = None,
        active_only: bool = True,
    ) -> List[Conversation]:
        """
        Get all conversations for a user, optionally filtered by listing.
        
        Args:
            user_id: User ID
            listing_id: Optional listing ID filter (None for generic conversations)
            active_only: Whether to return only active conversations
            
        Returns:
            List of Conversation instances, ordered by most recent first
        """
        with self._handle_errors():
            query = select(Conversation).where(Conversation.user_id == user_id)

            if listing_id:
                query = query.where(Conversation.listing_id == listing_id)

            if active_only:
                query = query.where(Conversation.is_active.is_(True))

            query = query.order_by(desc(Conversation.created_at))

            result = self.session.execute(query)
            return list(result.scalars().all())
