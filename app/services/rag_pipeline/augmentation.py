"""
Augmentation module for enriching queries with retrieved context.
"""
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy import text
from app.services.rag_pipeline.retrieval import PropertyRetriever
from app.helpers.ingestion_pipeline.generic import GenericKnowledgeStore
from app.schemas import DataSource

# Constants
QUERY_SOURCE_PROPERTY = 'property'
QUERY_SOURCE_GENERIC = 'generic'

DEFAULT_CHUNK_TYPE = 'unknown'
DEFAULT_CATEGORY = 'general'
DEFAULT_LISTING_ID = 'unknown'

CONTENT_PREVIEW_LENGTH = 200
LISTING_ID_DISPLAY_LENGTH = 20

# Data sufficiency check keywords
PRICE_KEYWORDS = ['price', 'cost', 'how much']
PRICE_INDICATORS = ['price', '$', 'asking', 'auction', 'bid', 'offer', 'sale']
SPECIFICATION_KEYWORDS = [
    'bedroom', 'bathroom', 'garage', 'zoning', 'energy rating', 'energy-rating',
    'frontage', 'car port', 'car ports', 'open parking', 'ensuite', 'ensuites',
    'year built', 'land area', 'floor area', 'highlights'
]
LOCATION_KEYWORDS = ['where', 'location', 'address', 'suburb']
NEARBY_PROPERTY_KEYWORDS = ['nearby', 'near']
PROPERTY_ENTITY_KEYWORDS = ['propert', 'listing', 'house']
PROPERTY_CATEGORY_KEYWORDS = [
    'residential', 'rural', 'land', 'property type', 'type of property',
    'what kind of property', 'kind of property', 'category of property'
]


class QueryAugmenter:
    """
    Augments buyer enquiries with relevant property listing information.
    Also supports generic knowledge retrieval.
    """
    
    def __init__(
        self,
        retriever: Optional[PropertyRetriever] = None,
        generic_store: Optional[GenericKnowledgeStore] = None
    ):
        """
        Initialize the query augmenter with pgvector and generic knowledge.
        
        Args:
            retriever: Optional pre-initialized retriever
            generic_store: Optional generic knowledge store
        """
        if retriever is None:
            self.retriever = PropertyRetriever()
        else:
            self.retriever = retriever
        
        # Initialize generic knowledge store (lazy init)
        self._generic_store = generic_store
    
    @property
    def generic_store(self):
        """Lazy initialization of generic knowledge store"""
        if self._generic_store is None:
            self._generic_store = GenericKnowledgeStore()
        return self._generic_store
    
    def augment_query(
        self,
        query: str,
        listing_id: Optional[str] = None,
        n_results: int = 5,
        query_source: str = QUERY_SOURCE_PROPERTY
    ) -> Tuple[str, List[DataSource], Optional[Dict[str, Any]]]:
        """
        Augment a query with relevant retrieved context.
        Supports both property-specific AND generic knowledge queries.
        
        Args:
            query: The buyer's enquiry
            listing_id: Optional listing ID to focus on
            n_results: Number of relevant chunks to retrieve
            query_source: 'property' or 'generic' - determines which store to search
            
        Returns:
            Tuple of (augmented_context, data_sources, location_context)
            location_context includes nearby_properties_json for API response
        """
        # Route to generic knowledge if requested
        if query_source == QUERY_SOURCE_GENERIC:
            return self._augment_generic_query(query, n_results)
        
        # Otherwise, use property-specific retrieval
        results, location_context = self._retrieve_property_data(
            query=query,
            listing_id=listing_id,
            n_results=n_results
        )
        
        # Format retrieved context in a clear, structured way
        augmented_context, data_sources = self._format_property_context(
            results=results,
            location_context=location_context
        )
        
        return augmented_context, data_sources, location_context
    
    def augment_query_json_chunks(
        self,
        query: str,
        listing_id: str,
        n_results: int = 5
    ) -> Tuple[str, List[DataSource], Optional[Dict[str, Any]]]:
        """
        Augment query with property JSON chunks only (excludes property_document chunks).
        This is Step 1 of the cascading fallback.
        
        Args:
            query: The buyer's enquiry
            listing_id: Listing ID to focus on
            n_results: Number of relevant chunks to retrieve
            
        Returns:
            Tuple of (augmented_context, data_sources, location_context)
        """
        # Retrieve property chunks EXCLUDING property_document chunks at retrieval time
        # This ensures property_document chunks don't dominate the results
        location_context = None
        
        if listing_id:
            from app.services.rag_pipeline.location_utils import detect_location_query, get_location_from_chunk
            is_location_query, _ = detect_location_query(query)
            
            if is_location_query:
                # For location queries, still exclude property_document chunks for JSON retrieval
                # We'll get location context but only from JSON chunks
                standard_results = self.retriever.retrieve(
                    query=query,
                    n_results=n_results,
                    listing_id=listing_id,
                    chunk_types=['overview', 'pricing', 'specifications', 'location', 'attributes', 'amenities']
                )
                # Extract location context from results
                for result in standard_results:
                    loc_ctx = get_location_from_chunk(result)
                    if loc_ctx:
                        location_context = loc_ctx
                        break
                results = standard_results
            else:
                # Standard retrieval - EXCLUDE property_document chunks
                results = self.retriever.retrieve(
                    query=query,
                    n_results=n_results,
                    listing_id=listing_id,
                    chunk_types=['overview', 'pricing', 'specifications', 'location', 'attributes', 'amenities']  # Explicitly exclude property_document
                )
        else:
            results = self.retriever.retrieve(
                query=query,
                n_results=n_results,
                listing_id=listing_id,
                chunk_types=['overview', 'pricing', 'specifications', 'location', 'attributes', 'amenities']  # Explicitly exclude property_document
            )
        
        # Additional filter as safety net (shouldn't be needed now, but keep for safety)
        # chunk_type is a top-level field, not in metadata
        json_results = [
            r for r in results
            if r.get('chunk_type') != 'property_document' and r.get('metadata', {}).get('chunk_type') != 'property_document'
        ][:n_results]  # Limit to n_results
        
        # Format retrieved context
        augmented_context, data_sources = self._format_property_context(
            results=json_results,
            location_context=location_context
        )
        
        return augmented_context, data_sources, location_context
    
    def augment_query_pdf_chunks(
        self,
        query: str,
        listing_id: str,
        n_results: int = 5
    ) -> Tuple[str, List[DataSource], Optional[Dict[str, Any]]]:
        """
        Augment query with property PDF chunks only (property_document chunks).
        This is Step 2 of the cascading fallback.
        
        Args:
            query: The buyer's enquiry
            listing_id: Listing ID to focus on
            n_results: Number of relevant chunks to retrieve
            
        Returns:
            Tuple of (augmented_context, data_sources, location_context)
        """
        # Use retriever's retrieve method with chunk_types filter to get property_document chunks
        # This uses the same logic as before (including reranking) but filters to property_document only
        from app.services.rag_pipeline.location_utils import detect_location_query
        is_location_query, _ = detect_location_query(query)
        
        print(f"\n🔍 augment_query_pdf_chunks called:")
        print(f"   Query: '{query}'")
        print(f"   Listing ID: {listing_id}")
        print(f"   Requesting {n_results} property_document chunks")
        
        # Retrieve property_document chunks using the retriever (includes reranking)
        pdf_results = self.retriever.retrieve(
            query=query,
            n_results=n_results,
            listing_id=listing_id,
            chunk_types=['property_document'],
            allow_hybrid=False  # Don't add other chunks, only property_document
        )
        
        print(f"✅ Retrieved {len(pdf_results)} PDF chunks:")
        for i, r in enumerate(pdf_results[:5]):  # Show first 5
            print(f"   [{i+1}] chunk_type={r.get('chunk_type', 'unknown')}, "
                  f"similarity={r.get('similarity', 0):.3f}, "
                  f"content_preview={r.get('content', '')[:100]}...")
        
        # For location queries, we still need location context
        location_context = None
        if is_location_query:
            # Get location context separately (from JSON chunks, not PDFs)
            _, location_context = self.retriever.retrieve_with_location_context(
                query=query,
                listing_id=listing_id,
                n_results=1  # Just need location, not content
            )
        
        # Format retrieved context
        augmented_context, data_sources = self._format_property_context(
            results=pdf_results,
            location_context=location_context
        )
        
        return augmented_context, data_sources, location_context
    
    def check_data_sufficiency(
        self,
        query: str,
        retrieved_context: str,
        data_sources: List[DataSource]
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if retrieved data is sufficient to answer the query.
        
        Args:
            query: Original query
            retrieved_context: Retrieved context
            data_sources: List of data sources used
            
        Returns:
            Tuple of (is_sufficient, reason_if_insufficient)
        """
        if not data_sources:
            return False, "No relevant property listing information found."
        
        query_lower = query.lower()
        context_lower = retrieved_context.lower()
        
        # Check price queries
        price_query = any(kw in query_lower for kw in PRICE_KEYWORDS)
        if price_query:
            if not any(indicator in context_lower for indicator in PRICE_INDICATORS):
                return False, "Price information not available in listing data."
      
        # Check specification queries
        if not price_query and any(kw in query_lower for kw in SPECIFICATION_KEYWORDS):
            if not any(kw in context_lower for kw in SPECIFICATION_KEYWORDS):
                return False, "Specification details not found in listing data."
        
        # Check location queries
        if any(kw in query_lower for kw in LOCATION_KEYWORDS):
            if 'address' not in context_lower and 'location' not in context_lower:
                return False, "Location information not found in listing data."
        
        # Check nearby properties queries
        if (any(kw in query_lower for kw in NEARBY_PROPERTY_KEYWORDS) and 
            any(kw in query_lower for kw in PROPERTY_ENTITY_KEYWORDS)):
            # If query is about nearby properties, check if we have that info
            if 'nearby properties' in context_lower or 'found 0 properties near' not in context_lower:
                return True, None  # We have data or LLM will handle it
        
        # Check amenity queries (schools, hospitals, etc.)
        # Amenity information is typically in property PDFs, not JSON chunks
        amenity_keywords = ['school', 'schools', 'hospital', 'hospitals', 'supermarket', 
                           'supermarkets', 'transport', 'bus', 'train', 'tram', 'station',
                           'park', 'parks', 'shopping', 'cafe', 'cafes', 'restaurant', 'restaurants']
        if any(kw in query_lower for kw in amenity_keywords):
            print(f"🔍 Amenity query detected in sufficiency check: query_lower='{query_lower}'")
            # Check if context contains ACTUAL amenity information (not just the keyword)
            # Look for patterns like "nearby schools:", "school is", "schools within", distances, etc.
            query_amenities = [kw for kw in amenity_keywords if kw in query_lower]
            print(f"   Query amenities: {query_amenities}")
            
            # Smart check: Look for amenity information patterns, not just keywords
            has_amenity_info = False
            for amenity in query_amenities:
                # Patterns that indicate ACTUAL amenity information
                amenity_info_patterns = [
                    f'nearby {amenity}',
                    f'{amenity} nearby',
                    f'{amenity} within',
                    f'{amenity} is ',
                    f'{amenity} are ',
                    f'{amenity}:',
                    f'{amenity} include',
                    f'close to {amenity}',
                    f'walking distance to {amenity}',
                    f'distance to {amenity}',
                    # Also check for singular/plural variants
                    f'nearby {amenity[:-1]}' if amenity.endswith('s') else f'nearby {amenity}s',
                ]
                if any(pattern in context_lower for pattern in amenity_info_patterns):
                    has_amenity_info = True
                    break
            
            print(f"   Context contains amenity info patterns? {has_amenity_info}")
            print(f"   Context preview: {context_lower[:300]}")
            if not has_amenity_info:
                print(f"   ❌ INSUFFICIENT: Amenity information not in JSON chunks (keyword found but no actual amenity data)")
                return False, f"Amenity information ({', '.join(query_amenities)}) not found in JSON chunks - should check property PDFs."
            else:
                print(f"   ✅ SUFFICIENT: Actual amenity info found in JSON chunks")
        
        # Check aerial view / view queries
        # View/aerial information is typically in property PDFs, not JSON chunks
        view_query_keywords = ['aerial view', 'aerial', 'bird eye', 'bird\'s eye', 'birds eye', 
                               'what does', 'what do', 'shows', 'show']
        # Only trigger for queries ASKING about aerial/view information (not just mentioning "view")
        is_view_query = ('aerial' in query_lower or 'bird' in query_lower or 
                        ('view' in query_lower and ('what' in query_lower or 'show' in query_lower or 'does' in query_lower)))
        
        if is_view_query:
            print(f"🔍 Aerial/view QUERY detected in sufficiency check: '{query_lower}'")
            
            # Check if this is a property_document chunk (PDF) - if so, be more lenient
            # Count how many sources are property_document vs other types
            pdf_chunk_count = 0
            json_chunk_count = 0
            for source in data_sources:
                # DataSource is a Pydantic model with chunk_type attribute
                source_chunk_type = source.chunk_type if hasattr(source, 'chunk_type') else None
                if source_chunk_type == 'property_document':
                    pdf_chunk_count += 1
                elif source_chunk_type in ['overview', 'pricing', 'specifications', 'location', 'attributes', 'amenities', 'bidding']:
                    json_chunk_count += 1
            
            # If we have ANY PDF chunks, treat as PDF check (be lenient)
            # If we have ONLY JSON chunks, treat as JSON check (be strict)
            is_pdf_chunk = pdf_chunk_count > 0
            print(f"   Debug: pdf_chunk_count={pdf_chunk_count}, json_chunk_count={json_chunk_count}, is_pdf_chunk={is_pdf_chunk}")
            
            if is_pdf_chunk:
                # For PDF chunks, be more lenient - if we have property document chunks, they likely contain relevant info
                # Check for property descriptions, layouts, surroundings that might answer aerial view questions
                property_description_patterns = [
                    'property', 'building', 'structure', 'layout', 'surrounding', 'neighborhood',
                    'courtyard', 'terrace', 'outdoor', 'garden', 'landscaped', 'location',
                    'adjacent', 'nearby', 'area', 'district', 'street', 'road'
                ]
                has_property_info = any(pattern in context_lower for pattern in property_description_patterns)
                print(f"   Context is from property PDF chunks")
                print(f"   Context contains property description info? {has_property_info}")
                print(f"   Context preview: {context_lower[:400]}")
                if not has_property_info:
                    print(f"   ❌ INSUFFICIENT: Property description information not found in PDF chunks")
                    return False, f"Property description information not found in PDF chunks."
                else:
                    print(f"   ✅ SUFFICIENT: Property PDF chunks contain relevant information (will let LLM determine if it answers aerial view question)")
                    return True, None
            else:
                # For JSON chunks, ALWAYS return False for aerial view queries
                # JSON chunks (overview, pricing, specifications, location) NEVER contain aerial view descriptions
                # Aerial view information is ONLY in property_document (PDF) chunks
                print(f"   Context is from JSON chunks (chunk_types: {[s.chunk_type for s in data_sources if hasattr(s, 'chunk_type')]})")
                print(f"   Context preview: {context_lower[:400]}")
                print(f"   ❌ INSUFFICIENT: JSON chunks never contain aerial view descriptions - must check property PDFs")
                return False, f"Aerial view information not found in JSON chunks - should check property PDFs."
        
        # Check property category queries
        if any(kw in query_lower for kw in PROPERTY_CATEGORY_KEYWORDS):
            return True, None
        
        # 🚨 STRICT SUFFICIENCY CHECK - DEFAULT TO INSUFFICIENT
        # Only mark as sufficient if we can PROVE the JSON chunks contain the answer
        # This ensures the full cascade: JSON → Property PDFs → Generic PDFs → Fallback
        
        # Check if the query keywords appear in the context
        # Extract meaningful keywords from the query (excluding stop words)
        stop_words = {'what', 'is', 'the', 'are', 'does', 'do', 'can', 'you', 'tell', 'me', 
                     'about', 'show', 'of', 'in', 'on', 'at', 'to', 'for', 'a', 'an', 'this',
                     'that', 'these', 'those', 'property', 'listing'}
        query_words = [w.lower() for w in query_lower.split() if w.lower() not in stop_words and len(w) > 2]
        
        # Check if at least SOME query keywords appear in the context
        if query_words:
            matching_words = [w for w in query_words if w in context_lower]
            match_ratio = len(matching_words) / len(query_words)
            
            print(f"🔍 Sufficiency check: {len(matching_words)}/{len(query_words)} query keywords found in context (ratio: {match_ratio:.2f})")
            print(f"   Query keywords: {query_words[:10]}")  # Show first 10
            print(f"   Matching keywords: {matching_words[:10]}")  # Show first 10
            
            # Require at least 30% of query keywords to be in the context
            if match_ratio < 0.3:
                print(f"   ❌ INSUFFICIENT: Low keyword match ratio ({match_ratio:.2f} < 0.3)")
                return False, f"JSON chunks don't contain enough relevant keywords to answer the query - should check property PDFs."
        
        # If we reach here, the context seems relevant
        print(f"   ✅ SUFFICIENT: JSON chunks appear to contain relevant information")
        return True, None
    
    def _augment_generic_query(
        self,
        query: str,
        n_results: int = 5
    ) -> Tuple[str, List[DataSource], None]:
        """
        Augment query with generic knowledge (legislation, buyer guides, etc.)
        
        Args:
            query: User's question
            n_results: Number of chunks to retrieve
            
        Returns:
            Tuple of (context_string, data_sources, None)
        """
        # Check if store has data first
        stats = self.generic_store.get_stats()
        total_chunks = stats.get('total_chunks', 0)
        
        if total_chunks == 0:
            print("⚠️  Generic knowledge store is EMPTY - no documents have been ingested")
            print("   Run: python app/helpers/ingestion_pipeline/generic/sync_generic_pdfs.py to ingest PDFs")
            return ("",  # Empty context string to indicate no results
                   [],  # Empty data sources
                   None)
        
        print(f"🔍 Searching generic knowledge store (has {total_chunks} chunks) for: '{query}'")
        
        # DEBUG: Check if AML content exists in the store
        if 'aml' in query.lower() or 'anti-money laundering' in query.lower():
            debug_query = text("""
                SELECT COUNT(*) 
                FROM generic_knowledge
                WHERE 
                    LOWER(content) LIKE '%aml%' OR
                    LOWER(content) LIKE '%anti-money laundering%' OR
                    LOWER(content) LIKE '%anti money laundering%'
            """)
            try:
                result = self.generic_store.db_session.execute(debug_query)
                aml_count = result.scalar()
                print(f"   🔍 DEBUG: Found {aml_count} chunks containing 'aml' or 'anti-money laundering' in content")
                
                # Also show a sample if found
                if aml_count > 0:
                    sample_query = text("""
                        SELECT LEFT(content, 150) as preview
                        FROM generic_knowledge
                        WHERE 
                            LOWER(content) LIKE '%aml%' OR
                            LOWER(content) LIKE '%anti-money laundering%' OR
                            LOWER(content) LIKE '%anti money laundering%'
                        LIMIT 1
                    """)
                    sample_result = self.generic_store.db_session.execute(sample_query)
                    sample_row = sample_result.fetchone()
                    if sample_row:
                        print(f"   🔍 DEBUG Sample: {sample_row[0]}...")
            except Exception as e:
                print(f"   ⚠️  DEBUG check failed: {e}")
        
        # Normalize query to fix common typos
        normalized_query = query
        # Fix common typos
        normalized_query = normalized_query.replace('requiremnts', 'requirements')
        normalized_query = normalized_query.replace('requiremnt', 'requirement')
        normalized_query = normalized_query.replace('requirments', 'requirements')
        normalized_query = normalized_query.replace('requirment', 'requirement')
        
        # Expand query for better matching (e.g., "aml" -> "anti-money laundering", "licensing" -> variations)
        expanded_query = normalized_query
        query_lower = normalized_query.lower()
        
        # AML expansion
        if 'aml' in query_lower and 'anti-money laundering' not in query_lower:
            # Expand "aml" to "anti-money laundering" for better semantic matching
            expanded_query = normalized_query.replace('aml', 'anti-money laundering').replace('AML', 'anti-money laundering')
            print(f"   Normalized query: '{query}' → '{normalized_query}'")
            print(f"   Expanded query: '{normalized_query}' → '{expanded_query}'")
        elif 'anti-money laundering' in query_lower and 'aml' not in query_lower:
            # Also search with "aml" abbreviation
            expanded_query = normalized_query.replace('anti-money laundering', 'aml anti-money laundering')
            print(f"   Normalized query: '{query}' → '{normalized_query}'")
            print(f"   Expanded query: '{normalized_query}' → '{expanded_query}'")
        
        # Licensing expansion
        elif 'licensing' in query_lower or 'license' in query_lower or 'licence' in query_lower:
            # Expand licensing queries to include variations
            expanded_query = f"{normalized_query} victorian estate agent license qualification certificate IV real estate"
            print(f"   Normalized query: '{query}' → '{normalized_query}'")
            print(f"   Expanded query for licensing: '{normalized_query}' → '{expanded_query}'")
        
        # Penalties/violations expansion
        elif 'penalt' in query_lower or 'violation' in query_lower or 'breach' in query_lower or 'fine' in query_lower:
            # Expand penalties queries to include variations
            expanded_query = f"{normalized_query} estate agents act penalties fines breaches trust account underquoting"
            print(f"   Normalized query: '{query}' → '{normalized_query}'")
            print(f"   Expanded query for penalties: '{normalized_query}' → '{expanded_query}'")
        
        elif normalized_query != query:
            print(f"   Normalized query: '{query}' → '{normalized_query}'")
        
        # Search generic knowledge store with expanded query
        # Use a higher n_results to ensure we get results even if similarity is low
        results = self.generic_store.search(expanded_query, n_results=max(n_results, 10))
        
        # Debug: Print similarity scores
        if results:
            print(f"✅ Found {len(results)} results from generic knowledge store")
            for i, result in enumerate(results[:3], 1):  # Show top 3
                sim = result.get('similarity', 0.0)
                content_preview = result.get('content', '')[:100]
                print(f"   Result {i}: similarity={sim:.4f}, preview='{content_preview}...'")
        else:
            print(f"⚠️  Generic knowledge store returned no results for query: '{expanded_query}'")
            print(f"   Store has {total_chunks} chunks but none matched the query")
            
            # Try fallback queries in order of specificity
            fallback_queries = []
            
            # 1. Remove question mark
            simple_query = expanded_query.rstrip('?').strip()
            if simple_query != expanded_query:
                fallback_queries.append(simple_query)
            
            # 2. For AML queries, try just "anti-money laundering requirements"
            if 'anti-money laundering' in expanded_query.lower() or 'aml' in query_lower:
                fallback_queries.append('anti-money laundering requirements')
                fallback_queries.append('aml requirements')
                fallback_queries.append('anti-money laundering')
            
            # 2b. For licensing queries, try variations
            if 'licens' in query_lower:  # Catches license/licence/licensing
                fallback_queries.append('estate agent license requirements')
                fallback_queries.append('real estate agent licensing')
                fallback_queries.append('Victorian estate agent licence')
                fallback_queries.append('certificate IV real estate')
                fallback_queries.append('agent representative registration')
            
            # 2c. For penalties queries, try variations
            if 'penalt' in query_lower or 'violation' in query_lower or 'fine' in query_lower:
                fallback_queries.append('estate agent penalties')
                fallback_queries.append('penalties for breaches')
                fallback_queries.append('trust account violations')
                fallback_queries.append('underquoting penalties')
                fallback_queries.append('fines for agents')
            
            # 3. Try the normalized query without expansion
            if normalized_query != expanded_query:
                fallback_queries.append(normalized_query)
            
            # Try each fallback query
            for fallback_query in fallback_queries:
                print(f"   Trying fallback query: '{fallback_query}'")
                results = self.generic_store.search(fallback_query, n_results=n_results)
                if results:
                    print(f"✅ Found {len(results)} results with fallback query: '{fallback_query}'")
                    for i, result in enumerate(results[:3], 1):
                        sim = result.get('similarity', 0.0)
                        content_preview = result.get('content', '')[:100]
                        print(f"   Result {i}: similarity={sim:.4f}, preview='{content_preview}...'")
                    break  # Use first successful fallback
        
        # Check if licensing query got relevant results
        print(f"🔍 DEBUG: Checking if licensing query needs verification (results={len(results) if results else 0}, query_lower has 'licens'={('licens' in query_lower)})")
        if results and 'licens' in query_lower:
            print(f"   🔍 Verifying licensing content in {len(results)} results...")
            # Verify that the results actually contain licensing information
            combined_content = ' '.join([r.get('content', '').lower() for r in results])
            print(f"   🔍 Combined content length: {len(combined_content)} chars")
            # Use SPECIFIC licensing terms that only appear in the actual licensing requirements chunk
            # "Estate Agents Act" is too broad - appears in many general chunks
            specific_licensing_terms = [
                'certificate iv', 'agent\'s representative', 'licensing and registration',
                'victorian estate agent\'s licence', 'agents representative', 'certificate of registration'
            ]
            matching_terms = [term for term in specific_licensing_terms if term in combined_content]
            print(f"   🔍 Matching SPECIFIC licensing terms found: {matching_terms if matching_terms else 'NONE'}")
            # Require at least ONE specific term (not just "estate agents act")
            has_licensing_info = len(matching_terms) > 0
            if not has_licensing_info:
                print(f"   ⚠️  Results don't contain specific licensing information - triggering keyword fallback")
                results = []  # Clear results to trigger keyword fallback
            else:
                print(f"   ✅ Results contain licensing information - using vector search results")
        
        if not results:
            # FALLBACK: If vector search fails for specific topics, use keyword search
            # AML fallback
            if 'aml' in query_lower or 'anti-money laundering' in query_lower:
                print(f"   ⚠️  Vector search failed, trying keyword-based fallback for AML query")
                keyword_query = text("""
                    SELECT 
                        id,
                        doc_category,
                        chunk_index,
                        content,
                        metadata,
                        0.5 as similarity
                    FROM generic_knowledge
                    WHERE 
                        LOWER(content) LIKE '%aml%' OR
                        LOWER(content) LIKE '%anti-money laundering%' OR
                        LOWER(content) LIKE '%anti money laundering%'
                    ORDER BY 
                        CASE 
                            WHEN LOWER(content) LIKE '%requirement%' THEN 1
                            WHEN LOWER(content) LIKE '%aml%' THEN 2
                            ELSE 3
                        END,
                        chunk_index
                    LIMIT :limit_count
                """)
                try:
                    keyword_result = self.generic_store.db_session.execute(
                        keyword_query, 
                        {'limit_count': n_results}
                    )
                    keyword_rows = keyword_result.fetchall()
                    
                    if keyword_rows:
                        print(f"   ✅ Keyword fallback found {len(keyword_rows)} chunks")
                        # Format the keyword results the same way as vector search results
                        results = []
                        for row in keyword_rows:
                            # Handle metadata - it might be a dict or JSONB
                            metadata = row[4]
                            if hasattr(metadata, 'copy'):
                                metadata = metadata.copy()
                            elif isinstance(metadata, dict):
                                metadata = metadata
                            else:
                                # Try to parse if it's a string
                                try:
                                    import json
                                    if isinstance(metadata, str):
                                        metadata = json.loads(metadata)
                                    else:
                                        metadata = {}
                                except:
                                    metadata = {}
                            
                            results.append({
                                'id': str(row[0]),
                                'doc_category': row[1],
                                'chunk_index': row[2],
                                'content': str(row[3]),
                                'metadata': metadata,
                                'similarity': 0.5  # Fixed similarity for keyword matches
                            })
                        print(f"   ✅ Formatted {len(results)} keyword results")
                    else:
                        print(f"   ⚠️  Keyword fallback also returned no results")
                except Exception as e:
                    print(f"   ⚠️  Keyword fallback failed: {e}")
            
            # Licensing fallback
            elif 'licens' in query_lower:  # Catches license/licence/licensing
                print(f"   ⚠️  Vector search failed, trying keyword-based fallback for licensing query")
                keyword_query = text("""
                    SELECT 
                        id,
                        doc_category,
                        chunk_index,
                        content,
                        metadata,
                        0.5 as similarity
                    FROM generic_knowledge
                    WHERE 
                        LOWER(content) LIKE '%licensing%' OR
                        LOWER(content) LIKE '%license%' OR
                        LOWER(content) LIKE '%licence%' OR
                        LOWER(content) LIKE '%certificate iv%' OR
                        LOWER(content) LIKE '%estate agents act%'
                    ORDER BY 
                        CASE 
                            WHEN LOWER(content) LIKE '%licensing and registration%' THEN 1
                            WHEN LOWER(content) LIKE '%license requirement%' THEN 2
                            WHEN LOWER(content) LIKE '%estate agent%' AND LOWER(content) LIKE '%license%' THEN 3
                            ELSE 4
                        END,
                        chunk_index
                    LIMIT :limit_count
                """)
                try:
                    keyword_result = self.generic_store.db_session.execute(
                        keyword_query, 
                        {'limit_count': n_results}
                    )
                    keyword_rows = keyword_result.fetchall()
                    
                    if keyword_rows:
                        print(f"   ✅ Keyword fallback found {len(keyword_rows)} chunks")
                        # Format the keyword results the same way as vector search results
                        results = []
                        for row in keyword_rows:
                            # Handle metadata - it might be a dict or JSONB
                            metadata = row[4]
                            if hasattr(metadata, 'copy'):
                                metadata = metadata.copy()
                            elif isinstance(metadata, dict):
                                metadata = metadata
                            else:
                                # Try to parse if it's a string
                                try:
                                    import json
                                    if isinstance(metadata, str):
                                        metadata = json.loads(metadata)
                                    else:
                                        metadata = {}
                                except:
                                    metadata = {}
                            
                            results.append({
                                'id': str(row[0]),
                                'doc_category': row[1],
                                'chunk_index': row[2],
                                'content': str(row[3]),
                                'metadata': metadata,
                                'similarity': 0.5  # Fixed similarity for keyword matches
                            })
                        print(f"   ✅ Formatted {len(results)} keyword results for licensing")
                    else:
                        print(f"   ⚠️  Keyword fallback also returned no results")
                except Exception as e:
                    print(f"   ⚠️  Keyword fallback failed: {e}")
            
            if not results:
                return ("",  # Empty context string to indicate no results
                       [],  # Empty data sources
                       None)
        
        print(f"✅ Found {len(results)} results from generic knowledge store")
        
        # Format context
        context_parts = []
        data_sources = []
        
        for idx, result in enumerate(results, 1):
            content = result['content']
            metadata = result.get('metadata', {})
            category = result.get('doc_category', DEFAULT_CATEGORY)
            
            context_parts.append(f"[Source {idx} - {category}]\n{content}\n")
            
            data_sources.append(DataSource(
                chunk_type=category,
                listing_id=None,  # Generic queries don't have a listing_id
                similarity_score=result.get('similarity', 0.0),
                content_preview=content[:CONTENT_PREVIEW_LENGTH]
            ))
        
        context = "\n".join(context_parts)
        
        return context, data_sources, None
    
   
    def _retrieve_property_data(
        self,
        query: str,
        listing_id: Optional[str],
        n_results: int
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Retrieve property data based on query type.
        
        Args:
            query: User's query
            listing_id: Optional listing ID
            n_results: Number of results to retrieve
            
        Returns:
            Tuple of (results, location_context)
        """
        location_context = None
        
        if listing_id:
            from app.services.rag_pipeline.location_utils import detect_location_query
            is_location_query, _ = detect_location_query(query)
            
            if is_location_query:
                results, location_context = self.retriever.retrieve_with_location_context(
                    query=query,
                    listing_id=listing_id,
                    n_results=n_results
                )
            else:
                # Standard retrieval
                results = self.retriever.retrieve(
                    query=query,
                    n_results=n_results,
                    listing_id=listing_id
                )
        else:
            # Standard retrieval without listing scope
            results = self.retriever.retrieve(
                query=query,
                n_results=n_results,
                listing_id=listing_id
            )
        
        return results, location_context
    
    def _calculate_similarity(self, distance: Optional[float]) -> Optional[float]:
        """
        Calculate similarity score from distance.
        
        Args:
            distance: Distance value (lower is better)
            
        Returns:
            Similarity score (higher is better) or None
        """
        if distance is not None:
            return 1.0 - distance
        return None
    
    def _create_property_data_source(
        self,
        content: str,
        chunk_type: str,
        listing_id: str,
        similarity: Optional[float]
    ) -> DataSource:
        """
        Create a DataSource object for property data.
        
        Args:
            content: Chunk content
            chunk_type: Type of chunk
            listing_id: Listing ID
            similarity: Similarity score
            
        Returns:
            DataSource object
        """
        preview = content[:CONTENT_PREVIEW_LENGTH]
        if len(content) > CONTENT_PREVIEW_LENGTH:
            preview += "..."
        
        return DataSource(
            chunk_type=chunk_type,
            listing_id=listing_id,
            content_preview=preview,
            similarity_score=similarity
        )
    
    def _format_property_context(
        self,
        results: List[Dict[str, Any]],
        location_context: Optional[Dict[str, Any]]
    ) -> Tuple[str, List[DataSource]]:
        """
        Format property retrieval results into context string and data sources.
        
        Args:
            results: List of retrieval results
            location_context: Optional location context
            
        Returns:
            Tuple of (formatted_context, data_sources)
        """
        context_parts = []
        data_sources = []
        
        # Group chunks by listing for better organization
        listings_data = {}
        for result in results:
            content = result.get('content', '')
            metadata = result.get('metadata', {})
            # chunk_type is a top-level field from the database, not in metadata
            chunk_type = result.get('chunk_type') or metadata.get('chunk_type') or DEFAULT_CHUNK_TYPE
            listing_id_from_chunk = result.get('listing_id') or metadata.get('listing_id') or DEFAULT_LISTING_ID
            distance = result.get('distance')
            similarity = self._calculate_similarity(distance)
            
            # Group by listing
            if listing_id_from_chunk not in listings_data:
                listings_data[listing_id_from_chunk] = []
            listings_data[listing_id_from_chunk].append({
                'chunk_type': chunk_type,
                'content': content,
                'similarity': similarity
            })
            
            # Track data source
            data_sources.append(
                self._create_property_data_source(
                    content=content,
                    chunk_type=chunk_type,
                    listing_id=listing_id_from_chunk,
                    similarity=similarity
                )
            )
        
        # Format context by listing for clarity
        for listing_id_key, chunks in listings_data.items():
            listing_display = listing_id_key[:LISTING_ID_DISPLAY_LENGTH] + "..."
            context_parts.append(f"=== PROPERTY LISTING: {listing_display} ===")
            for chunk in chunks:
                context_parts.append(f"\n[{chunk['chunk_type'].upper()}]")
                context_parts.append(chunk['content'])
                context_parts.append("")  
            context_parts.append("") 
        
        if location_context:
            context_parts.append("\n" + location_context['formatted_context'])
        
        augmented_context = "\n".join(context_parts)
        
        return augmented_context, data_sources

