"""
Retrieval module for querying the vector store to find relevant property listing information.
SAFE version with strict factual retrieval guarantees.
Includes location-based retrieval for nearby properties and amenities.
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

    # ------------------------------------------------------------------
    # Core retrieval
    # ------------------------------------------------------------------

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

        # ---- Detect query topics
        query_lower = query.lower()
        is_price_query = any(k in query_lower for k in self.PRICE_KEYWORDS)
        is_amenity_query = any(k in query_lower for k in self.AMENITY_KEYWORDS)
        is_attribute_query = any(k in query_lower for k in self.ATTRIBUTE_KEYWORDS)
        
        # Count how many topics are being asked about
        topic_count = sum([is_price_query, is_amenity_query, is_attribute_query])
        is_multi_topic = topic_count > 1

        # ---- Handle multi-topic queries (e.g., "pricing and amenities")
        if is_multi_topic and listing_id:
            # For multi-topic queries, retrieve from each relevant chunk type
            results = []
            seen_ids = set()
            
            # Determine which chunk types to query
            target_chunk_types = []
            if is_price_query:
                target_chunk_types.append('pricing')
            if is_amenity_query or is_attribute_query:
                target_chunk_types.extend(['attributes', 'amenities'])
            
            # Retrieve from each chunk type
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
            
            # If we still don't have enough, get more with semantic search
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

        # ---- Single-topic price query: FORCE strict mode
        if is_price_query and not is_multi_topic:
            allow_hybrid = False
            chunk_types = ['pricing']

        # ---- Metadata filter (MANDATORY for correctness)
        filters = {}
        if listing_id:
            filters['listing_id'] = listing_id
        if chunk_types and len(chunk_types) == 1:
            filters['chunk_type'] = chunk_types[0]

        # ---- Vector search
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

    # ------------------------------------------------------------------
    # Reranking
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Convenience APIs
    # ------------------------------------------------------------------

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
    
    # ------------------------------------------------------------------
    # Location-based Retrieval
    # ------------------------------------------------------------------
    
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
        # Detect if this is a location-based query
        is_location_query, query_type = detect_location_query(query)
        
        # Get standard retrieval results
        standard_results = self.retrieve(
            query=query,
            listing_id=listing_id,
            n_results=n_results
        )
        
        # If not a location query, return early
        if not is_location_query:
            return standard_results, None
        
        # Get current property's location from retrieved chunks
        current_location = None
        for result in standard_results:
            location = get_location_from_chunk(result.get('metadata', {}))
            if location:
                current_location = location
                break
        
        # If no location found in chunks, try getting all chunks for this listing
        if not current_location:
            listing_chunks = self.vector_store.get_by_listing_id(listing_id)
            for chunk in listing_chunks:
                location = get_location_from_chunk(chunk.get('metadata', {}))
                if location:
                    current_location = location
                    break
        
        # If still no location, return standard results
        if not current_location:
            return standard_results, None
        
        current_lat, current_lon, current_address = current_location
        
        # Find nearby properties if query is about properties
        nearby_properties = []
        if query_type == 'nearby_properties':
            # Get all properties from vector store
            all_chunks = self.vector_store.collection.get()
            
            # Convert to list of dicts
            all_properties = []
            for i in range(len(all_chunks['ids'])):
                all_properties.append({
                    'id': all_chunks['ids'][i],
                    'content': all_chunks['documents'][i] if 'documents' in all_chunks else '',
                    'metadata': all_chunks['metadatas'][i] if 'metadatas' in all_chunks else {}
                })
            
            # Find nearby properties
            nearby_properties_raw = find_nearby_properties(
                current_lat=current_lat,
                current_lon=current_lon,
                all_properties=all_properties,
                max_distance_km=max_distance_km,
                max_results=max_nearby_properties
            )
            
            # Enrich nearby properties with complete data from all their chunks
            for nearby_prop in nearby_properties_raw:
                listing_id = nearby_prop['listing_id']
                # Get all chunks for this listing
                listing_chunks = self.vector_store.get_by_listing_id(listing_id)
                
                # Merge data from all chunks
                enriched_metadata = nearby_prop['metadata'].copy()
                enriched_content_parts = [nearby_prop['content']]
                
                for chunk in listing_chunks:
                    chunk_meta = chunk.get('metadata', {})
                    chunk_content = chunk.get('content', '')
                    
                    # Update metadata with any missing fields
                    for key, value in chunk_meta.items():
                        if key not in enriched_metadata or enriched_metadata[key] in [None, '', 'N/A']:
                            enriched_metadata[key] = value
                    
                    # Append content from other chunks
                    if chunk_content and chunk_content not in enriched_content_parts:
                        enriched_content_parts.append(chunk_content)
                
                # Update the nearby property with enriched data
                nearby_prop['metadata'] = enriched_metadata
                nearby_prop['content'] = ' | '.join(enriched_content_parts[:3])  # Limit to avoid too much
                
            nearby_properties = nearby_properties_raw
        
        # Build location context
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




# """
# Retrieval module for querying the vector store to find relevant property listing information.
# Enhanced with query intent detection, hybrid retrieval, and reranking.
# """
# from typing import List, Dict, Any, Optional, Set
# import re
# from app.ingestion_pipeline.vector_store import PropertyVectorStore


# class PropertyRetriever:
#     """
#     Retrieves relevant property listing information from the vector store.
#     Enhanced with intelligent query understanding and hybrid retrieval.
#     """
    
#     # Query intent keywords
#     PRICE_KEYWORDS = ['price', 'cost', 'asking', 'offer', 'bid', 'auction price', 'how much', 'pricing']
#     SPECS_KEYWORDS = ['bedroom', 'bathroom', 'garage', 'area', 'sqm', 'specification', 'feature', 'amenity', 'pool', 'gym', 'sauna']
#     LOCATION_KEYWORDS = ['location', 'address', 'suburb', 'city', 'inspection', 'visit', 'where']
#     BIDDING_KEYWORDS = ['bid', 'bidding', 'auction', 'offer', 'tender', 'deadline']
    
#     def __init__(
#         self,
#         vector_store: Optional[PropertyVectorStore] = None,
#         collection_name: str = "property_listings",
#         persist_directory: str = "./chroma_db",
#         use_hybrid_retrieval: bool = True
#     ):
#         """
#         Initialize the retriever.
        
#         Args:
#             vector_store: Optional pre-initialized vector store
#             collection_name: Name of the ChromaDB collection
#             persist_directory: Directory where ChromaDB data is persisted
#             use_hybrid_retrieval: If True, retrieve all chunks for matched listings
#         """
#         if vector_store is None:
#             self.vector_store = PropertyVectorStore(
#                 collection_name=collection_name,
#                 persist_directory=persist_directory
#             )
#         else:
#             self.vector_store = vector_store
#         self.use_hybrid_retrieval = use_hybrid_retrieval
    
#     def detect_query_intent(self, query: str) -> Dict[str, float]:
#         """
#         Detect the intent of a query to prioritize relevant chunk types.
        
#         Args:
#             query: The search query
            
#         Returns:
#             Dictionary mapping chunk types to relevance scores (0.0-1.0)
#         """
#         query_lower = query.lower()
        
#         scores = {
#             'pricing': 0.0,
#             'specifications': 0.0,
#             'location': 0.0,
#             'bidding': 0.0,
#             'overview': 0.5  # Default baseline
#         }
        
#         # Count keyword matches
#         price_matches = sum(1 for kw in self.PRICE_KEYWORDS if kw in query_lower)
#         specs_matches = sum(1 for kw in self.SPECS_KEYWORDS if kw in query_lower)
#         location_matches = sum(1 for kw in self.LOCATION_KEYWORDS if kw in query_lower)
#         bidding_matches = sum(1 for kw in self.BIDDING_KEYWORDS if kw in query_lower)
        
#         # Calculate scores (normalized to 0-1)
#         if price_matches > 0:
#             scores['pricing'] = min(1.0, 0.5 + (price_matches * 0.2))
#         if specs_matches > 0:
#             scores['specifications'] = min(1.0, 0.5 + (specs_matches * 0.15))
#         if location_matches > 0:
#             scores['location'] = min(1.0, 0.5 + (location_matches * 0.2))
#         if bidding_matches > 0:
#             scores['bidding'] = min(1.0, 0.5 + (bidding_matches * 0.2))
        
#         # If no specific intent detected, boost overview
#         if sum([price_matches, specs_matches, location_matches, bidding_matches]) == 0:
#             scores['overview'] = 0.8
        
#         return scores
    
#     def retrieve(
#         self,
#         query: str,
#         n_results: int = 5,
#         listing_id: Optional[str] = None,
#         chunk_types: Optional[List[str]] = None,
#         use_hybrid: Optional[bool] = None
#     ) -> List[Dict[str, Any]]:
#         """
#         Retrieve relevant chunks for a query with intelligent reranking.
        
#         Args:
#             query: The search query
#             n_results: Number of results to return
#             listing_id: Optional listing ID to filter by
#             chunk_types: Optional list of chunk types to filter by
#             use_hybrid: Override default hybrid retrieval setting
            
#         Returns:
#             List of relevant chunks with content and metadata, reranked by relevance
#         """
#         use_hybrid = use_hybrid if use_hybrid is not None else self.use_hybrid_retrieval
        
#         # Detect query intent
#         intent_scores = self.detect_query_intent(query)
        
#         # Build filter metadata
#         filter_metadata = {}
#         if listing_id:
#             filter_metadata['listing_id'] = listing_id
#         if chunk_types and len(chunk_types) > 0:
#             if len(chunk_types) == 1:
#                 filter_metadata['chunk_type'] = chunk_types[0]
        
#         # Search vector store - get more results for reranking
#         search_n = n_results * 3 if use_hybrid else n_results * 2
#         results = self.vector_store.search(
#             query=query,
#             n_results=search_n,
#             filter_metadata=filter_metadata if filter_metadata else None
#         )
        
#         # Filter by chunk types if multiple specified
#         if chunk_types and len(chunk_types) > 1:
#             results = [
#                 r for r in results
#                 if r.get('metadata', {}).get('chunk_type') in chunk_types
#             ]
        
#         # Hybrid retrieval: get all chunks for matched listings
#         if use_hybrid and not listing_id:
#             matched_listing_ids = set()
#             for result in results[:n_results * 2]:  # Check top results
#                 lid = result.get('metadata', {}).get('listing_id')
#                 if lid:
#                     matched_listing_ids.add(lid)
            
#             # Get all chunks for matched listings
#             for lid in matched_listing_ids:
#                 listing_chunks = self.vector_store.get_by_listing_id(lid)
#                 # Add chunks that aren't already in results
#                 existing_ids = {r.get('id') for r in results}
#                 for chunk in listing_chunks:
#                     if chunk.get('id') not in existing_ids:
#                         # Set a default distance for chunks retrieved by listing ID
#                         # Prioritize chunks that match query intent
#                         chunk_type = chunk.get('metadata', {}).get('chunk_type', 'overview')
#                         intent_score = intent_scores.get(chunk_type, 0.5)
#                         # Lower distance (higher similarity) for higher intent scores
#                         chunk['distance'] = 0.6 - (intent_score * 0.3)  # Range: 0.3-0.6
#                         results.append(chunk)
        
#         # Rerank results based on intent and distance
#         reranked = self._rerank_results(results, intent_scores, query)
        
#         # Return top n_results
#         return reranked[:n_results]
    
#     def _rerank_results(
#         self,
#         results: List[Dict[str, Any]],
#         intent_scores: Dict[str, float],
#         query: str
#     ) -> List[Dict[str, Any]]:
#         """
#         Rerank results combining semantic similarity with chunk type relevance.
        
#         Args:
#             results: List of retrieval results
#             intent_scores: Query intent scores by chunk type
#             query: Original query for additional scoring
            
#         Returns:
#             Reranked list of results
#         """
#         scored_results = []
#         query_lower = query.lower()
#         is_price_query = any(kw in query_lower for kw in self.PRICE_KEYWORDS)
        
#         for result in results:
#             metadata = result.get('metadata', {})
#             chunk_type = metadata.get('chunk_type', 'overview')
#             distance = result.get('distance', 0.5)
#             content = result.get('content', '')
            
#             # Get intent score for this chunk type
#             intent_score = intent_scores.get(chunk_type, 0.5)
            
#             # Combine distance (lower is better) with intent (higher is better)
#             # Convert distance to similarity (1 - distance) and combine with intent
#             similarity = 1.0 - min(distance, 1.0)  # Normalize distance to 0-1
#             combined_score = (similarity * 0.6) + (intent_score * 0.4)
            
#             # Special boost for price queries - prioritize pricing chunks
#             if is_price_query and chunk_type == 'pricing':
#                 combined_score += 0.3  # Strong boost
#             elif is_price_query and chunk_type == 'overview' and any(kw in content.lower() for kw in ['price', '$', 'cost', 'asking']):
#                 combined_score += 0.15  # Moderate boost if overview mentions price
            
#             # Boost overview chunks if they contain query keywords
#             if chunk_type == 'overview':
#                 content_lower = content.lower()
#                 query_words = set(re.findall(r'\b\w+\b', query_lower))
#                 content_words = set(re.findall(r'\b\w+\b', content_lower))
#                 overlap = len(query_words & content_words)
#                 if overlap > 0:
#                     combined_score += min(0.2, overlap * 0.05)
            
#             # Boost chunks that directly answer the query
#             content_lower = content.lower()
#             if any(word in content_lower for word in re.findall(r'\b\w+\b', query_lower)[:3]):  # Check first 3 query words
#                 combined_score += 0.1
            
#             scored_results.append({
#                 **result,
#                 '_relevance_score': combined_score
#             })
        
#         # Sort by relevance score (descending)
#         scored_results.sort(key=lambda x: x.get('_relevance_score', 0), reverse=True)
        
#         # Remove the temporary score field
#         for result in scored_results:
#             result.pop('_relevance_score', None)
        
#         return scored_results
    
#     def retrieve_for_listing(
#         self,
#         listing_id: str,
#         query: Optional[str] = None
#     ) -> List[Dict[str, Any]]:
#         """
#         Retrieve all chunks for a specific listing, optionally filtered by query.
        
#         Args:
#             listing_id: The listing ID
#             query: Optional query to filter/rank chunks
            
#         Returns:
#             List of chunks for the listing, optionally reranked by query relevance
#         """
#         if query:
#             # Use semantic search to find most relevant chunks
#             return self.retrieve(
#                 query=query,
#                 n_results=10,
#                 listing_id=listing_id,
#                 use_hybrid=False  # Already have all chunks for this listing
#             )
#         else:
#             # Get all chunks for the listing
#             chunks = self.vector_store.get_by_listing_id(listing_id)
#             # Sort by chunk_index for consistent ordering
#             chunks.sort(key=lambda x: int(x.get('metadata', {}).get('chunk_index', 0)))
#             return chunks
    
#     def retrieve_pricing_info(
#         self,
#         query: str,
#         listing_id: Optional[str] = None,
#         n_results: int = 3
#     ) -> List[Dict[str, Any]]:
#         """
#         Retrieve pricing-specific information.
        
#         Args:
#             query: The search query
#             listing_id: Optional listing ID to filter by
#             n_results: Number of results to return
            
#         Returns:
#             List of pricing-related chunks
#         """
#         return self.retrieve(
#             query=query,
#             n_results=n_results,
#             listing_id=listing_id,
#             chunk_types=['pricing'],
#             use_hybrid=True  # Get all chunks for matched listings, then filter
#         )
    
#     def retrieve_specifications(
#         self,
#         query: str,
#         listing_id: Optional[str] = None,
#         n_results: int = 3
#     ) -> List[Dict[str, Any]]:
#         """
#         Retrieve specification-related information.
        
#         Args:
#             query: The search query
#             listing_id: Optional listing ID to filter by
#             n_results: Number of results to return
            
#         Returns:
#             List of specification-related chunks
#         """
#         return self.retrieve(
#             query=query,
#             n_results=n_results,
#             listing_id=listing_id,
#             chunk_types=['specifications'],
#             use_hybrid=True
#         )
    
#     def retrieve_bidding_info(
#         self,
#         query: str,
#         listing_id: Optional[str] = None,
#         n_results: int = 3
#     ) -> List[Dict[str, Any]]:
#         """
#         Retrieve bidding/auction-related information.
        
#         Args:
#             query: The search query
#             listing_id: Optional listing ID to filter by
#             n_results: Number of results to return
            
#         Returns:
#             List of bidding-related chunks
#         """
#         return self.retrieve(
#             query=query,
#             n_results=n_results,
#             listing_id=listing_id,
#             chunk_types=['bidding'],
#             use_hybrid=True
#         )
    
#     def format_retrieval_results(
#         self,
#         results: List[Dict[str, Any]],
#         include_metadata: bool = False,
#         max_preview_length: int = 400
#     ) -> str:
#         """
#         Format retrieval results into a readable string for LLM context.
#         Enhanced with better previews showing full highlights/amenities.
        
#         Args:
#             results: List of retrieval results
#             include_metadata: Whether to include metadata in the formatted output
#             max_preview_length: Maximum length for content preview (0 = full content)
            
#         Returns:
#             Formatted string with retrieved information
#         """
#         if not results:
#             return "No relevant information found."
        
#         formatted_parts = []
#         for i, result in enumerate(results, 1):
#             content = result.get('content', '')
#             metadata = result.get('metadata', {})
#             chunk_type = metadata.get('chunk_type', 'unknown')
            
#             # For specifications chunks, ensure highlights/amenities are visible
#             if chunk_type == 'specifications' and max_preview_length > 0:
#                 # Find where highlights/amenities are mentioned
#                 if 'Special Features:' in content or 'Highlights:' in content:
#                     # Try to show at least up to highlights
#                     highlight_idx = content.find('Special Features:')
#                     if highlight_idx == -1:
#                         highlight_idx = content.find('Highlights:')
#                     if highlight_idx > 0:
#                         # Show content up to highlights + 200 more chars
#                         preview_end = min(len(content), highlight_idx + 200)
#                         if preview_end < len(content):
#                             content_preview = content[:preview_end] + "..."
#                         else:
#                             content_preview = content
#                     else:
#                         content_preview = content[:max_preview_length] + "..." if len(content) > max_preview_length else content
#                 else:
#                     content_preview = content[:max_preview_length] + "..." if len(content) > max_preview_length else content
#             else:
#                 content_preview = content[:max_preview_length] + "..." if max_preview_length > 0 and len(content) > max_preview_length else content
            
#             formatted_parts.append(f"[Source {i} - {chunk_type}]")
#             formatted_parts.append(content_preview)
            
#             if include_metadata:
#                 listing_id = metadata.get('listing_id', 'N/A')
#                 distance = result.get('distance')
#                 formatted_parts.append(f"  (Listing ID: {listing_id}" + 
#                                      (f", Similarity: {1.0 - distance:.3f}" if distance is not None else "") + ")")
            
#             formatted_parts.append("")  # Empty line between results
        
#         return "\n".join(formatted_parts)
