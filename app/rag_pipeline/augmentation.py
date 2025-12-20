"""
Augmentation module for enriching queries with retrieved context.
"""
from typing import List, Dict, Any, Optional, Tuple
from app.rag_pipeline.retrieval import PropertyRetriever
from app.rag_pipeline.schemas import DataSource


class QueryAugmenter:
    """
    Augments buyer enquiries with relevant property listing information.
    """
    
    def __init__(
        self,
        retriever: Optional[PropertyRetriever] = None,
        collection_name: str = "property_listings",
        persist_directory: str = "./chroma_db"
    ):
        """
        Initialize the query augmenter.
        
        Args:
            retriever: Optional pre-initialized retriever
            collection_name: Name of the ChromaDB collection
            persist_directory: Directory where ChromaDB data is persisted
        """
        if retriever is None:
            self.retriever = PropertyRetriever(
                collection_name=collection_name,
                persist_directory=persist_directory
            )
        else:
            self.retriever = retriever
    
    def augment_query(
        self,
        query: str,
        listing_id: Optional[str] = None,
        n_results: int = 5
    ) -> Tuple[str, List[DataSource], Optional[Dict[str, Any]]]:
        """
        Augment a query with relevant retrieved context.
        Includes location-aware context for nearby queries.
        
        Args:
            query: The buyer's enquiry
            listing_id: Optional listing ID to focus on
            n_results: Number of relevant chunks to retrieve
            
        Returns:
            Tuple of (augmented_context, data_sources, location_context)
            location_context includes nearby_properties_json for API response
        """
        # Check if this is a location-based query and we have a listing_id
        location_context = None
        if listing_id:
            from app.rag_pipeline.location_utils import detect_location_query
            is_location_query, _ = detect_location_query(query)
            
            if is_location_query:
                # Use location-aware retrieval
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
        
        # Format retrieved context in a clear, structured way
        context_parts = []
        data_sources = []
        
        # Group chunks by listing for better organization
        listings_data = {}
        for result in results:
            content = result.get('content', '')
            metadata = result.get('metadata', {})
            chunk_type = metadata.get('chunk_type', 'unknown')
            listing_id_from_chunk = metadata.get('listing_id', 'unknown')
            distance = result.get('distance')
            similarity = 1.0 - distance if distance is not None else None
            
            # Group by listing
            if listing_id_from_chunk not in listings_data:
                listings_data[listing_id_from_chunk] = []
            listings_data[listing_id_from_chunk].append({
                'chunk_type': chunk_type,
                'content': content,
                'similarity': similarity
            })
            
            # Track data source
            data_sources.append(DataSource(
                chunk_type=chunk_type,
                listing_id=listing_id_from_chunk,
                content_preview=content[:200] + "..." if len(content) > 200 else content,
                similarity_score=similarity
            ))
        
        # Format context by listing for clarity
        for listing_id_key, chunks in listings_data.items():
            context_parts.append(f"=== PROPERTY LISTING: {listing_id_key[:20]}... ===")
            for chunk in chunks:
                context_parts.append(f"\n[{chunk['chunk_type'].upper()}]")
                context_parts.append(chunk['content'])
                context_parts.append("")  # Empty line
            context_parts.append("")  # Extra line between listings
        
        # Add location context if available
        if location_context:
            context_parts.append("\n" + location_context['formatted_context'])
        
        augmented_context = "\n".join(context_parts)
        
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
        # If no data sources, insufficient
        if not data_sources:
            return False, "No relevant property listing information found."
        
        # Check if query asks for specific information that might be missing
        query_lower = query.lower()
        context_lower = retrieved_context.lower()
        
        # Price-related queries - be more lenient, check for any pricing indicators
        price_query = any(kw in query_lower for kw in ['price', 'cost', 'how much'])
        if price_query:
            # Check for various price indicators
            price_indicators = ['price', '$', 'asking', 'auction', 'bid', 'offer', 'sale']
            if not any(indicator in context_lower for indicator in price_indicators):
                return False, "Price information not available in listing data."
        
        # Specification queries
        # Skip strict spec check if we already treated it as a price query
        if not price_query and any(kw in query_lower for kw in ['bedroom', 'bathroom', 'garage']):
            if not any(kw in context_lower for kw in ['bedroom', 'bathroom', 'garage']):
                return False, "Specification details not found in listing data."
        
        # Location queries
        if any(kw in query_lower for kw in ['where', 'location', 'address', 'suburb']):
            if 'address' not in context_lower and 'location' not in context_lower:
                return False, "Location information not found in listing data."
        
        # Auction/bidding queries
        if any(kw in query_lower for kw in ['auction', 'bid', 'bidding']):
            if 'auction' not in context_lower and 'bid' not in context_lower:
                return False, "Auction/bidding information not found in listing data."
        
        # If we have some data sources, consider it sufficient
        # The LLM will handle cases where information is partial
        return True, None

