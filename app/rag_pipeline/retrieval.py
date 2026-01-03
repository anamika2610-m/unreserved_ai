"""
Retrieval module for querying the vector store to find relevant property listing information.
SAFE version with strict factual retrieval guarantees.
Includes location-based retrieval for nearby properties and amenities.
Now using pgvector (PostgreSQL native vector storage) instead of ChromaDB.
"""

from typing import List, Dict, Any, Optional, Tuple
import re
from app.ingestion_pipeline.vector_store import PropertyVectorStore
from app.rag_pipeline.location_utils import (
    detect_location_query,
    get_location_from_chunk,
    find_nearby_properties,
    format_location_info_for_prompt,
    format_nearby_properties_json
)


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

    def __init__(
        self,
        vector_store: Optional[PropertyVectorStore] = None,
        collection_name: str = "property_listings",
        persist_directory: str = "./chroma_db"
    ):
        self.vector_store = vector_store or PropertyVectorStore(
            collection_name=collection_name,
            persist_directory=persist_directory
        )

    def retrieve(
        self,
        query: str,
        n_results: int = 5,
        listing_id: Optional[str] = None,
        chunk_types: Optional[List[str]] = None,
        allow_hybrid: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Safe retrieval logic with multi-topic query detection.
        """

        query_lower = query.lower()
        is_price_query = any(k in query_lower for k in self.PRICE_KEYWORDS)
        is_amenity_query = any(k in query_lower for k in self.AMENITY_KEYWORDS)
        is_attribute_query = any(k in query_lower for k in self.ATTRIBUTE_KEYWORDS)
        
        topic_count = sum([is_price_query, is_amenity_query, is_attribute_query])
        is_multi_topic = topic_count > 1

        if is_multi_topic and listing_id:
            results = []
            seen_ids = set()
            
            target_chunk_types = []
            if is_price_query:
                target_chunk_types.append('pricing')
            if is_amenity_query or is_attribute_query:
                target_chunk_types.extend(['attributes', 'amenities'])
            
            per_type_results = max(2, n_results // len(target_chunk_types))
            for chunk_type in target_chunk_types:
                type_results = self.vector_store.search(
                    query=query,
                    n_results=per_type_results,
                    filter_metadata={'listing_id': listing_id, 'chunk_type': chunk_type}
                )
                for r in type_results:
                    if r['id'] not in seen_ids:
                        results.append(r)
                        seen_ids.add(r['id'])
            
            if len(results) < n_results:
                additional = self.vector_store.search(
                    query=query,
                    n_results=n_results - len(results),
                    filter_metadata={'listing_id': listing_id}
                )
                for r in additional:
                    if r['id'] not in seen_ids:
                        results.append(r)
                        seen_ids.add(r['id'])
            
            return self._rerank(results, query)[:n_results]

        if is_price_query and not is_multi_topic:
            allow_hybrid = False
            chunk_types = ['pricing']

        filters = {}
        if listing_id:
            filters['listing_id'] = listing_id
        if chunk_types and len(chunk_types) == 1:
            filters['chunk_type'] = chunk_types[0]

        results = self.vector_store.search(
            query=query,
            n_results=n_results,
            filter_metadata=filters if filters else None
        )

        # ---- Optional hybrid (ONLY for non-factual fields)
        if allow_hybrid and listing_id:
            listing_chunks = self.vector_store.get_by_listing_id(listing_id)

            seen_ids = {r['id'] for r in results}
            for chunk in listing_chunks:
                if chunk['id'] not in seen_ids:
                    results.append(chunk)

        # ---- Final rerank
        return self._rerank(results, query)[:n_results]

   
    def _rerank(
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


    def retrieve_pricing_info(
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
    
    
    def retrieve_with_location_context(
        self,
        query: str,
        listing_id: str,
        n_results: int = 8,
        max_distance_km: float = 15.0,
        max_nearby_properties: int = 5
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
        
        standard_results = self.retrieve(
            query=query,
            listing_id=listing_id,
            n_results=n_results
        )
        
        if not is_location_query:
            return standard_results, None
        
        current_location = None
        for result in standard_results:
            location = get_location_from_chunk(result.get('metadata', {}))
            if location:
                current_location = location
                break
        
        if not current_location:
            listing_chunks = self.vector_store.get_by_listing_id(listing_id)
            for chunk in listing_chunks:
                location = get_location_from_chunk(chunk.get('metadata', {}))
                if location:
                    current_location = location
                    break
        
        if not current_location:
            return standard_results, None
        
        current_lat, current_lon, current_address = current_location
        
        nearby_properties = []
        if query_type == 'nearby_properties':
            all_chunks = self.vector_store.collection.get()
            
            all_properties = []
            for i in range(len(all_chunks['ids'])):
                all_properties.append({
                    'id': all_chunks['ids'][i],
                    'content': all_chunks['documents'][i] if 'documents' in all_chunks else '',
                    'metadata': all_chunks['metadatas'][i] if 'metadatas' in all_chunks else {}
                })
            
            nearby_properties_raw = find_nearby_properties(
                current_lat=current_lat,
                current_lon=current_lon,
                all_properties=all_properties,
                max_distance_km=max_distance_km,
                max_results=max_nearby_properties
            )
            
            for nearby_prop in nearby_properties_raw:
                listing_id = nearby_prop['listing_id']
                listing_chunks = self.vector_store.get_by_listing_id(listing_id)
                
                enriched_metadata = nearby_prop['metadata'].copy()
                enriched_content_parts = [nearby_prop['content']]
                
                for chunk in listing_chunks:
                    chunk_meta = chunk.get('metadata', {})
                    chunk_content = chunk.get('content', '')
                    
                    for key, value in chunk_meta.items():
                        if key not in enriched_metadata or enriched_metadata[key] in [None, '', 'N/A']:
                            enriched_metadata[key] = value
                    
                    if chunk_content and chunk_content not in enriched_content_parts:
                        enriched_content_parts.append(chunk_content)
                
                nearby_prop['metadata'] = enriched_metadata
                nearby_prop['content'] = ' | '.join(enriched_content_parts[:3])  # Limit to avoid too much
                
            nearby_properties = nearby_properties_raw
        
        location_context = {
            'latitude': current_lat,
            'longitude': current_lon,
            'address': current_address,
            'query_type': query_type,
            'nearby_properties': nearby_properties,
            'nearby_properties_json': format_nearby_properties_json(nearby_properties) if nearby_properties else [],
            'formatted_context': format_location_info_for_prompt(
                latitude=current_lat,
                longitude=current_lon,
                address=current_address,
                nearby_properties=nearby_properties if nearby_properties else None,
                query_type=query_type
            )
        }
        
        return standard_results, location_context



