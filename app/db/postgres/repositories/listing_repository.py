"""
Repository for property listing database operations.
Handles fetching listings with all related data (property attributes, agents, media, etc.)
"""
import logging
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError


class ListingRepository:
    """
    Repository for property listing operations.
    Handles complex queries with multiple joins for listing data.
    """
    
    def __init__(self, session: AsyncSession):
        """
        Initialize repository with database session.
        
        Args:
            session: Async SQLAlchemy database session
        """
        self.session = session
    
    @asynccontextmanager
    async def _handle_errors(self):
        """
        Async context manager for automatic error handling and rollback.
        
        Usage:
            async with self._handle_errors():
                # database operations
        """
        try:
            yield
        except SQLAlchemyError as e:
            await self.session.rollback()
            raise e
    
    async def _execute_query(
        self,
        query_str: str,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a SQL query and return results as list of dictionaries.
        
        Args:
            query_str: SQL query string
            params: Optional query parameters
            
        Returns:
            List of row dictionaries
        """
        async with self._handle_errors():
            result = await self.session.execute(text(query_str), params or {})
            rows = result.fetchall()
            try:
                await self.session.commit()
            except Exception:
                pass
            return [dict(row._mapping) for row in rows]
    
    async def _execute_query_one(
        self,
        query_str: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Execute a SQL query and return single result as dictionary.
        
        Args:
            query_str: SQL query string
            params: Optional query parameters
            
        Returns:
            Row dictionary or None if no result
        """
        async with self._handle_errors():
            result = await self.session.execute(text(query_str), params or {})
            row = result.fetchone()
            try:
                await self.session.commit()
            except Exception:
                pass
            return dict(row._mapping) if row else None
    
    async def fetch_listings(
        self,
        listing_ids: Optional[List[str]] = None,
        listing_status: str = "active",
        suburb: Optional[str] = None,
        exclude_listing_ids: Optional[List[str]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch property listings from database using actual Prisma schema.
        
        Args:
            listing_ids: Optional list of specific listing IDs to fetch
            listing_status: Filter by listing status (default: 'active')
            limit: Maximum number of listings to fetch
            
        Returns:
            List of formatted listing dictionaries ready for chunking
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
        
        params = {}
        
        if listing_ids:
            query += " AND l.id = ANY(:listing_ids)"
            params['listing_ids'] = listing_ids
        
        if listing_status:
            query += " AND l.listing_status = :listing_status"
            params['listing_status'] = listing_status
        
        if suburb:
            query += " AND LOWER(TRIM(loc.suburb)) = LOWER(TRIM(:suburb))"
            params['suburb'] = suburb
        
        if exclude_listing_ids:
            query += " AND l.id != ALL(:exclude_listing_ids)"
            params['exclude_listing_ids'] = exclude_listing_ids
        
        query += " ORDER BY l.published_at DESC"
        
        if limit:
            query += " LIMIT :limit"
            params['limit'] = limit
        
        rows = await self._execute_query(query, params)
        
        listings = []
        for row_dict in rows:
            from app.helpers.ingestion_pipeline.property.formatters import format_listing_for_chunking
            formatted_listing = format_listing_for_chunking(row_dict)
            listings.append(formatted_listing)
        
        return listings
    
    async def _fetch_amenities(self, property_id: str) -> List[Dict[str, Any]]:
        """
        Fetch amenities for a property.
        
        Args:
            property_id: Property ID
            
        Returns:
            List of amenity dictionaries
        """
        query = """
            SELECT a.id, a.name, a.icon
            FROM property_amenities pa
            JOIN amenities a ON pa.amenity_id = a.id
            WHERE pa.property_id = :property_id
        """
        return await self._execute_query(query, {"property_id": property_id})
    
    async def _fetch_inspections(self, listing_id: str) -> List[Dict[str, Any]]:
        """
        Fetch inspection times for a listing.
        
        Args:
            listing_id: Listing ID
            
        Returns:
            List of inspection dictionaries
        """
        # listing_inspections: id, listing_id, inspection_start_time, inspection_end_time,
        # inspection_type, is_active, created_at, updated_at, total_inspection_count
        query = """
            SELECT 
                id,
                inspection_type as "inspectionType",
                (inspection_start_time::date)::text as "inspectionDate",
                inspection_start_time as "inspectionStartTime",
                inspection_end_time as "inspectionEndTime",
                (NOT is_active) as "isCancelled"
            FROM listing_inspections
            WHERE listing_id = :listing_id
            ORDER BY inspection_start_time ASC
        """
        return await self._execute_query(query, {"listing_id": listing_id})
    
    async def _fetch_agents(self, listing_id: str) -> List[Dict[str, Any]]:
        """
        Fetch agents for a listing.
        
        Args:
            listing_id: Listing ID
            
        Returns:
            List of agent dictionaries
        """
        query = """
            SELECT 
                u.id,
                u.full_name as "fullName",
                u.email,
                u.phone,
                u.avatar,
                u.is_verified as "isVerified"
            FROM property_agents pa
            JOIN users u ON pa.user_id = u.id
            WHERE pa.listing_id = :listing_id
        """
        return await self._execute_query(query, {"listing_id": listing_id})
    
    async def _fetch_highest_bid(self, listing_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch highest bid for an auction listing.
        
        Args:
            listing_id: Listing ID
            
        Returns:
            Highest bid dictionary or None
        """
        query = """
            SELECT 
                ab.id,
                ab.bid_amount as "bidAmount",
                ab.bid_type as "bidType",
                ab.created_at as "createdAt"
            FROM listing_auction_bids lab
            JOIN auction_bids ab ON lab.bid_id = ab.id
            WHERE lab.listing_id = :listing_id
            ORDER BY ab.bid_amount DESC
            LIMIT 1
        """
        return await self._execute_query_one(query, {"listing_id": listing_id})
    
    async def _fetch_sales_history(self, property_id: str) -> List[Dict[str, Any]]:
        """
        Fetch sales history for a property.
        
        Args:
            property_id: Property ID
            
        Returns:
            List of sales history dictionaries
        """
        query = """
            SELECT 
                id,
                sale_date as "saleDate",
                sale_price as "salePrice",
                sale_method as "saleMethod"
            FROM sales_history
            WHERE property_id = :property_id
            ORDER BY sale_date DESC
        """
        return await self._execute_query(query, {"property_id": property_id})
    
    async def _fetch_offers(self, listing_id: str) -> List[Dict[str, Any]]:
        """
        Fetch offers for a listing.
        
        Args:
            listing_id: Listing ID
            
        Returns:
            List of offer dictionaries
        """
        query = """
            SELECT 
                id,
                offer_amount as "offerAmount",
                offer_status as "offerStatus",
                created_at as "createdAt"
            FROM offers
            WHERE listing_id = :listing_id
            ORDER BY created_at DESC
        """
        return await self._execute_query(query, {"listing_id": listing_id})
    
    async def _fetch_media(self, property_id: str) -> List[Dict[str, Any]]:
        """
        Fetch media for a property.
        
        Args:
            property_id: Property ID
            
        Returns:
            List of media dictionaries
        """
        query = """
            SELECT 
                mm.id,
                mm.file_url as "fileUrl",
                mm.media_type as "mediaType",
                mm.display_order as "displayOrder"
            FROM property_media pm
            JOIN media_metadata mm ON pm.media_id = mm.id
            WHERE pm.property_id = :property_id
            ORDER BY mm.display_order ASC
        """
        return await self._execute_query(query, {"property_id": property_id})
    
    async def get_listing_hero_image(self, listing_id: str) -> Optional[str]:
        """
        Get the hero image URL (first image by display order) for a listing.
        
        Args:
            listing_id: The listing ID
            
        Returns:
            Image URL string or None if no images found
        """
        query = """
            SELECT mm.file_url as "fileUrl"
            FROM listings l
            JOIN properties p ON l.property_id = p.id
            JOIN property_media pm ON p.id = pm.property_id
            JOIN media_metadata mm ON pm.file_id = mm.id
            WHERE l.id = :listing_id
            AND mm.file_type IN ('jpg', 'jpeg', 'png', 'webp')
            ORDER BY pm.display_order ASC
            LIMIT 1
        """
        result = await self._execute_query_one(query, {"listing_id": listing_id})
        return result.get("fileUrl") if result else None
    
    async def get_multiple_listing_hero_images(self, listing_ids: List[str]) -> Dict[str, str]:
        """
        Get hero image URLs for multiple listings at once.
        
        Args:
            listing_ids: List of listing IDs
            
        Returns:
            Dictionary mapping listing_id to image URL
        """
        if not listing_ids:
            return {}
        
        query = """
            WITH RankedImages AS (
                SELECT 
                    l.id as listing_id,
                    mm.file_url as "fileUrl",
                    ROW_NUMBER() OVER (PARTITION BY l.id ORDER BY pm.display_order ASC) as rn
                FROM listings l
                JOIN properties p ON l.property_id = p.id
                JOIN property_media pm ON p.id = pm.property_id
                JOIN media_metadata mm ON pm.file_id = mm.id
                WHERE l.id = ANY(:listing_ids)
                AND mm.file_type IN ('jpg', 'jpeg', 'png', 'webp')
            )
            SELECT listing_id, "fileUrl"
            FROM RankedImages
            WHERE rn = 1
        """
        results = await self._execute_query(query, {"listing_ids": listing_ids})
        return {row["listing_id"]: row["fileUrl"] for row in results}
    
    async def get_multiple_listing_property_media(self, listing_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get full property media arrays for multiple listings at once.
        
        Args:
            listing_ids: List of listing IDs
            
        Returns:
            Dictionary mapping listing_id to list of property media objects
        """
        if not listing_ids:
            return {}
        
        query = """
            SELECT 
                l.id as listing_id,
                pm.id as pm_id,
                pm.display_order as "displayOrder",
                mm.id as mm_id,
                mm.file_name as "fileName",
                mm.file_type as "fileType",
                mm.file_url as "fileUrl",
                mm.alt_text as "altText"
            FROM listings l
            JOIN properties p ON l.property_id = p.id
            JOIN property_media pm ON p.id = pm.property_id
            JOIN media_metadata mm ON pm.file_id = mm.id
            WHERE l.id = ANY(:listing_ids)
            AND mm.file_type IN ('jpg', 'jpeg', 'png', 'webp')
            ORDER BY l.id, pm.display_order ASC
        """
        results = await self._execute_query(query, {"listing_ids": listing_ids})
        
        media_by_listing = {}
        for row in results:
            listing_id = str(row["listing_id"])
            if listing_id not in media_by_listing:
                media_by_listing[listing_id] = []
            
            media_by_listing[listing_id].append({
                "id": str(row["pm_id"]),
                "displayOrder": row["displayOrder"],
                "mediaMetadata": {
                    "id": str(row["mm_id"]),
                    "fileName": row["fileName"],
                    "fileType": row["fileType"],
                    "fileUrl": row["fileUrl"],
                    "altText": row["altText"] or ""
                }
            })
        
        return media_by_listing
    
    async def get_listing_location(self, listing_id: str) -> Optional[Dict[str, Any]]:
        """
        Get location data (latitude, longitude, address, suburb) for a listing.
        Tries: (1) via property (listings -> properties -> locations),
        then (2) via listing's location_id if present (listings -> locations).
        
        Args:
            listing_id: The listing ID (UUID string)
            
        Returns:
            Dictionary with location data or None if not found
        """
        # Path 1: listings -> properties -> locations (standard schema)
        query = """
            SELECT 
                loc.latitude,
                loc.longitude,
                loc.display_address as "displayAddress",
                loc.suburb
            FROM listings l
            LEFT JOIN properties p ON l.property_id = p.id
            LEFT JOIN locations loc ON p.location_id = loc.id
            WHERE l.id::text = :listing_id
        """
        row_dict = await self._execute_query_one(query, {'listing_id': str(listing_id)})
        
        # Path 2: if no row or null lat/lon, try listing -> location directly (some schemas)
        if (not row_dict or row_dict.get('latitude') is None or row_dict.get('longitude') is None):
            try:
                fallback_row = await self._execute_query_one(
                    """
                    SELECT loc.latitude, loc.longitude, loc.display_address as "displayAddress", loc.suburb
                    FROM listings l
                    LEFT JOIN locations loc ON l.location_id = loc.id
                    WHERE l.id::text = :listing_id
                    """,
                    {'listing_id': str(listing_id)}
                )
                if fallback_row and fallback_row.get('latitude') is not None and fallback_row.get('longitude') is not None:
                    row_dict = fallback_row
            except Exception:
                pass

        # Path 3: some schemas store latitude/longitude directly on listings
        if (not row_dict or row_dict.get('latitude') is None or row_dict.get('longitude') is None):
            try:
                direct_row = await self._execute_query_one(
                    """
                    SELECT latitude, longitude, display_address as "displayAddress", suburb
                    FROM listings WHERE id::text = :listing_id
                    """,
                    {'listing_id': str(listing_id)}
                )
                if direct_row and direct_row.get('latitude') is not None and direct_row.get('longitude') is not None:
                    row_dict = direct_row
            except Exception:
                pass

        # Path 4: listings table may use lat/lng or lat/lon column names
        if (not row_dict or row_dict.get('latitude') is None or row_dict.get('longitude') is None):
            try:
                alt_row = await self._execute_query_one(
                    """
                    SELECT lat as latitude, lng as longitude FROM listings WHERE id::text = :listing_id
                    """,
                    {'listing_id': str(listing_id)}
                )
                if alt_row and alt_row.get('latitude') is not None and alt_row.get('longitude') is not None:
                    row_dict = alt_row
            except Exception:
                try:
                    alt_row = await self._execute_query_one(
                        """
                        SELECT lat as latitude, lon as longitude FROM listings WHERE id::text = :listing_id
                        """,
                        {'listing_id': str(listing_id)}
                    )
                    if alt_row and alt_row.get('latitude') is not None and alt_row.get('longitude') is not None:
                        row_dict = alt_row
                except Exception:
                    pass

        if row_dict and (row_dict.get('latitude') is not None and row_dict.get('longitude') is not None):
            lat, lon = row_dict.get('latitude'), row_dict.get('longitude')
            try:
                lat, lon = float(lat), float(lon)
            except (TypeError, ValueError):
                pass
            return {
                'latitude': lat,
                'longitude': lon,
                'displayAddress': row_dict.get('displayAddress'),
                'suburb': row_dict.get('suburb')
            }

        logger = logging.getLogger(__name__)
        logger.debug(
            "get_listing_location: no lat/lon for listing_id=%s (path1 row=%s)",
            listing_id,
            bool(row_dict),
        )
        return None
    
    async def find_nearby_listings(
        self,
        latitude: float,
        longitude: float,
        max_distance_km: float = 15.0,
        exclude_listing_id: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find nearby listings within a distance threshold.
        
        Args:
            latitude: Center point latitude
            longitude: Center point longitude
            max_distance_km: Maximum distance in kilometers
            exclude_listing_id: Listing ID to exclude from results
            limit: Maximum number of results
            
        Returns:
            List of listing dictionaries with distance_km added
        """
        from app.services.rag_pipeline.location_utils import haversine_distance
        
        query_str = """
            SELECT DISTINCT 
                l.id,
                l.property_id as "propertyId",
                p.slug,
                p.title,
                loc.display_address as "displayAddress",
                loc.latitude,
                loc.longitude,
                loc.suburb,
                loc.city,
                loc.state,
                pa.bedrooms,
                pa.bathrooms
            FROM listings l
            LEFT JOIN properties p ON l.property_id = p.id
            LEFT JOIN locations loc ON p.location_id = loc.id
            LEFT JOIN property_attributes pa ON p.id = pa.property_id
            WHERE loc.latitude IS NOT NULL
            AND loc.longitude IS NOT NULL
            AND l.listing_status = 'active'
        """
        
        params = {}
        if exclude_listing_id:
            query_str += " AND l.id::text != :exclude_listing_id"
            params['exclude_listing_id'] = str(exclude_listing_id)
        
        rows = await self._execute_query(query_str, params)
        
        nearby_listings = []
        for row_dict in rows:
            if row_dict.get('latitude') and row_dict.get('longitude'):
                distance = haversine_distance(
                    latitude, longitude,
                    float(row_dict['latitude']), float(row_dict['longitude'])
                )
                
                if distance <= max_distance_km:
                    row_dict['distance_km'] = round(distance, 2)
                    nearby_listings.append(row_dict)
        
        nearby_listings.sort(key=lambda x: x['distance_km'])
        return nearby_listings[:limit]
    
    async def find_same_suburb_listings(
        self,
        suburb: str,
        exclude_listing_id: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find listings in the same suburb.
        
        Args:
            suburb: Suburb name (case-insensitive matching)
            exclude_listing_id: Listing ID to exclude from results
            limit: Maximum number of results
            
        Returns:
            List of listing dictionaries
        """
        query_str = """
            SELECT DISTINCT 
                l.id,
                l.property_id as "propertyId",
                p.slug,
                p.title,
                loc.display_address as "displayAddress",
                loc.latitude,
                loc.longitude,
                loc.suburb,
                loc.city,
                loc.state,
                pa.bedrooms,
                pa.bathrooms
            FROM listings l
            LEFT JOIN properties p ON l.property_id = p.id
            LEFT JOIN locations loc ON p.location_id = loc.id
            LEFT JOIN property_attributes pa ON p.id = pa.property_id
            WHERE LOWER(TRIM(loc.suburb)) = LOWER(TRIM(:suburb))
            AND l.listing_status = 'active'
        """
        
        params = {'suburb': suburb}
        if exclude_listing_id:
            query_str += " AND l.id::text != :exclude_listing_id"
            params['exclude_listing_id'] = str(exclude_listing_id)
        
        if limit:
            query_str += " LIMIT :limit"
            params['limit'] = limit
        
        return await self._execute_query(query_str, params)
    
    async def fetch_property_documents(
        self,
        listing_id: str
    ) -> List[Dict[str, Any]]:
        """
        Fetch PUBLIC PDF documents for a listing from database.
        
        Args:
            listing_id: Listing ID to fetch documents for
            
        Returns:
            List of document dictionaries matching the propertyDocuments structure
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
            AND mm.is_private = false
            ORDER BY pm.display_order
        """
        
        rows = await self._execute_query(query_str, {'listing_id': listing_id})
        
        documents = []
        for row_dict in rows:
            documents.append({
                "id": row_dict.get('id'),
                "displayOrder": row_dict.get('displayOrder'),
                "mediaMetadata": {
                    "id": row_dict.get('metadataId'),
                    "fileName": row_dict.get('fileName'),
                    "fileUrl": row_dict.get('fileUrl'),
                    "fileType": row_dict.get('fileType'),
                    "altText": row_dict.get('altText')
                }
            })
        
        return documents
