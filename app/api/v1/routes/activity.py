"""
API endpoint for getting listing activity metrics (calculated from existing tables).
No tracking endpoints needed - metrics are calculated on-the-fly.
"""
import app.config  # noqa: F401

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from uuid import UUID

from app.db.session import get_db
from app.db.postgres.repositories.listing_activity_repository import ListingActivityRepository
from sqlalchemy.orm import Session


# ------------------------------------------------------------------------------
# Router
# ------------------------------------------------------------------------------
router = APIRouter(prefix="/api/v1/activity", tags=["activity"])


# ------------------------------------------------------------------------------
# Response Models
# ------------------------------------------------------------------------------
class ActivityMetricsResponse(BaseModel):
    """Response model for activity metrics (all 7-day based)."""
    listing_id: str
    enquiries_7d: int
    repeat_buyers_7d: int
    first_inspection_groups_7d: int
    multi_inspection_buyers_7d: int
    contract_requests_7d: int
    genuine_offers_7d: int
    competing_offers_7d: int
    bp_inspections_7d: int
    tone_level: str
    tone_context: str


# ------------------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------------------
@router.get("/metrics/{listing_id}", response_model=ActivityMetricsResponse)
async def get_activity_metrics(
    listing_id: UUID,
    db: Session = Depends(get_db),
):
    """
    Get activity metrics and current tone level for a listing.
    
    Metrics are calculated on-the-fly from existing tables:
    - Enquiries: from chat_messages and conversations
    - Inspections/Contracts/Offers: from their respective tables (if they exist)
    
    This endpoint returns the current metrics and the tone level
    that would be applied to AI responses.
    """
    try:
        from app.services.tone_adaptation_service import ToneAdaptationService
        
        activity_repo = ListingActivityRepository(db)
        tone_service = ToneAdaptationService()
        
        activity_data = activity_repo.get_activity_dict(listing_id)
        
        if not activity_data:
            # Return zero metrics if listing not found
            return ActivityMetricsResponse(
                listing_id=str(listing_id),
                enquiries_7d=0,
                repeat_buyers_7d=0,
                first_inspection_groups_7d=0,
                multi_inspection_buyers_7d=0,
                contract_requests_7d=0,
                genuine_offers_7d=0,
                competing_offers_7d=0,
                bp_inspections_7d=0,
                tone_level="neutral",
                tone_context="",
            )
        
        # Determine tone level
        tone_level, tone_context = tone_service.determine_tone(activity_data)
        
        return ActivityMetricsResponse(
            listing_id=str(listing_id),
            enquiries_7d=activity_data["enquiries_7d"],
            repeat_buyers_7d=activity_data["repeat_buyers_7d"],
            first_inspection_groups_7d=activity_data["first_inspection_groups_7d"],
            multi_inspection_buyers_7d=activity_data["multi_inspection_buyers_7d"],
            contract_requests_7d=activity_data["contract_requests_7d"],
            genuine_offers_7d=activity_data["genuine_offers_7d"],
            competing_offers_7d=activity_data["competing_offers_7d"],
            bp_inspections_7d=activity_data["bp_inspections_7d"],
            tone_level=tone_level.value,
            tone_context=tone_context,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving activity metrics: {str(e)}",
        )
