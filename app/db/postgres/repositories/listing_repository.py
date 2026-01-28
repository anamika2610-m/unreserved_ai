"""
Repository for property listing database operations.
Handles fetching listings with all related data (property attributes, agents, media, etc.)
"""
from contextlib import contextmanager
from typing import List, Dict, Any, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError


class ListingRepository:
    """
    Repository for property listing operations.
    Handles complex queries with multiple joins for listing data.
    """
    
    def __init__(self, session: Session):
        """
        Initialize repository with database session.
        
        Args:
            session: SQLAlchemy database session
        """
        self.session = session
    
    @contextmanager
    def _handle_errors(self):
        """
        Context manager for automatic error handling and rollback.
        
        Usage:
            with self._handle_errors():
                # database operations
        """
        try:
            yield
        except SQLAlchemyError as e:
            self.session.rollback()
            raise e
    
    def _execute_query(
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
        with self._handle_errors():
            result = self.session.execute(text(query_str), params or {})
            rows = result.fetchall()
            return [dict(row._mapping) for row in rows]
    
    def _execute_query_one(
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
        with self._handle_errors():
            result = self.session.execute(text(query_str), params or {})
            row = result.fetchone()
            return dict(row._mapping) if row else None
    
    def fetch_listings(
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
        # Build the comprehensive query matching the schema mapping
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
        
        # Apply filters
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
        
        # Add ordering
        query += " ORDER BY l.published_at DESC"
        
        # Add limit
        if limit:
            query += " LIMIT :limit"
            params['limit'] = limit
        
        # Execute query
        rows = self._execute_query(query, params)
        
        listings = []
        for row_dict in rows:
            # NOTE: For now we only use core listing + joined property/location fields.
            # Related collections (amenities, inspections, agents, bids, sales history,
            # offers, media) are not fetched here to avoid schema mismatches.
            # The formatter will handle missing optional fields gracefully.
            
            # Format listing for chunking (lazy import to avoid circular dependency)
            from app.helpers.ingestion_pipeline.property.formatters import format_listing_for_chunking
            formatted_listing = format_listing_for_chunking(row_dict)
            listings.append(formatted_listing)
        
        return listings
    
    def _fetch_amenities(self, property_id: str) -> List[Dict[str, Any]]:
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
        return self._execute_query(query, {"property_id": property_id})
    
    def _fetch_inspections(self, listing_id: str) -> List[Dict[str, Any]]:
        """
        Fetch inspection times for a listing.
        
        Args:
            listing_id: Listing ID
            
        Returns:
            List of inspection dictionaries
        """
        query = """
            SELECT 
                id,
                inspection_date as "inspectionDate",
                inspection_start_time as "inspectionStartTime",
                inspection_end_time as "inspectionEndTime",
                is_cancelled as "isCancelled"
            FROM listing_inspections
            WHERE listing_id = :listing_id
            ORDER BY inspection_date ASC
        """
        return self._execute_query(query, {"listing_id": listing_id})
    
    def _fetch_agents(self, listing_id: str) -> List[Dict[str, Any]]:
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
        return self._execute_query(query, {"listing_id": listing_id})
    
    def _fetch_highest_bid(self, listing_id: str) -> Optional[Dict[str, Any]]:
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
        return self._execute_query_one(query, {"listing_id": listing_id})
    
    def _fetch_sales_history(self, property_id: str) -> List[Dict[str, Any]]:
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
        return self._execute_query(query, {"property_id": property_id})
    
    def _fetch_offers(self, listing_id: str) -> List[Dict[str, Any]]:
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
        return self._execute_query(query, {"listing_id": listing_id})
    
    def _fetch_media(self, property_id: str) -> List[Dict[str, Any]]:
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
        return self._execute_query(query, {"property_id": property_id})
    
    def get_listing_hero_image(self, listing_id: str) -> Optional[str]:
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
        result = self._execute_query_one(query, {"listing_id": listing_id})
        return result.get("fileUrl") if result else None
    
    def get_multiple_listing_hero_images(self, listing_ids: List[str]) -> Dict[str, str]:
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
        results = self._execute_query(query, {"listing_ids": listing_ids})
        return {row["listing_id"]: row["fileUrl"] for row in results}
    
    def get_multiple_listing_property_media(self, listing_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
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
        results = self._execute_query(query, {"listing_ids": listing_ids})
        
        # Group by listing_id (convert to string for consistency)
        media_by_listing = {}
        for row in results:
            listing_id = str(row["listing_id"])  # Convert UUID to string
            if listing_id not in media_by_listing:
                media_by_listing[listing_id] = []
            
            media_by_listing[listing_id].append({
                "id": str(row["pm_id"]),  # Convert UUID to string
                "displayOrder": row["displayOrder"],
                "mediaMetadata": {
                    "id": str(row["mm_id"]),  # Convert UUID to string
                    "fileName": row["fileName"],
                    "fileType": row["fileType"],
                    "fileUrl": row["fileUrl"],
                    "altText": row["altText"] or ""
                }
            })
        
        return media_by_listing
    
    def get_listing_location(self, listing_id: str) -> Optional[Dict[str, Any]]:
        """
        Get location data (latitude, longitude, address, suburb) for a listing.
        
        Args:
            listing_id: The listing ID
            
        Returns:
            Dictionary with location data or None if not found
        """
        query = """
            SELECT 
                loc.latitude,
                loc.longitude,
                loc.display_address as "displayAddress",
                loc.suburb
            FROM listings l
            LEFT JOIN properties p ON l.property_id = p.id
            LEFT JOIN locations loc ON p.location_id = loc.id
            WHERE l.id = :listing_id
        """
        
        row_dict = self._execute_query_one(query, {'listing_id': listing_id})
        
        if row_dict:
            return {
                'latitude': row_dict.get('latitude'),
                'longitude': row_dict.get('longitude'),
                'displayAddress': row_dict.get('displayAddress'),
                'suburb': row_dict.get('suburb')
            }
        return None
    
    def find_nearby_listings(
        self,
        latitude: float,
        longitude: float,
        max_distance_km: float = 15.0,
        exclude_listing_id: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find nearby listings within a distance threshold.
        Note: This calculates distance in Python using Haversine formula.
        For better performance with large datasets, consider using PostGIS.
        
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
        
        # Build query as string first, then convert to text()
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
        
        rows = self._execute_query(query_str, params)
        
        # Calculate distances and filter
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
        
        # Sort by distance and limit
        nearby_listings.sort(key=lambda x: x['distance_km'])
        return nearby_listings[:limit]
    
    def find_same_suburb_listings(
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
        # Build query as string first, then convert to text()
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
        
        return self._execute_query(query_str, params)
    
    def fetch_property_documents(
        self,
        listing_id: str
    ) -> List[Dict[str, Any]]:
        """
        Fetch PUBLIC PDF documents for a listing from database.
        
        This method retrieves property documents from the property_media table where:
        - category is 'floor_plan' or 'other' (documents, not 'photo')
        - is_public = true (only public documents)
        - file_type = 'pdf' (only PDF files, not images)
        
        Args:
            listing_id: Listing ID to fetch documents for
            
        Returns:
            List of document dictionaries matching the propertyDocuments structure:
            [
                {
                    "id": "uuid",
                    "displayOrder": 1,
                    "mediaMetadata": {
                        "id": "uuid",
                        "fileName": "floor_plan.pdf",
                        "fileUrl": "https://...",
                        "fileType": "pdf",
                        "altText": "Property floor plan"
                    }
                }
            ]
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
        
        rows = self._execute_query(query_str, {'listing_id': listing_id})
        
        # Format to match propertyDocuments structure
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

