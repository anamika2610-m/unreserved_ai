"""
Chat API endpoint for property listing conversations.
Provides a REST API interface similar to chat_listing_cli.py
No conversation history or database dependencies.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import os

# Disable ChromaDB telemetry
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "1")

from app.rag_pipeline.schemas import BuyerEnquiry
from app.rag_pipeline.preprocess import preprocess_enquiry
from app.rag_pipeline.generation import ResponseGenerator


# Create router
router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

# Global generator instance (initialized once)
_generator = None


def get_generator() -> ResponseGenerator:
    """Get or create the response generator instance."""
    global _generator
    if _generator is None:
        _generator = ResponseGenerator(
            embedding_model="all-MiniLM-L6-v2"  # Now using pgvector
        )
    return _generator


# Request/Response Models
class ChatRequest(BaseModel):
    """Request model for chat endpoint."""
    question: str = Field(..., description="User's question about the property")
    listing_id: str = Field(..., description="Property listing ID")
    user_id: Optional[str] = Field(default="api_user", description="User identifier (optional)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "question": "What are the pricing and amenities?",
                "listing_id": "prop-similar-001",
                "user_id": "user123"
            }
        }


class ChatResponse(BaseModel):
    """Response model for chat endpoint."""
    answer: str = Field(..., description="Bot's response to the user's question")
    needs_vendor_contact: Optional[bool] = Field(None, description="Whether the query requires vendor contact")
    nearby_properties: Optional[List[Dict[str, Any]]] = Field(None, description="Nearby properties if query is location-based")
    amenity_links: Optional[List[Dict[str, Any]]] = Field(None, description="Google Maps links for nearby amenities")
    timestamp: Optional[str] = Field(None, description="Response timestamp")
    
    class Config:
        json_schema_extra = {
            "example": {
                "answer": "## [Main Answer]\nThe asking price is $510,000...",
                "needs_vendor_contact": False,
                "nearby_properties": [],
                "amenity_links": [
                    {
                        "type": "hospitals",
                        "icon": "🏥",
                        "label": "Hospitals & Medical Centers",
                        "url": "https://www.google.com/maps/search/hospitals/@-33.8688,151.2093,15z"
                    }
                ],
                "timestamp": "2024-12-19T10:30:00Z"
            }
        }


@router.post("/message", response_model=ChatResponse, response_model_exclude_none=True)
async def chat_message(
    request: ChatRequest,
    generator: ResponseGenerator = Depends(get_generator)
) -> ChatResponse:
    """
    Send a message to the property chatbot and get a response.
    
    This endpoint allows users to have a conversation about a specific property listing.
    It supports:
    - General property questions (price, features, etc.)
    - Location-based queries (nearby properties, amenities)
    - Multi-topic questions
    
    Args:
        request: ChatRequest with question and listing details
        
    Returns:
        ChatResponse with bot's answer, nearby properties, and amenity links
        
    Raises:
        HTTPException: If there's an error processing the request
    """
    try:
        # Create enquiry
        enquiry = BuyerEnquiry(
            question=request.question,
            listing_id=request.listing_id,
            user_id=request.user_id,
            session_id=f"session_{datetime.now().timestamp()}"  # Auto-generated for internal use
        )
        
        # Preprocess and generate response
        enquiry_data = preprocess_enquiry(enquiry)
        result = generator.generate_response_from_enquiry(enquiry_data)
        
        # Extract response data
        ai_response = result["ai_response"]
        nearby_properties = result.get("nearby_properties", [])
        amenity_links = result.get("amenity_links", [])
        
        # Build response with conditional fields
        response_data = {
            "answer": ai_response.answer
        }
        
        # Only include fields when they have meaningful values
        if ai_response.needs_vendor_contact:
            response_data["needs_vendor_contact"] = ai_response.needs_vendor_contact
            
        if nearby_properties:
            response_data["nearby_properties"] = nearby_properties
            
        if amenity_links:
            response_data["amenity_links"] = amenity_links
        
        return ChatResponse(**response_data)
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing chat request: {str(e)}"
        )


@router.get("/health")
async def health_check():
    """Health check endpoint to verify the chat service is running."""
    try:
        generator = get_generator()
        return {
            "status": "healthy",
            "service": "property-chat-api",
            "model": generator.model_name,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Service unhealthy: {str(e)}"
        )

