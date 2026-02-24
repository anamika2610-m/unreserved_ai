"""
Admin API endpoints for property management and analytics.
Includes property-level chat summaries and other administrative features.
"""

# Import config to ensure environment variables are set
import app.config  # noqa: F401

from fastapi import APIRouter, Depends, Request

from app.core.exceptions import InternalServerError
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limiter import rate_limit
from app.db.connection import get_db
from app.db.postgres.repositories.conversation_repository import ConversationRepository
from app.db.models.cron_job_run import CronJobRun


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
    db: AsyncSession = Depends(get_db),
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
        existing_summary = await summary_repo.get_by_listing_id(listing_id)
        if existing_summary and existing_summary.summary:
            user_messages = await conversation_repo.get_listing_user_messages(
                listing_id=listing_id,
                limit_per_conversation=50,
            )
            analysis = summary_service.analyze_conversations(user_messages)
            
            property_title = None
            try:
                listing = await listing_repo.get_by_id(listing_id)
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
        property_title = None
        try:
            listing = await listing_repo.get_by_id(listing_id)
            if listing:
                property_title = getattr(listing, 'slug', None) or str(listing_id)
        except:
            pass
        
        user_messages = await conversation_repo.get_listing_user_messages(
            listing_id=listing_id,
            limit_per_conversation=50,
        )
        
        analysis = summary_service.analyze_conversations(user_messages)
        
        summary = summary_service.generate_summary(
            listing_id=str(listing_id),
            analysis=analysis,
            property_title=property_title,
        )
        
        await summary_repo.create_or_update(
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
        
        raise InternalServerError(detail=f"Error generating property chat summary: {str(e)}")


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
@rate_limit("10/minute")
async def trigger_summary_generation(
    request: Request,
    days_required: int = 7,
    max_listings: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
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
        results = await cron_service.run_nightly_summary_job(
            days_required=days_required,
            max_listings=max_listings
        )

        run = CronJobRun(
            job_name="chat_summary",
            ran_at=datetime.now(timezone.utc),
            status="200",
            message=None,
        )
        db.add(run)
        await db.commit()

        return SummaryJobResponse(**results)

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"❌ Error in summary generation job: {type(e).__name__}: {str(e)}")
        print(f"Full traceback:\n{error_details}")

        try:
            run = CronJobRun(
                job_name="chat_summary",
                ran_at=datetime.now(timezone.utc),
                status="500",
                message=str(e)[:500],
            )
            db.add(run)
            await db.commit()
        except Exception:
            pass

        raise InternalServerError(detail=f"Error running summary generation job: {str(e)}")


# ------------------------------------------------------------------------------
# Cron job status (for checking if chat summary cron is running)
# ------------------------------------------------------------------------------
class CronStatusResponse(BaseModel):
    """Response model for cron job status."""
    
    job_name: str = Field(..., description="Name of the cron job")
    schedule: str = Field(..., description="Expected schedule (e.g. daily at 10:00)")
    endpoint: str = Field(..., description="Endpoint that the cron calls")
    ready: bool = Field(..., description="Whether the summary generation endpoint is available")
    last_run_at: Optional[str] = Field(None, description="Last run timestamp (from database)")
    last_run_status: Optional[str] = Field(None, description="Last run HTTP status or outcome")


async def _get_last_cron_run(db: AsyncSession, job_name: str = "chat_summary") -> tuple[Optional[str], Optional[str]]:
    """Read last run from database. Returns (last_run_at_iso, last_run_status)."""
    query = (
        select(CronJobRun)
        .where(CronJobRun.job_name == job_name)
        .order_by(desc(CronJobRun.ran_at))
        .limit(1)
    )
    result = await db.execute(query)
    row = result.scalar_one_or_none()
    if not row:
        return None, None
    ran_at_iso = row.ran_at.isoformat() if row.ran_at.tzinfo else row.ran_at.replace(tzinfo=timezone.utc).isoformat()
    return ran_at_iso, row.status


class CronLastRunRequest(BaseModel):
    """
    Body for POST /cron/last-run. Used by the cron script to report when it ran.
    To fetch last run info, use GET /cron/status instead.
    """
    last_run_at: str = Field(
        ...,
        description="ISO8601 timestamp when the cron ran (e.g. 2026-02-12T11:30:00+0530)",
    )
    status: str = Field(
        ...,
        description="HTTP status from the summary job, e.g. 200 or 500",
    )

    model_config = {"json_schema_extra": {"example": {"last_run_at": "2026-02-12T11:30:00+0530", "status": "200"}}}


@router.post(
    "/cron/last-run",
    response_model=Dict[str, str],
)
async def register_cron_last_run(body: CronLastRunRequest, db: AsyncSession = Depends(get_db)) -> Dict[str, str]:
    """
    **Report** when the cron job last ran (called by external cron script after each run).

    Saves the run to the database so **GET /api/v1/admin/cron/status** returns real-time last run info.
    """
    try:
        ran_at = datetime.fromisoformat(body.last_run_at.replace("Z", "+00:00"))
        if ran_at.tzinfo is None:
            ran_at = ran_at.replace(tzinfo=timezone.utc)
    except Exception:
        ran_at = datetime.now(timezone.utc)
    run = CronJobRun(
        job_name="chat_summary",
        ran_at=ran_at,
        status=body.status,
        message=None,
    )
    db.add(run)
    await db.commit()
    return {"status": "ok", "last_run_at": body.last_run_at}


@router.get(
    "/cron/status",
    response_model=CronStatusResponse,
)
async def get_cron_status(db: AsyncSession = Depends(get_db)) -> CronStatusResponse:
    """
    Real-time cron status: when the chat summary job last ran and its outcome.
    Last run is recorded in the database when:
    - POST /api/v1/admin/summaries/generate runs (success or failure), or
    - POST /api/v1/admin/cron/last-run is called by an external cron script.

    **Schedule:** Daily at 11:20 AM (crontab: 20 11 * * *)
    """
    last_run_at, last_run_status = await _get_last_cron_run(db, job_name="chat_summary")

    return CronStatusResponse(
        job_name="chat_summary",
        schedule="daily at 11:20 AM",
        endpoint="/api/v1/admin/summaries/generate",
        ready=True,
        last_run_at=last_run_at,
        last_run_status=last_run_status,
    )
