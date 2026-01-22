"""
Chat API endpoint for property listing conversations.
Supports conversation history for context-aware responses.
"""

# Import config to ensure environment variables are set
import app.config  # noqa: F401

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID

from app.schemas import BuyerEnquiry
from app.services.rag_pipeline.preprocess import preprocess_enquiry, detect_query_source
from app.services.rag_pipeline.generation import ResponseGenerator
from app.db.session import get_db
from app.db.postgres.repositories.conversation_repository import ConversationRepository
from app.db.models.conversation import ConversationRole
from sqlalchemy.orm import Session


# ------------------------------------------------------------------------------
# Router
# ------------------------------------------------------------------------------
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

# ------------------------------------------------------------------------------
# Generator (singleton)
# ------------------------------------------------------------------------------
_generator: Optional[ResponseGenerator] = None


def get_generator() -> ResponseGenerator:
    global _generator
    if _generator is None:
        _generator = ResponseGenerator()  # pgvector-backed
    return _generator


# ------------------------------------------------------------------------------
# Request / Response Models
# ------------------------------------------------------------------------------
class ChatRequest(BaseModel):
    """Request model for chat endpoint."""

    question: str = Field(..., description="User's question about the property or general real estate query")

    listing_id: UUID = Field(
        ..., description="Property listing ID (UUID). Required."
    )

    user_id: Optional[UUID] = Field(
        None, description="User ID (UUID). Optional, defaults to 'api_user'."
    )

    conversation_id: Optional[UUID] = Field(
        None, description="Existing conversation ID (UUID)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "question": "What are the pricing and amenities?",
                "listing_id": "950b945a-5604-49a0-9cf9-3d3c16cf9c1a",
                "user_id": "22c91760-ac98-4d05-b545-cdb5a7a8d23f"
            }
        }


class ChatResponse(BaseModel):
    """Response model for chat endpoint."""

    answer: str = Field(..., description="Bot's response to the user's question")
    conversation_id: str = Field(..., description="Conversation ID")
    needs_vendor_contact: Optional[bool] = None
    nearby_properties: Optional[List[Dict[str, Any]]] = None
    amenity_links: Optional[List[Dict[str, Any]]] = None
    timestamp: Optional[str] = None
    error_details: Optional[str] = Field(None, description="Error details (only in DEBUG mode)")


# ------------------------------------------------------------------------------
# Chat Endpoint
# ------------------------------------------------------------------------------
@router.post(
    "/message",
    response_model=ChatResponse,
    response_model_exclude_none=True,
)
async def chat_message(
    request: ChatRequest,
    generator: ResponseGenerator = Depends(get_generator),
    db: Session = Depends(get_db),
) -> ChatResponse:
    """
    Send a message to the property chatbot and get a response.
    """

    try:
        from uuid import uuid5, NAMESPACE_DNS
        from sqlalchemy import text
        
        # ----------------------------------------------------------
        # Set default values for optional fields
        # ----------------------------------------------------------
        # Default user_id for anonymous/generic queries
        user_id = request.user_id or uuid5(NAMESPACE_DNS, "api_user")

        listing_id = request.listing_id
        
        conversation_repo = ConversationRepository(db)

        # ----------------------------------------------------------
        # Get or create conversation (scoped by user_id + listing_id)
        # Query may still be generic; routing is decided by text, not listing_id presence.
        # ----------------------------------------------------------
        conversation = conversation_repo.get_or_create_conversation(
            user_id=user_id,
            listing_id=listing_id,
            conversation_id=request.conversation_id,
        )

        # ----------------------------------------------------------
        # Fetch recent conversation history BEFORE adding new message
        # This ensures we only get PREVIOUS messages, not the current one
        # ----------------------------------------------------------
        conversation_history = conversation_repo.get_recent_messages(
            conversation_id=conversation.id,
            n_messages=10,
        )

        enquiry = BuyerEnquiry(
            question=request.question,
            listing_id=listing_id,
            user_id=user_id,
        )

        enquiry_data = preprocess_enquiry(enquiry)

        # ----------------------------------------------------------
        # Detect whether the query is GENERIC vs PROPERTY-specific
        # This uses the text + conversation history, not listing_id.
        # ----------------------------------------------------------
        source = detect_query_source(
            enquiry_data["normalized_query"],
            conversation_history=conversation_history,
        )
        is_generic_query = (source == "generic")

        # ----------------------------------------------------------
        # Store user message AFTER fetching history & determining query type
        # ----------------------------------------------------------
        conversation_repo.add_message(
            conversation_id=conversation.id,
            role=ConversationRole.user,
            content=request.question,
            metadata={
                "listing_id": str(request.listing_id) if request.listing_id else None,
                "query_type": "generic" if is_generic_query else "property_specific",
            },
        )

        # ----------------------------------------------------------
        # Generate AI response (RAG)
        # generate_response will detect if query is generic and override listing_id internally
        # But we also check here for conversational queries to prevent property data retrieval
        # ----------------------------------------------------------
        query_text = enquiry_data["normalized_query"].lower()
        is_conversational = any(phrase in query_text for phrase in [
            'recording', 'testing', 'test', 'checking', 'see how', 'let\'s see', 
            'just testing', 'trying out', 'how does this work', 'how does it work'
        ])
        
        final_listing_id = None if is_conversational else enquiry_data.get("listing_id")
        
        if is_conversational:
            print(f"🔍 Conversational query detected → forcing listing_id=None to prevent property data retrieval")

        # Convert UUID objects to strings for generate_response
        final_user_id = str(enquiry_data.get("user_id")) if enquiry_data.get("user_id") else None
        final_listing_id_str = str(final_listing_id) if final_listing_id else None
        
        result = generator.generate_response(
            query=enquiry_data["normalized_query"],
            listing_id=final_listing_id_str,  # None for generic/conversational, UUID string for property-specific
            user_id=final_user_id,  # Always set (UUID string or None)
            conversation_history=conversation_history,
        )

        ai_response = result["ai_response"]
        nearby_properties = result.get("nearby_properties", [])
        amenity_links = result.get("amenity_links", [])

        # ----------------------------------------------------------
        # Store AI response
        # ----------------------------------------------------------
        conversation_repo.add_message(
            conversation_id=conversation.id,
            role=ConversationRole.bot,
            content=ai_response.answer,
            metadata={
                "listing_id": str(request.listing_id) if request.listing_id else None,
                "query_type": "generic" if is_generic_query else "property_specific",
                "needs_vendor_contact": ai_response.needs_vendor_contact,
                "nearby_properties": nearby_properties,
                "amenity_links": amenity_links,
                "data_sources": (
                    [ds.dict() for ds in ai_response.data_sources]
                    if ai_response.data_sources
                    else []
                ),
            },
        )

        # ----------------------------------------------------------
        # Build response
        # ----------------------------------------------------------
        response = {
            "answer": ai_response.answer,
            "conversation_id": str(conversation.id),
            "timestamp": datetime.utcnow().isoformat(),
        }

        if ai_response.needs_vendor_contact:
            response["needs_vendor_contact"] = ai_response.needs_vendor_contact

        if nearby_properties:
            response["nearby_properties"] = nearby_properties

        if amenity_links:
            response["amenity_links"] = amenity_links

      
        if ai_response.escalation_reason:
            escalation_lower = ai_response.escalation_reason.lower()
            
            is_error = any(keyword in escalation_lower for keyword in ["error", "exception", "failed", "rate limit"])
            is_generic_error = "unable to process" in ai_response.answer.lower()
            
            if is_error or is_generic_error:
                response["error_details"] = ai_response.escalation_reason
                
                print(f"⚠️  Error details included in response: {ai_response.escalation_reason}")
        
        # If we have the generic error message but no escalation_reason, something is wrong
        if "unable to process" in ai_response.answer.lower() and not ai_response.escalation_reason:
            response["error_details"] = "Unknown error: escalation_reason was not set"
            print("⚠️  WARNING: Generic error message but no escalation_reason set!")

        return ChatResponse(**response)

    except Exception as e:
        # Log full error details
        import traceback
        error_details = traceback.format_exc()
        print(f"❌ API Error in chat_message: {type(e).__name__}: {str(e)}")
        print(f"Full traceback:\n{error_details}")
        
        # Include error details in response if in debug mode
        import os
        detail_msg = f"Error processing chat request: {str(e)}"
        if os.getenv("DEBUG", "false").lower() == "true":
            detail_msg += f"\n\nFull error: {error_details}"
        
        raise HTTPException(
            status_code=500,
            detail=detail_msg,
        )


class ConversationHistoryResponse(BaseModel):
    """Response model for conversation history."""
    
    conversation_id: str = Field(..., description="Conversation ID")
    messages: List[Dict[str, Any]] = Field(
        ..., 
        description="List of messages in chronological order. Each message includes: message_id (UUID), role, content, created_at (ISO format), and optionally metadata."
    )
    total_messages: int = Field(..., description="Total number of messages in conversation")


@router.get(
    "/history",
    response_model=ConversationHistoryResponse,
)
async def get_conversation_history(
    user_id: UUID = Query(..., description="User ID (UUID)"),
    listing_id: UUID = Query(..., description="Listing ID (UUID)"),
    db: Session = Depends(get_db),
) -> ConversationHistoryResponse:
    """
    Get conversation history for a user and listing.

    Returns up to 40 messages in chronological order.
    Uses query parameters: ?user_id=<uuid>&listing_id=<uuid>
    """
    try:
        conversation_repo = ConversationRepository(db)

        conversations = conversation_repo.get_user_conversations(
            user_id=user_id,
            listing_id=listing_id,
            active_only=True,
        )

        if not conversations:
            raise HTTPException(
                status_code=404,
                detail=f"No conversation found for user_id={user_id} and listing_id={listing_id}",
            )

        conversation = conversations[0]

        messages = conversation_repo.get_conversation_messages(
            conversation_id=conversation.id,
            limit=40,
            include_metadata=True,
        )

        return ConversationHistoryResponse(
            conversation_id=str(conversation.id),
            messages=messages,
            total_messages=len(messages),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving conversation history: {str(e)}",
        )


