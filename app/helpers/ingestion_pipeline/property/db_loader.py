"""
Database loader module for fetching property listings directly from PostgreSQL.

This module is used by the ingestion/sync scripts and FastAPI sync endpoints.
It intentionally uses the **sync** SQLAlchemy engine/session so it can be
called from regular (non-async) code.
"""
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.postgres.repositories import SyncListingRepository


def fetch_listings_from_db(
    db: Optional[Session] = None,
    listing_ids: Optional[List[str]] = None,
    listing_status: Optional[str] = "active",
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch property listings from the database using the sync engine.

    Args:
        db: Optional existing sync SQLAlchemy session (if None, a new one is created)
        listing_ids: Optional list of specific listing IDs to fetch
        listing_status: Optional filter by listing status (e.g. 'active').
                        Pass None to disable status filtering.
        limit: Maximum number of listings to fetch

    Returns:
        List of formatted listing dictionaries ready for chunking.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        # Delegate to sync repository layer so ingestion code still goes via a
        # repository abstraction, not raw SQL in scripts.
        repo = SyncListingRepository(db)
        return repo.fetch_listings(
            listing_ids=listing_ids,
            listing_status=listing_status,
            limit=limit,
        )
    finally:
        if close_db:
            db.close()
