"""
Augmentation module for enriching queries with retrieved context.
"""
from typing import List, Dict, Any, Optional, Tuple
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
SPECIFICATION_KEYWORDS = ['bedroom', 'bathroom', 'garage']
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
        # Get all property chunks, then filter out property_document chunks
        all_results, location_context = self._retrieve_property_data(
            query=query,
            listing_id=listing_id,
            n_results=n_results * 2  # Get more to filter
        )
        
        # Filter to exclude property_document chunks
        json_results = [
            r for r in all_results
            if r.get('metadata', {}).get('chunk_type') != 'property_document'
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
        
        # Retrieve property_document chunks using the retriever (includes reranking)
        pdf_results = self.retriever.retrieve(
            query=query,
            n_results=n_results,
            listing_id=listing_id,
            chunk_types=['property_document'],
            allow_hybrid=False  # Don't add other chunks, only property_document
        )
        
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
        
        # Check property category queries
        if any(kw in query_lower for kw in PROPERTY_CATEGORY_KEYWORDS):
            return True, None
        
        # If we have some data sources, consider it sufficient
        # The LLM will handle cases where information is partial
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
        
        # Search generic knowledge store
        results = self.generic_store.search(query, n_results=n_results)
        
        if not results:
            print(f"⚠️  Generic knowledge store returned no results for query: '{query}'")
            print(f"   Store has {total_chunks} chunks but none matched the query")
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
            chunk_type = metadata.get('chunk_type', DEFAULT_CHUNK_TYPE)
            listing_id_from_chunk = metadata.get('listing_id', DEFAULT_LISTING_ID)
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

