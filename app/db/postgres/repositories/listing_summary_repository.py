"""
Repository for managing listing summaries.
"""
from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models.listing_summary import ListingSummary
from app.db.postgres.repositories.base_repository import BaseRepository


class ListingSummaryRepository(BaseRepository[ListingSummary]):
    """
    Repository for listing summary management.
    """

    def __init__(self, session: AsyncSession):
        """Initialize repository with ListingSummary model."""
        super().__init__(ListingSummary, session)

    async def get_by_listing_id(self, listing_id: UUID) -> Optional[ListingSummary]:
        """
        Get summary for a specific listing.
        
        Args:
            listing_id: Listing ID
            
        Returns:
            ListingSummary or None
        """
        async with self._handle_errors():
            query = select(ListingSummary).where(
                ListingSummary.listing_id == listing_id
            )
            result = await self.session.execute(query)
            return result.scalar_one_or_none()

    async def create_or_update(
        self,
        listing_id: UUID,
        summary: str,
        analysis: Optional[dict] = None,
    ) -> ListingSummary:
        """
        Create or update summary for a listing.
        
        Args:
            listing_id: Listing ID
            summary: Generated summary text
            analysis: Optional analysis data (stored in summary field as JSON if needed)
            
        Returns:
            Created or updated ListingSummary
        """
        async with self._handle_errors():
            existing = await self.get_by_listing_id(listing_id)
            
            if existing:
                existing.summary = summary
                existing.last_summarised_at = datetime.now(timezone.utc)
                existing.updated_at = datetime.now(timezone.utc)
                await self.session.commit()
                return existing
            else:
                new_summary = ListingSummary(
                    listing_id=listing_id,
                    summary=summary,
                    last_summarised_at=datetime.utcnow(),
                )
                self.session.add(new_summary)
                await self.session.commit()
                return new_summary

    async def get_listings_needing_summary(
        self,
        days_since_last_summary: int = 7,
    ) -> list[UUID]:
        """
        Get list of listing IDs that need summary generation.
        A listing needs a summary if:
        - It doesn't have a summary yet, OR
        - Its last_summarised_at is more than days_since_last_summary days ago
        
        Args:
            days_since_last_summary: Number of days since last summary to trigger regeneration
            
        Returns:
            List of listing IDs that need summaries
        """
        async with self._handle_errors():
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_since_last_summary)
            
            query = select(ListingSummary.listing_id).where(
                (ListingSummary.last_summarised_at.is_(None)) |
                (ListingSummary.last_summarised_at < cutoff_date)
            )
            
            result = await self.session.execute(query)
            return [row[0] for row in result.fetchall()]

    async def get_last_summary_date(self, listing_id: UUID) -> Optional[datetime]:
        """
        Get the last summary date for a listing.
        
        Args:
            listing_id: Listing ID
            
        Returns:
            Last summary date or None
        """
        summary = await self.get_by_listing_id(listing_id)
        return summary.last_summarised_at if summary else None
