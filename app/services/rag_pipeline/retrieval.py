"""
Retrieval module for querying the vector store to find relevant property listing information.
SAFE version with strict factual retrieval guarantees.
Includes location-based retrieval for nearby properties and amenities.
Now using pgvector (PostgreSQL native vector storage) instead of ChromaDB.
"""
import logging
import re
import time
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional, Tuple

from app.helpers.ingestion_pipeline.property.pgvector_store import PgVectorStore
from app.services.rag_pipeline.config import (
    DEFAULT_MAX_DISTANCE_KM,
    DEFAULT_MAX_NEARBY_PROPERTIES,
)
from app.services.rag_pipeline.location_utils import (
    detect_location_query,
    get_location_from_chunk,
    get_suburb_from_chunk,
    find_nearby_properties,
    find_same_suburb_properties,
    format_location_info_for_prompt,
    format_nearby_properties_json,
)


logger = logging.getLogger(__name__)


class PropertyRetriever:
    """
    Retrieves relevant property listing information from the vector store.
    """

    PRICE_KEYWORDS = [
        'price', 'cost', 'asking', 'offer', 'how much', 'pricing'
    ]
    
    AMENITY_KEYWORDS = [
        'amenity', 'amenities', 'facilities', 'features', 'pool', 'gym',
        'parking', 'garden', 'balcony', 'theatre', 'theater'
    ]
    
    ATTRIBUTE_KEYWORDS = [
        'bedroom', 'bathroom', 'size', 'area', 'garage', 'sqm',
        'land', 'floor', 'rooms'
    ]
    
    # Queries that need property_document PDFs (trends, comparables, bushfire, etc.). Keep minimal; generation tries PDF as last resort.
    DOCUMENT_KEYWORDS = [
        'market insights', 'market insight', 'insights', 'insight',
        'information provided', 'details provided', 'what information',
        'what details', 'document', 'documents', 'statement', 'report',
        'disclosure', 'vendor statement', 'section 32', 'contract',
        'market', 'knowledge base', 'property knowledge', 'property information',
        # Price/market trends and area context (often in property PDFs)
        'price trend', 'price trends', 'market trend', 'market trends',
        'trends for this area', 'price trends for', 'market trends for',
        # Comparable sales / nearby sold properties → use property_document PDFs
        'nearby properties sold', 'nearby sold', 'properties sold', 'recent sales',
        'recent sale', 'comparable sales', 'comparable sale', 'comparable properties',
        # Property-specific environmental/planning queries (should search property_document PDFs)
        'bushfire', 'bushfire regulations', 'bushfire management', 'bushfire overlay',
        'flood', 'flooding', 'flood regulations', 'flood overlay', 'flood risk',
        # Views/aerial information (often in property PDFs)
        'aerial view', 'aerial', 'bird eye view', 'bird\'s eye', 'birds eye',
        'view', 'views', 'outlook', 'aspect', 'vantage',
        'erosion', 'soil erosion', 'erosion risk', 'coastal erosion',
        'heritage overlay', 'planning overlay', 'zoning overlay',
        'environmental', 'environmental risk', 'environmental hazard'
    ]

    def __init__(
        self,
        vector_store: Optional[PgVectorStore] = None
    ):
        """
        Initialize PropertyRetriever with pgvector store.
        
        Args:
            vector_store: Optional PgVectorStore instance. If None, creates a new one.
        """
        self.vector_store = vector_store or PgVectorStore()
        self._last_timings: Dict[str, float] = {}  # fine-grained timers from last retrieve call
    
    @asynccontextmanager
    async def _get_listing_repository(self):
        """
        Context manager for database session and listing repository.
        
        Yields:
            ListingRepository instance
            
        Example:
            async with self._get_listing_repository() as listing_repo:
                location_data = await listing_repo.get_listing_location(listing_id)
        """
        
        from app.db.postgres.repositories.listing_repository import ListingRepository
        from app.db.connection import get_session_maker
        async_session_maker = get_session_maker()
        async with async_session_maker() as db:
                yield ListingRepository(db)
        
        
    
    async def _get_location_from_database(self, listing_id: str) -> Optional[Tuple[float, float, str]]:   
        """
        Get location (lat, lon, address) from database via repository.

        Args:
            listing_id: Listing ID

        Returns:
            Tuple of (latitude, longitude, address) or None if not found
        """
        try:
            async with self._get_listing_repository() as listing_repo:
                location_data = await listing_repo.get_listing_location(listing_id)
                
                if location_data:
                    lat = location_data.get('latitude')
                    lon = location_data.get('longitude')
                    addr = location_data.get('displayAddress') or ''

                    if lat is not None and lon is not None:
                        location = (float(lat), float(lon), addr)
                        logger.info(
                            "✅ Got location from database: lat=%s, lon=%s, address=%s",
                            lat,
                            lon,
                            addr,
                        )
                        return location
                    logger.warning(
                        "⚠️  Location data in database is None for listing %s",
                        listing_id,
                    )
                else:
                    logger.warning(
                        "⚠️  No location data found for listing %s",
                        listing_id,
                    )
        except Exception as e:
            logger.exception("⚠️  Could not fetch location from database for %s: %s", listing_id, e)
        
        return None
    
    async def _get_suburb_from_database(self, listing_id: str) -> Optional[str]:
        """
        Get suburb from database via repository.

        Args:
            listing_id: Listing ID

        Returns:
            Suburb name or None if not found
        """
        try:
            async with self._get_listing_repository() as listing_repo:
                location_data = await listing_repo.get_listing_location(listing_id)

                if location_data:
                    suburb = location_data.get('suburb')
                    if suburb:
                        logger.info("✅ Got suburb from database: %s", suburb)
                        return suburb
                    logger.warning(
                        "⚠️  Suburb is None in database for listing %s",
                        listing_id,
                    )
                else:
                    logger.warning(
                        "⚠️  No location data found for listing %s",
                        listing_id,
                    )
        except Exception as e:
            logger.exception("⚠️  Could not fetch suburb from database for %s: %s", listing_id, e)
        
        return None
    
    def _convert_listing_to_retrieval_format(
        self,
        listing: Dict[str, Any],
        distance_km: Optional[float] = None,
        same_suburb: bool = False
    ) -> Dict[str, Any]:
        """
        Convert repository listing format to retrieval format.
        
        Args:
            listing: Listing dictionary from repository
            distance_km: Optional distance in km
            same_suburb: Whether this is a same-suburb property
            
        Returns:
            Property dictionary in retrieval format
        """
        return {
            'listing_id': str(listing['id']),
            'distance_km': distance_km,
            'latitude': float(listing['latitude']) if listing.get('latitude') else None,
            'longitude': float(listing['longitude']) if listing.get('longitude') else None,
            'address': listing.get('displayAddress') or '',
            'content': f"{listing.get('title', '')} - {listing.get('slug', '')}",
            'metadata': {
                'listing_id': str(listing['id']),
                'slug': listing.get('slug', ''),
                'title': listing.get('title', ''),
                'displayAddress': listing.get('displayAddress', ''),
                'suburb': listing.get('suburb', ''),
                'city': listing.get('city', ''),
                'state': listing.get('state', ''),
                'bedrooms': listing.get('bedrooms'),
                'bathrooms': listing.get('bathrooms'),
                'latitude': float(listing['latitude']) if listing.get('latitude') else None,
                'longitude': float(listing['longitude']) if listing.get('longitude') else None,
            },
        }
    
    async def _enrich_property_with_chunks(self, property_dict: Dict[str, Any]) -> None:
        """
        Enrich a property dictionary with full listing data from chunks.
        Modifies the property_dict in place.
        
        Args:
            property_dict: Property dictionary to enrich (modified in place)
        """
        prop_listing_id = property_dict['listing_id']
        listing_chunks = self.vector_store.get_by_listing_id(prop_listing_id)
        
        enriched_metadata = property_dict['metadata'].copy()
        enriched_content_parts = [property_dict['content']]
        
        for chunk in listing_chunks:
            chunk_meta = chunk.get('metadata', {})
            chunk_content = chunk.get('content', '')
            
            for key, value in chunk_meta.items():
                if key not in enriched_metadata or enriched_metadata[key] in [None, '', 'N/A']:
                    enriched_metadata[key] = value
            
            if chunk_content and chunk_content not in enriched_content_parts:
                enriched_content_parts.append(chunk_content)
        
        property_dict['metadata'] = enriched_metadata
        property_dict['content'] = ' | '.join(enriched_content_parts[:3])  # Limit to avoid too much
    
    async def _fetch_nearby_properties_from_database(
        self,
        current_lat: float,
        current_lon: float,
        listing_id: str,
        max_distance_km: float,
        max_nearby_properties: int
    ) -> List[Dict[str, Any]]:
        """
        Fetch nearby properties from database via repository.

        Args:
            current_lat: Current latitude
            current_lon: Current longitude
            listing_id: Current listing ID to exclude
            max_distance_km: Maximum distance in km
            max_nearby_properties: Maximum number of properties to return

        Returns:
            List of property dictionaries in retrieval format
        """
        try:
            async with self._get_listing_repository() as listing_repo:
                nearby_listings = await listing_repo.find_nearby_listings(
                    latitude=current_lat,
                    longitude=current_lon,
                    max_distance_km=max_distance_km,
                    exclude_listing_id=listing_id,
                    limit=max_nearby_properties
                )

                properties = []
                for listing in nearby_listings:
                    prop = self._convert_listing_to_retrieval_format(
                        listing,
                        distance_km=listing.get('distance_km', 0.0),
                    )
                    properties.append(prop)

                if properties:
                    logger.info("✅ Found %d nearby properties from database", len(properties))
                    for prop in properties:
                        logger.debug(
                            "   - %s: %s (%s km away)",
                            prop['listing_id'],
                            prop['address'],
                            prop['distance_km'],
                        )

                return properties
        except Exception as e:
            logger.exception("⚠️  Could not fetch nearby properties from database: %s", e)
            return []
    
    async def _fetch_same_suburb_properties_from_database(
        self,
        current_suburb: str,
        listing_id: str,
        max_nearby_properties: int
    ) -> List[Dict[str, Any]]:
        """
        Fetch same-suburb properties from database via repository.

        Args:
            current_suburb: Suburb name
            listing_id: Current listing ID to exclude
            max_nearby_properties: Maximum number of properties to return

        Returns:
            List of property dictionaries in retrieval format
        """
        try:
            async with self._get_listing_repository() as listing_repo:
                same_suburb_listings = await listing_repo.find_same_suburb_listings(
                    suburb=current_suburb,
                    exclude_listing_id=listing_id,
                    limit=max_nearby_properties
                )

                properties = []
                for listing in same_suburb_listings:
                    prop = self._convert_listing_to_retrieval_format(
                        listing,
                        distance_km=None,
                        same_suburb=True,
                    )
                    prop['same_suburb'] = True
                    properties.append(prop)

                if properties:
                    logger.info("✅ Found %d same-suburb properties from database", len(properties))

                return properties
        except Exception as e:
            logger.exception("⚠️  Could not fetch same-suburb properties from database: %s", e)
            return []

    async def retrieve(
        self,
        query: str,
        n_results: int = 5,
        listing_id: Optional[str] = None,
        chunk_types: Optional[List[str]] = None,
        allow_hybrid: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Safe retrieval logic with multi-topic query detection.
        Embeds the query once and reuses the embedding for all vector searches (reduces latency).
        """
        self._last_timings = {}
        t0 = time.perf_counter()
        # Embed query once and reuse for all searches (avoids N embedding API calls)
        emb = self.vector_store.embedding_model.encode([query], convert_to_numpy=False)
        _qe = emb[0] if emb else None
        query_embedding = (_qe.tolist() if _qe is not None and hasattr(_qe, 'tolist') else (list(_qe) if _qe is not None else None))
        self._last_timings["embed_ms"] = (time.perf_counter() - t0) * 1000.0
        t_after_embed = time.perf_counter()

        query_lower = query.lower()
        is_price_query = any(k in query_lower for k in self.PRICE_KEYWORDS)
        is_amenity_query = any(k in query_lower for k in self.AMENITY_KEYWORDS)
        is_attribute_query = any(k in query_lower for k in self.ATTRIBUTE_KEYWORDS)
        is_document_query = any(k in query_lower for k in self.DOCUMENT_KEYWORDS)
        
        topic_count = sum([is_price_query, is_amenity_query, is_attribute_query, is_document_query])
        is_multi_topic = topic_count > 1

        # When caller explicitly requests a single chunk type (e.g. property_document only), respect it
        # so PDF-only callers get only PDF chunks instead of a mix with pricing/overview.
        if chunk_types and len(chunk_types) == 1:
            is_multi_topic = False

        if is_multi_topic and listing_id:
            results = []
            seen_ids = set()
            
            target_chunk_types = []
            if is_price_query:
                target_chunk_types.append('pricing')
            if is_amenity_query:
                # Amenity queries should search both amenities chunk AND property_document PDFs
                # Property PDFs often contain nearby school/hospital information
                target_chunk_types.extend(['amenities', 'property_document'])
            if is_attribute_query:
                # Attribute queries should search specifications chunk (bedrooms, bathrooms, land area, etc.)
                target_chunk_types.extend(['specifications', 'overview'])
            if is_document_query:
                target_chunk_types.append('property_document')
            
            per_type_results = max(2, n_results // len(target_chunk_types)) if target_chunk_types else n_results
            for chunk_type in target_chunk_types:
                type_results = self.vector_store.search(
                    query=query,
                    n_results=per_type_results,
                    filter_metadata={'listing_id': listing_id, 'chunk_type': chunk_type},
                    query_embedding=query_embedding,
                )
                for r in type_results:
                    if r['id'] not in seen_ids:
                        results.append(r)
                        seen_ids.add(r['id'])
            
            # Additional fill-up search: EXCLUDE property_document chunks to prioritize backend JSON data
            # This ensures PDF data doesn't override backend pricing/specifications
            if len(results) < n_results:
                additional = self.vector_store.search(
                    query=query,
                    n_results=n_results - len(results),
                    listing_id=listing_id,
                    chunk_types=['overview', 'pricing', 'specifications', 'location', 'attributes', 'amenities'],  # Exclude property_document
                    query_embedding=query_embedding,
                )
                for r in additional:
                    if r['id'] not in seen_ids:
                        results.append(r)
                        seen_ids.add(r['id'])
            
            self._last_timings["search_rerank_ms"] = (time.perf_counter() - t_after_embed) * 1000.0
            reranked = await self._rerank(results, query)
            return reranked[:n_results]

        if is_price_query and not is_multi_topic:
            allow_hybrid = False
            chunk_types = ['pricing']
        
        # For attribute queries (land area, bedrooms, etc.), explicitly search specifications chunk
        # Also use hybrid mode to ensure we get the specifications chunk even if similarity is low
        if is_attribute_query and not is_multi_topic and not is_price_query:
            chunk_types = ['specifications', 'overview']  # Specifications has detailed attributes, overview has summary
            allow_hybrid = True  # Ensure we get all chunks for this listing, then rerank
        
        # For amenity queries, search both amenities chunk AND property_document PDFs
        # Property PDFs often contain nearby school/hospital information
        if is_amenity_query and not is_multi_topic and not is_price_query and listing_id:
            logger.info("🏫 Amenity query detected (single-topic, not price)")
            logger.debug(
                "   Setting chunk_types=['amenities', 'property_document', 'overview'], allow_hybrid=True",
            )
            # Include property_document for school/hospital info
            chunk_types = ['amenities', 'property_document', 'overview']
            # Ensure we get all chunks for this listing, then rerank
            allow_hybrid = True
        
        # For document queries, explicitly include property_document chunks
        if is_document_query and not is_multi_topic and listing_id:
            # Search both general chunks and property_document chunks
            results = []
            seen_ids = set()
            
            # First, search property_document chunks specifically
            doc_results = self.vector_store.search(
                query=query,
                n_results=max(3, n_results // 2),
                filter_metadata={'listing_id': listing_id, 'chunk_type': 'property_document'},
                query_embedding=query_embedding,
            )
            for r in doc_results:
                results.append(r)
                seen_ids.add(r['id'])
            
            # Then, search other chunks
            other_results = self.vector_store.search(
                query=query,
                n_results=n_results - len(results),
                filter_metadata={'listing_id': listing_id},
                query_embedding=query_embedding,
            )
            for r in other_results:
                if r['id'] not in seen_ids:
                    results.append(r)
                    seen_ids.add(r['id'])
            
            # Add all listing chunks in hybrid mode if needed
            if allow_hybrid:
                listing_chunks = self.vector_store.get_by_listing_id(listing_id)
                for chunk in listing_chunks:
                    if chunk['id'] not in seen_ids:
                        results.append(chunk)
                        seen_ids.add(chunk['id'])
            
            self._last_timings["search_rerank_ms"] = (time.perf_counter() - t_after_embed) * 1000.0
            reranked = await self._rerank(results, query)
            return reranked[:n_results]

        filters = {}
        if listing_id:
            filters['listing_id'] = listing_id
        if chunk_types and len(chunk_types) == 1:
            filters['chunk_type'] = chunk_types[0]

        # Pass chunk_types directly to search (supports multiple types)
        logger.debug("🔍 Calling vector_store.search with:")
        logger.debug("   query='%s'", query)
        logger.debug("   n_results=%d", n_results)
        logger.debug("   listing_id=%s", listing_id)
        logger.debug("   chunk_types=%s", chunk_types)
        logger.debug("   allow_hybrid=%s", allow_hybrid)

        results = self.vector_store.search(
            query=query,
            n_results=n_results,
            listing_id=listing_id,
            chunk_types=chunk_types if chunk_types else None,
            filter_metadata=filters if filters else None,
            query_embedding=query_embedding,
        )
        
        logger.info("✅ vector_store.search returned %d results", len(results))
        for i, r in enumerate(results[:5]):  # Show first 5
            logger.debug(
                "   [%d] chunk_type=%s, similarity=%.3f, listing_id=%s",
                i + 1,
                r.get('chunk_type', 'unknown'),
                r.get('similarity', 0),
                r.get('listing_id', 'N/A'),
            )

        
        if allow_hybrid and listing_id:
            listing_chunks = self.vector_store.get_by_listing_id(listing_id)

            seen_ids = {r['id'] for r in results}
            for chunk in listing_chunks:
                # Filter by chunk_type if specified
                if chunk_types:
                    chunk_type = chunk.get('metadata', {}).get('chunk_type') or chunk.get('chunk_type')
                    if chunk_type not in chunk_types:
                        continue
                if chunk['id'] not in seen_ids:
                    results.append(chunk)
                    seen_ids.add(chunk['id'])

        self._last_timings["search_rerank_ms"] = (time.perf_counter() - t_after_embed) * 1000.0
        reranked = await self._rerank(results, query)
        return reranked[:n_results]

   
    async def _rerank(
        self,
        results: List[Dict[str, Any]],
        query: str
    ) -> List[Dict[str, Any]]:

        query_terms = set(re.findall(r'\b\w+\b', query.lower()))

        scored = []
        for r in results:
            content = r.get('content', '').lower()
            distance = r.get('distance', 0.7)

            similarity = 1 - min(distance, 1.0)

            keyword_overlap = len(
                query_terms.intersection(set(content.split()))
            )

            score = (similarity * 0.7) + (min(keyword_overlap, 3) * 0.1)

            scored.append({**r, "_score": score})

        scored.sort(key=lambda x: x["_score"], reverse=True)

        for r in scored:
            r.pop("_score", None)

        return scored


    async def retrieve_pricing_info(
        self,
        query: str,
        listing_id: str
    ) -> List[Dict[str, Any]]:
        """
        STRICT pricing retrieval — no hybrid, no ambiguity.
        """
        return self.retrieve(
            query=query,
            listing_id=listing_id,
            chunk_types=['pricing'],
            n_results=1,
            allow_hybrid=False
        )
    
    
    async def retrieve_with_location_context(
        self,
        query: str,
        listing_id: str,
        n_results: int = 8,
        max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
        max_nearby_properties: int = DEFAULT_MAX_NEARBY_PROPERTIES,
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Retrieve context with location-aware information for nearby queries.
        
        Args:
            query: User query
            listing_id: Current property listing ID
            n_results: Number of semantic results to retrieve
            max_distance_km: Maximum distance for nearby properties (km)
            max_nearby_properties: Maximum number of nearby properties to include
            
        Returns:
            Tuple of (standard_results, location_context)
            location_context contains nearby properties and location info
        """
        is_location_query, query_type = detect_location_query(query)
        
        standard_results = await self.retrieve(
            query=query,
            listing_id=listing_id,
            n_results=n_results
        )
        
        if not is_location_query:
            return standard_results, None

        # Fetch location and suburb in one DB call (avoids 2x get_by_listing_id and 2x repo calls)
        t_loc = time.perf_counter()
        current_lat = None
        current_lon = None
        current_address = None
        current_suburb = None
        location_data = None
        try:
            async with self._get_listing_repository() as listing_repo:
                location_data = await listing_repo.get_listing_location(listing_id)
                if location_data:
                    lat, lon = location_data.get('latitude'), location_data.get('longitude')
                    if lat is not None and lon is not None:
                        current_lat, current_lon = float(lat), float(lon)
                    current_address = (location_data.get('displayAddress') or '').strip() or None
                    current_suburb = (location_data.get('suburb') or '').strip() or None
        except Exception as e:
            logger.exception("⚠️  Could not fetch location/suburb for listing %s: %s", listing_id, e)
        self._last_timings["get_location_ms"] = (time.perf_counter() - t_loc) * 1000.0

        # Fallback: get from retrieval results; only re-query DB if we never got location_data (avoids redundant calls)
        if current_lat is None and current_lon is None:
            for result in standard_results:
                location = get_location_from_chunk(result.get('metadata', {}))
                if location:
                    current_lat, current_lon, current_address = location
                    break
            if current_lat is None and location_data is None:
                loc = self._get_location_from_database(listing_id)
                if loc:
                    current_lat, current_lon, current_address = loc
        if not current_suburb:
            for result in standard_results:
                suburb = get_suburb_from_chunk(result.get('metadata', {}))
                if suburb:
                    current_suburb = suburb
                    break
            if not current_suburb and location_data is None:
                current_suburb = self._get_suburb_from_database(listing_id)
        
        nearby_properties = []
        same_suburb_properties = []

        if query_type == 'nearby_properties':
            # Use database first for nearby/same-suburb (avoids loading all chunks via get_all_chunks())
            nearby_properties_raw = []
            if current_lat is not None and current_lon is not None:
                logger.info(
                    "🔍 Searching for nearby properties (lat=%s, lon=%s, max_distance=%skm)",
                    current_lat,
                    current_lon,
                    max_distance_km,
                )
                t_nearby = time.perf_counter()
                nearby_properties_raw = await self._fetch_nearby_properties_from_database(
                    current_lat=current_lat,
                    current_lon=current_lon,
                    listing_id=listing_id,
                    max_distance_km=max_distance_km,
                    max_nearby_properties=max_nearby_properties
                )
                self._last_timings["nearby_db_ms"] = (time.perf_counter() - t_nearby) * 1000.0
                if nearby_properties_raw:
                    logger.info(
                        "   Found %d nearby properties from database",
                        len(nearby_properties_raw),
                    )
            if not nearby_properties_raw and current_suburb:
                logger.info("   Trying same-suburb properties in '%s'", current_suburb)
                t_suburb = time.perf_counter()
                same_suburb_properties = await self._fetch_same_suburb_properties_from_database(
                    current_suburb=current_suburb,
                    listing_id=listing_id,
                    max_nearby_properties=max_nearby_properties
                )
                self._last_timings["same_suburb_db_ms"] = (time.perf_counter() - t_suburb) * 1000.0
            # Fallback: only load all chunks when DB returned nothing (slow path)
            if not nearby_properties_raw and not same_suburb_properties:
                all_chunks_dict = self.vector_store.get_all_chunks()
                all_properties = [
                    {'content': doc, 'metadata': meta}
                    for doc, meta in zip(
                        all_chunks_dict.get('documents', []),
                        all_chunks_dict.get('metadatas', [])
                    )
                ]
                if current_lat is not None and current_lon is not None:
                    nearby_properties_raw = find_nearby_properties(
                        current_lat=current_lat,
                        current_lon=current_lon,
                        all_properties=all_properties,
                        max_distance_km=max_distance_km,
                        max_results=max_nearby_properties,
                        current_listing_id=listing_id
                    )
                if not nearby_properties_raw and current_suburb:
                    same_suburb_properties = find_same_suburb_properties(
                        current_suburb=current_suburb,
                        all_properties=all_properties,
                        max_results=max_nearby_properties,
                        current_listing_id=listing_id
                    )

            # Enrich nearby properties with full listing data
            for nearby_prop in nearby_properties_raw:
                await self._enrich_property_with_chunks(nearby_prop)
            
            nearby_properties = nearby_properties_raw
            
            # Enrich same-suburb properties with full listing data
            for same_suburb_prop in same_suburb_properties:
                await self._enrich_property_with_chunks(same_suburb_prop)
        
        # Format nearby properties JSON and add property media
        nearby_properties_json = []
        if nearby_properties:
            nearby_properties_json = format_nearby_properties_json(nearby_properties)
            
            # Filter out the current listing from nearby properties (shouldn't be in "nearby" list)
            original_count = len(nearby_properties_json)
            nearby_properties_json = [
                prop for prop in nearby_properties_json
                if prop.get('id') != listing_id
            ]
            if len(nearby_properties_json) < original_count:
                logger.info("🏠 Filtered out current listing (%s) from nearby properties", listing_id)

            logger.info(
                "📸 Formatted %d nearby properties, now fetching property media...",
                len(nearby_properties_json),
            )

            # Fetch property media for all nearby properties
            listing_ids = [prop.get('id') for prop in nearby_properties_json if prop.get('id')]
            logger.debug("📸 Extracted %d listing IDs: %s", len(listing_ids), listing_ids)

            if listing_ids:
                try:
                    async with self._get_listing_repository() as listing_repo:
                        property_media_dict = await listing_repo.get_multiple_listing_property_media(listing_ids)
                        logger.info(
                            "📸 Fetched property media for %d listings",
                            len(property_media_dict),
                        )

                        # Add propertyMedia array to each property
                        for prop in nearby_properties_json:
                            listing_id = prop.get('id')
                            if listing_id and listing_id in property_media_dict:
                                media_count = len(property_media_dict[listing_id])
                                prop['propertyMedia'] = property_media_dict[listing_id]
                                logger.debug(
                                    "   ✅ Added %d media items to listing %s",
                                    media_count,
                                    listing_id,
                                )
                            else:
                                logger.debug("   ⚠️  No media found for listing %s", listing_id)
                except Exception as e:
                    logger.exception("⚠️  Error fetching nearby property media: %s", e)
        
        location_context = {
            'latitude': current_lat,
            'longitude': current_lon,
            'address': current_address,
            'suburb': current_suburb,
            'query_type': query_type,
            'nearby_properties': nearby_properties,
            'same_suburb_properties': same_suburb_properties,
            'nearby_properties_json': nearby_properties_json,
            'formatted_context': format_location_info_for_prompt(
                latitude=current_lat,
                longitude=current_lon,
                address=current_address,
                suburb=current_suburb,
                nearby_properties=nearby_properties if nearby_properties else None,
                same_suburb_properties=same_suburb_properties if same_suburb_properties else None,
                query_type=query_type
            )
        }
        
        return standard_results, location_context



