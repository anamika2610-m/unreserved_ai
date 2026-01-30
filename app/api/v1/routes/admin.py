"""
Admin API endpoints for property management and analytics.
Includes property-level chat summaries and other administrative features.
"""

# Import config to ensure environment variables are set
import app.config  # noqa: F401

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID

from app.db.session import get_db
from app.db.postgres.repositories.conversation_repository import ConversationRepository
from sqlalchemy.orm import Session


# ------------------------------------------------------------------------------
# Router
# ------------------------------------------------------------------------------
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ------------------------------------------------------------------------------
# Property-Level Chat Summary Endpoint
# ------------------------------------------------------------------------------
class PropertySummaryResponse(BaseModel):
    """Response model for property-level chat summary."""
    
    listing_id: str = Field(..., description="Listing ID")
    property_title: Optional[str] = Field(None, description="Property title")
    summary: str = Field(..., description="Generated summary of user queries and themes")
    analysis: Dict[str, Any] = Field(
        ...,
        description="Detailed analysis including query counts, categories, and patterns"
    )
    generated_at: str = Field(..., description="Timestamp when summary was generated")
    total_queries: int = Field(..., description="Total number of user queries analyzed")
    unique_users_estimate: int = Field(..., description="Estimated number of unique users")


@router.get(
    "/listings/{listing_id}/summary",
    response_model=PropertySummaryResponse,
)
async def get_property_chat_summary(
    listing_id: UUID,
    db: Session = Depends(get_db),
) -> PropertySummaryResponse:
    """
    Get a property-level chat summary for administrators.
    
    This endpoint aggregates all conversations for a specific listing and generates
    a high-level summary of common user queries, themes, and buyer interest patterns.
    Individual user conversations are not exposed - only aggregate patterns.
    
    **Admin Use Cases:**
    - Identify frequently asked questions about a property
    - Understand buyer interest patterns (pricing, amenities, location, etc.)
    - Identify information gaps that need clarification
    - Track engagement levels for listings
    
    **Privacy:**
    - No user IDs or individual conversation details are included
    - Only aggregate statistics and patterns are returned
    - Summary focuses on themes, not specific user interactions
    
    Args:
        listing_id: Listing ID (UUID)
        
    Returns:
        PropertySummaryResponse with:
        - summary: Natural language summary of buyer interest patterns
        - analysis: Detailed breakdown of query categories, frequencies, etc.
        - total_queries: Total number of queries analyzed
        - unique_users_estimate: Estimated number of unique users
    """
    try:
        from app.services.chat_summary_service import ChatSummaryService
        from app.db.postgres.repositories.listing_repository import ListingRepository
        from app.db.postgres.repositories.listing_summary_repository import ListingSummaryRepository
        
        conversation_repo = ConversationRepository(db)
        listing_repo = ListingRepository(db)
        summary_repo = ListingSummaryRepository(db)
        summary_service = ChatSummaryService()
        
        # Check if summary exists in database
        existing_summary = summary_repo.get_by_listing_id(listing_id)
        if existing_summary and existing_summary.summary:
            # Return existing summary from database
            # Note: We still need to generate analysis for the response
            user_messages = conversation_repo.get_listing_user_messages(
                listing_id=listing_id,
                limit_per_conversation=50,
            )
            analysis = summary_service.analyze_conversations(user_messages)
            
            # Get property title
            property_title = None
            try:
                listing = listing_repo.get_by_id(listing_id)
                if listing:
                    property_title = getattr(listing, 'slug', None) or str(listing_id)
            except:
                pass
            
            return PropertySummaryResponse(
                listing_id=str(listing_id),
                property_title=property_title,
                summary=existing_summary.summary,
                analysis=analysis,
                generated_at=existing_summary.last_summarised_at.isoformat() if existing_summary.last_summarised_at else datetime.utcnow().isoformat(),
                total_queries=analysis["total_queries"],
                unique_users_estimate=analysis["unique_users"],
            )
        
        # Generate new summary if not in database
        # Get property title (optional, for context)
        property_title = None
        try:
            listing = listing_repo.get_by_id(listing_id)
            if listing:
                # Try to get property title from listing or property data
                # This depends on your listing model structure
                property_title = getattr(listing, 'slug', None) or str(listing_id)
        except:
            pass
        
        # Get all user messages for this listing
        user_messages = conversation_repo.get_listing_user_messages(
            listing_id=listing_id,
            limit_per_conversation=50,  # Limit to prevent excessive data
        )
        
        # Analyze conversations
        analysis = summary_service.analyze_conversations(user_messages)
        
        # Generate summary using LLM
        summary = summary_service.generate_summary(
            listing_id=str(listing_id),
            analysis=analysis,
            property_title=property_title,
        )
        
        # Save to database
        summary_repo.create_or_update(
            listing_id=listing_id,
            summary=summary,
            analysis=analysis,
        )
        
        return PropertySummaryResponse(
            listing_id=str(listing_id),
            property_title=property_title,
            summary=summary,
            analysis=analysis,
            generated_at=datetime.utcnow().isoformat(),
            total_queries=analysis["total_queries"],
            unique_users_estimate=analysis["unique_users"],
        )
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"❌ Error generating property summary: {type(e).__name__}: {str(e)}")
        print(f"Full traceback:\n{error_details}")
        
        raise HTTPException(
            status_code=500,
            detail=f"Error generating property chat summary: {str(e)}",
        )


# ------------------------------------------------------------------------------
# Summary Generation Cron Job Endpoint
# ------------------------------------------------------------------------------
class SummaryJobResponse(BaseModel):
    """Response model for summary generation job."""
    
    started_at: str = Field(..., description="Job start timestamp")
    completed_at: Optional[str] = Field(None, description="Job completion timestamp")
    days_required: int = Field(..., description="Days required before generating new summary")
    listings_processed: int = Field(..., description="Number of listings processed")
    listings_succeeded: int = Field(..., description="Number of listings with successful summaries")
    listings_failed: int = Field(..., description="Number of listings that failed")
    listings_skipped: int = Field(..., description="Number of listings skipped")
    results: List[Dict[str, Any]] = Field(..., description="Detailed results for each listing")
    duration_seconds: Optional[float] = Field(None, description="Job duration in seconds")
    error: Optional[str] = Field(None, description="Error message if job failed")


@router.post(
    "/summaries/generate",
    response_model=SummaryJobResponse,
)
async def trigger_summary_generation(
    days_required: int = 7,
    max_listings: Optional[int] = None,
    db: Session = Depends(get_db),
) -> SummaryJobResponse:
    """
    Trigger summary generation for listings that need summaries.
    
    This endpoint can be called manually or by a cron job.
    It will generate summaries for listings where:
    - A complete week (7 days) has passed since last summary, OR
    - No summary exists yet
    
    **Cron Job Usage:**
    - Run this endpoint every night via cron job
    - It will automatically check if a complete week has passed
    - Only generates summaries for listings with user queries
    - Focuses on property features and desired features
    
    **Privacy:**
    - No user IDs or personal information is used
    - Only aggregate query patterns are analyzed
    - Focuses on property features and buyer interest trends
    
    Args:
        days_required: Number of days required before generating new summary (default: 7)
        max_listings: Maximum number of listings to process (None = all)
        
    Returns:
        SummaryJobResponse with job execution results
    """
    try:
        from app.services.summary_cron_service import SummaryCronService
        
        cron_service = SummaryCronService()
        results = cron_service.run_nightly_summary_job(
            days_required=days_required,
            max_listings=max_listings
        )
        
        return SummaryJobResponse(**results)
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"❌ Error in summary generation job: {type(e).__name__}: {str(e)}")
        print(f"Full traceback:\n{error_details}")
        
        raise HTTPException(
            status_code=500,
            detail=f"Error running summary generation job: {str(e)}",
        )
