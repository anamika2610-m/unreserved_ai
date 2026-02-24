"""
Database loader module for fetching property listings directly from PostgreSQL.

This module is used by the ingestion/sync scripts and FastAPI sync endpoints.
It intentionally uses the **sync** SQLAlchemy engine/session so it can be
called from regular (non-async) code.
"""
from typing import List, Dict, Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import SessionLocal


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
        # Base query (mirrors the async ListingRepository, but using sync session)
        query = """
        SELECT 
            -- Listing fields
            l.id,
            l.property_id as "propertyId",
            l.listing_type as "listingType",
            l.listing_status as "listingStatus",
            l.auction_status as "auctionStatus",
            l.display_price as "displayPrice",
            l.price,
            l.auction_start_price as "auctionStartPrice",
            l.auction_start_date as "auctionStartDate",
            l.reserve_price as "reservePrice",
            p.slug,
            p.title,
            p.description,
            l.published_at as "publishedAt",

            -- Property fields
            p.property_category as "propertyCategory",

            -- Property attributes
            pa.bedrooms,
            pa.bathrooms,
            pa.land_area as "landArea",
            pa.floor_area as "floorArea",
            pa.year_built as "yearBuilt",
            pa.zoning,
            pa.garages,
            pa.ensuites,
            pa.car_ports as "carPorts",
            pa.open_parking_spaces as "openParkingSpace",
            pa.highlights,
            pa.energy_rating as "energyRating",
            pa.frontage,

            -- Property type
            pt.name as "propertyTypeName",

            -- Location
            loc.id as "locationId",
            loc.display_address as "displayAddress",
            loc.street_address as "streetAddress",
            loc.suburb,
            loc.city,
            loc.state,
            loc.country,
            loc.postal_code as "postalCode",
            loc.latitude,
            loc.longitude

        FROM listings l
        LEFT JOIN properties p ON l.property_id = p.id
        LEFT JOIN property_attributes pa ON l.property_attribute_id = pa.id
        LEFT JOIN property_types pt ON p.property_type_id = pt.id
        LEFT JOIN locations loc ON p.location_id = loc.id

        WHERE 1=1
        """

        params: Dict[str, Any] = {}

        if listing_ids:
            query += " AND l.id = ANY(:listing_ids)"
            params["listing_ids"] = listing_ids

        if listing_status:
            query += " AND l.listing_status = :listing_status"
            params["listing_status"] = listing_status

        query += " ORDER BY l.published_at DESC"

        if limit:
            query += " LIMIT :limit"
            params["limit"] = limit

        result = db.execute(text(query), params)
        rows = result.fetchall()

        from app.helpers.ingestion_pipeline.property.formatters import (
            format_listing_for_chunking,
        )

        listings: List[Dict[str, Any]] = []
        for row in rows:
            row_dict = dict(row._mapping)
            formatted = format_listing_for_chunking(row_dict)
            listings.append(formatted)

        return listings
    finally:
        if close_db:
            db.close()
