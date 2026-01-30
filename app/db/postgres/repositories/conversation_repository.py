"""
Repository for managing conversations and chat messages.
"""

import uuid
from typing import Optional, List, Dict, Any
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import select, desc, and_
from sqlalchemy.exc import OperationalError, DisconnectionError

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
            
            try:
                result = self.session.execute(query)
                conversation = result.scalar_one_or_none()
            except (OperationalError, DisconnectionError) as e:
                # Check if it's a connection closed error
                error_str = str(e).lower()
                if any(phrase in error_str for phrase in [
                    'connection has been closed',
                    'terminating connection',
                    'ssl connection has been closed',
                    'connection closed unexpectedly'
                ]):
                    # Rollback and retry once with a fresh connection
                    try:
                        self.session.rollback()
                    except:
                        pass
                    # Retry the query once
                    result = self.session.execute(query)
                    conversation = result.scalar_one_or_none()
                else:
                    raise
            
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
            "message_id": str(msg.id),  # Include message ID
            "role": msg.role.value,  # enum → string
            "content": msg.content,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        }
        
        # Extract imageURL from metadata as a top-level field (if it exists)
        if msg.meta_data and "imageURL" in msg.meta_data:
            item["imageURL"] = msg.meta_data["imageURL"]
        
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
        Get messages for a conversation, formatted for LLM context.
        
        If limit is specified, returns the LATEST N messages in chronological order.
        Otherwise returns all messages in chronological order.
        
        Args:
            conversation_id: Conversation ID
            limit: Optional limit on number of messages (returns LATEST N if specified)
            include_metadata: Whether to include message metadata
            
        Returns:
            List of formatted message dictionaries in chronological order
        """
        with self._handle_errors():
            if limit:
                # Get LATEST N messages: order by created_at DESC, limit, then reverse
                query = (
                    select(ChatMessage)
                    .where(ChatMessage.conversation_id == conversation_id)
                    .order_by(desc(ChatMessage.created_at))
                    .limit(limit)
                )
                result = self.session.execute(query)
                messages = list(result.scalars().all())
                messages.reverse()  # Reverse to get chronological order (oldest to newest)
            else:
                # Get ALL messages in chronological order
                query = (
                    select(ChatMessage)
                    .where(ChatMessage.conversation_id == conversation_id)
                    .order_by(ChatMessage.created_at)
                )
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

    # ------------------------------------------------------------------
    # Get all conversations for a listing (for property-level summaries)
    # ------------------------------------------------------------------
    def get_listing_conversations(
        self,
        listing_id: UUID,
        active_only: bool = True,
        limit: Optional[int] = None,
    ) -> List[Conversation]:
        """
        Get all conversations for a specific listing (across all users).
        Used for generating property-level chat summaries.
        
        Args:
            listing_id: Listing ID
            active_only: Whether to return only active conversations
            limit: Optional limit on number of conversations
            
        Returns:
            List of Conversation instances, ordered by most recent first
        """
        with self._handle_errors():
            query = select(Conversation).where(
                Conversation.listing_id == listing_id
            )

            if active_only:
                query = query.where(Conversation.is_active.is_(True))

            query = query.order_by(desc(Conversation.created_at))

            if limit:
                query = query.limit(limit)

            result = self.session.execute(query)
            return list(result.scalars().all())

    def get_listing_user_messages(
        self,
        listing_id: UUID,
        limit_per_conversation: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get all user messages (questions) for a listing across all conversations.
        This aggregates user queries while preserving privacy (no user_id in output).
        
        Args:
            listing_id: Listing ID
            limit_per_conversation: Optional limit on messages per conversation
            
        Returns:
            List of user message dictionaries with content, metadata, and timestamps
            (user_id is excluded for privacy)
        """
        with self._handle_errors():
            # Get all conversations for this listing
            conversations = self.get_listing_conversations(
                listing_id=listing_id,
                active_only=True,
            )

            all_user_messages = []
            for conversation in conversations:
                # Get user messages only (questions)
                query = (
                    select(ChatMessage)
                    .where(
                        and_(
                            ChatMessage.conversation_id == conversation.id,
                            ChatMessage.role == ConversationRole.user,
                        )
                    )
                    .order_by(ChatMessage.created_at)
                )

                if limit_per_conversation:
                    query = query.limit(limit_per_conversation)

                result = self.session.execute(query)
                messages = result.scalars().all()

                for msg in messages:
                    # Format message without user_id for privacy
                    message_data = {
                        "content": msg.content,
                        "created_at": msg.created_at.isoformat() if msg.created_at else None,
                        "query_type": msg.meta_data.get("query_type") if msg.meta_data else None,
                    }
                    all_user_messages.append(message_data)

            return all_user_messages
