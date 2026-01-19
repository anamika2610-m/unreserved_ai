"""
Database loader module for fetching property listings directly from PostgreSQL.
This module now uses the Repository Pattern for database access.

All database operations have been moved to ListingRepository.
"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.postgres.repositories import ListingRepository


def fetch_listings_from_db(
    db: Optional[Session] = None,
    listing_ids: Optional[List[str]] = None,
    listing_status: str = "active",
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Fetch property listings from database using Repository Pattern.
    
    Args:
        db: Database session (creates new one if not provided)
        listing_ids: Optional list of specific listing IDs to fetch
        listing_status: Filter by listing status (default: 'active')
        limit: Maximum number of listings to fetch
        
    Returns:
        List of formatted listing dictionaries ready for chunking
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    
    try:
        # Use repository for database operations
        listing_repo = ListingRepository(db)
        listings = listing_repo.fetch_listings(
            listing_ids=listing_ids,
            listing_status=listing_status,
            limit=limit
        )
        return listings
    finally:
        if close_db:
            db.close()
