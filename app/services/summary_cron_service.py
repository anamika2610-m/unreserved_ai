"""
Cron Job Service for Generating Listing Summaries

Runs nightly to generate property-level chat summaries for listings.
Only generates summaries if a complete week has passed since the last summary.
Focuses on property features and desired features from user queries.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.db.connection import get_session_maker
from app.db.postgres.repositories.listing_summary_repository import ListingSummaryRepository
from app.db.postgres.repositories.conversation_repository import ConversationRepository
from app.db.postgres.repositories.listing_repository import ListingRepository
from app.services.chat_summary_service import ChatSummaryService


class SummaryCronService:
    """
    Service for running nightly summary generation cron jobs.
    """

    def __init__(self):
        """Initialize the cron service."""
        self.summary_service = ChatSummaryService()

    def should_generate_summary(
        self,
        last_summary_date: Optional[datetime],
        days_required: int = 7
    ) -> bool:
        """
        Check if a summary should be generated based on time elapsed.
        
        A summary should be generated if:
        - No summary exists yet (last_summary_date is None), OR
        - A complete week (7 days) has passed since last summary
        
        Args:
            last_summary_date: Date of last summary or None
            days_required: Number of days required before generating new summary (default: 7)
            
        Returns:
            True if summary should be generated, False otherwise
        """
        if last_summary_date is None:
            return True
        
        now = datetime.now(timezone.utc)
        if last_summary_date.tzinfo is None:
            last_summary_date = last_summary_date.replace(tzinfo=timezone.utc)
        days_since_last = (now - last_summary_date).days
        return days_since_last >= days_required

    async def get_listings_to_summarize(
        self,
        db_session,
        days_required: int = 7
    ) -> List[UUID]:
        """
        Get list of listing IDs that need summary generation.
        
        A listing needs a summary if:
        - It has user queries, AND
        - Either no summary exists OR a complete week has passed since last summary
        
        Args:
            db_session: Async database session
            days_required: Number of days required before generating new summary
            
        Returns:
            List of listing IDs that need summaries
        """
        summary_repo = ListingSummaryRepository(db_session)
        conversation_repo = ConversationRepository(db_session)
        
        from sqlalchemy import select, distinct
        from app.db.models.conversation import Conversation
        
        # Include all listings that have any conversation (active or inactive) so we don't skip
        # listings whose conversations have gone inactive after 10 days
        query = select(distinct(Conversation.listing_id)).where(
            Conversation.listing_id.isnot(None)
        )
        result = await db_session.execute(query)
        all_listing_ids = [row[0] for row in result.fetchall() if row[0]]
        
        listings_to_summarize = []
        for listing_id in all_listing_ids:
            last_summary_date = await summary_repo.get_last_summary_date(listing_id)
            
            if self.should_generate_summary(last_summary_date, days_required):
                user_messages = await conversation_repo.get_listing_user_messages(
                    listing_id=listing_id,
                    limit_per_conversation=50,
                    active_only=False,
                )
                
                if user_messages:
                    listings_to_summarize.append(listing_id)
        
        return listings_to_summarize

    async def generate_summary_for_listing(
        self,
        db_session,
        listing_id: UUID,
    ) -> Dict[str, Any]:
        """
        Generate summary for a single listing.
        
        Args:
            db_session: Async database session
            listing_id: Listing ID to generate summary for
            
        Returns:
            Dictionary with summary generation results
        """
        try:
            summary_repo = ListingSummaryRepository(db_session)
            conversation_repo = ConversationRepository(db_session)
            listing_repo = ListingRepository(db_session)
            summary_service = ChatSummaryService()
            
            property_title = None
            try:
                listing = await listing_repo.get_by_id(listing_id)
                if listing:
                    property_title = getattr(listing, 'slug', None) or str(listing_id)
            except:
                pass
            
            user_messages = await conversation_repo.get_listing_user_messages(
                listing_id=listing_id,
                limit_per_conversation=100,
                active_only=False,
            )
            
            if not user_messages:
                return {
                    "listing_id": str(listing_id),
                    "status": "skipped",
                    "reason": "No user messages found",
                }
            
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
            
            return {
                "listing_id": str(listing_id),
                "status": "success",
                "summary_length": len(summary),
                "total_queries": analysis["total_queries"],
                "unique_users_estimate": analysis["unique_users"],
            }
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"❌ Error generating summary for listing {listing_id}: {type(e).__name__}: {str(e)}")
            print(f"Full traceback:\n{error_details}")
            
            return {
                "listing_id": str(listing_id),
                "status": "error",
                "error": str(e),
            }

    async def run_nightly_summary_job(
        self,
        days_required: int = 7,
        max_listings: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Run the nightly summary generation job.
        
        This should be called by a cron job every night.
        It will:
        1. Find all listings that need summaries (complete week has passed)
        2. Generate summaries for each listing
        3. Save summaries to database
        
        Args:
            days_required: Number of days required before generating new summary (default: 7)
            max_listings: Maximum number of listings to process (None = all)
            
        Returns:
            Dictionary with job execution results
        """
        session_maker = get_session_maker()
        results = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "days_required": days_required,
            "listings_processed": 0,
            "listings_succeeded": 0,
            "listings_failed": 0,
            "listings_skipped": 0,
            "results": [],
        }
        
        async with session_maker() as db_session:
            try:
                listings_to_summarize = await self.get_listings_to_summarize(
                    db_session,
                    days_required=days_required
                )
                
                if max_listings:
                    listings_to_summarize = listings_to_summarize[:max_listings]
                
                print(f"📊 Found {len(listings_to_summarize)} listings that need summaries")
                
                for listing_id in listings_to_summarize:
                    result = await self.generate_summary_for_listing(db_session, listing_id)
                    results["results"].append(result)
                    results["listings_processed"] += 1
                    
                    if result["status"] == "success":
                        results["listings_succeeded"] += 1
                    elif result["status"] == "skipped":
                        results["listings_skipped"] += 1
                    else:
                        results["listings_failed"] += 1
                    
                    print(f"   {'✅' if result['status'] == 'success' else '⚠️' if result['status'] == 'skipped' else '❌'} Listing {listing_id}: {result['status']}")
                
                results["completed_at"] = datetime.now(timezone.utc).isoformat()
                results["duration_seconds"] = (
                    datetime.fromisoformat(results["completed_at"]) -
                    datetime.fromisoformat(results["started_at"])
                ).total_seconds()
                
                print(f"✅ Summary job completed: {results['listings_succeeded']} succeeded, {results['listings_skipped']} skipped, {results['listings_failed']} failed")
                
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                print(f"❌ Error in nightly summary job: {type(e).__name__}: {str(e)}")
                print(f"Full traceback:\n{error_details}")
                results["error"] = str(e)
        
        return results


if __name__ == "__main__":
    import asyncio
    service = SummaryCronService()
    result = asyncio.run(service.run_nightly_summary_job())
    print(result)
