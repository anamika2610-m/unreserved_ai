"""
Synchronous repository for property listing database operations.

This is used by ingestion/sync scripts and other synchronous code paths
that cannot use the async `ListingRepository` (which expects AsyncSession).
"""
from typing import List, Dict, Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


class SyncListingRepository:
    """
    Repository for property listing operations using a sync SQLAlchemy session.

    The SQL closely mirrors the async `ListingRepository` so behaviour stays
    consistent across sync/async callers.
    """

    def __init__(self, session: Session):
        self.session = session

    def fetch_listings(
        self,
        listing_ids: Optional[List[str]] = None,
        listing_status: Optional[str] = "active",
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch property listings from database.

        Args:
            listing_ids: Optional list of specific listing IDs to fetch
            listing_status: Optional filter by listing status (e.g. 'active');
                            pass None to disable status filtering.
            limit: Maximum number of listings to fetch

        Returns:
            List of formatted listing dictionaries ready for chunking.
        """
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

        result = self.session.execute(text(query), params)
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

    def fetch_property_documents(self, listing_id: str) -> List[Dict[str, Any]]:
        """
        Fetch PUBLIC PDF documents for a listing from database.

        Mirrors `ListingRepository.fetch_property_documents` but uses
        a synchronous session.

        Args:
            listing_id: Listing ID to fetch documents for

        Returns:
            List of document dictionaries matching the propertyDocuments structure.
        """
        query_str = """
            SELECT 
                pm.id,
                pm.display_order as "displayOrder",
                pm.category,
                mm.id as "metadataId",
                mm.file_name as "fileName",
                mm.file_url as "fileUrl",
                mm.file_type as "fileType",
                mm.alt_text as "altText"
            FROM listings l
            LEFT JOIN properties p ON l.property_id = p.id
            LEFT JOIN property_media pm ON p.id = pm.property_id
            LEFT JOIN media_metadata mm ON pm.file_id = mm.id
            WHERE l.id = :listing_id
            AND pm.category IN ('floor_plan', 'other')
            AND pm.is_public = true
            AND mm.file_type = 'pdf'
            ORDER BY pm.display_order
        """

        result = self.session.execute(text(query_str), {"listing_id": listing_id})
        rows = result.fetchall()

        documents: List[Dict[str, Any]] = []
        for row in rows:
            row_dict = dict(row._mapping)
            documents.append(
                {
                    "id": row_dict.get("id"),
                    "displayOrder": row_dict.get("displayOrder"),
                    "mediaMetadata": {
                        "id": row_dict.get("metadataId"),
                        "fileName": row_dict.get("fileName"),
                        "fileUrl": row_dict.get("fileUrl"),
                        "fileType": row_dict.get("fileType"),
                        "altText": row_dict.get("altText"),
                    },
                }
            )

        return documents

