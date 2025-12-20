"""
Preprocessing module for buyer enquiries.
Extracts listing IDs, normalizes queries, and prepares for retrieval.
"""
import re
from typing import Dict, Optional, Any
from app.rag_pipeline.schemas import BuyerEnquiry


def extract_listing_id(query: str) -> Optional[str]:
    """
    Extract listing ID from query if present.
    Looks for UUID patterns or explicit listing ID mentions.
    
    Args:
        query: The buyer's enquiry text
        
    Returns:
        Listing ID if found, None otherwise
    """
    # UUID pattern (8-4-4-4-12 format)
    uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    matches = re.findall(uuid_pattern, query, re.IGNORECASE)
    if matches:
        return matches[0]
    
    # Look for "listing" or "property" followed by ID
    listing_pattern = r'(?:listing|property)\s*(?:id|#)?\s*:?\s*([0-9a-f-]{36})'
    match = re.search(listing_pattern, query, re.IGNORECASE)
    if match:
        return match.group(1)
    
    return None


def normalize_query(query: str) -> str:
    """
    Normalize the query for better retrieval.
    
    Args:
        query: Raw query text
        
    Returns:
        Normalized query
    """
    # Remove extra whitespace
    query = ' '.join(query.split())
    
    # Remove listing ID if present (we'll handle it separately)
    query = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '', query, flags=re.IGNORECASE)
    
    # Clean up
    query = ' '.join(query.split())
    
    return query.strip()


def preprocess_enquiry(enquiry: BuyerEnquiry) -> Dict[str, any]:
    """
    Preprocess a buyer enquiry for retrieval and generation.
    
    Args:
        enquiry: BuyerEnquiry object
        
    Returns:
        Dictionary with preprocessed data:
        - normalized_query: Cleaned query text
        - listing_id: Extracted or provided listing ID
        - original_query: Original query text
        - user_context: User/session information
    """
    # Extract listing ID from query if not provided
    listing_id = enquiry.listing_id
    if not listing_id:
        listing_id = extract_listing_id(enquiry.question)
    
    # Normalize query
    normalized_query = normalize_query(enquiry.question)
    
    return {
        "normalized_query": normalized_query,
        "listing_id": listing_id,
        "original_query": enquiry.question,
        "user_id": enquiry.user_id,
        "session_id": enquiry.session_id,
    }


def detect_enquiry_type(query: str) -> str:
    """
    Detect the type of enquiry for better routing.
    
    Args:
        query: The enquiry text
        
    Returns:
        Enquiry type: 'price', 'specifications', 'location', 'bidding', 'general'
    """
    query_lower = query.lower()
    
    price_keywords = ['price', 'cost', 'how much', 'asking', 'offer']
    specs_keywords = ['bedroom', 'bathroom', 'garage', 'area', 'feature', 'amenity', 'pool']
    location_keywords = ['location', 'address', 'where', 'suburb', 'city', 'inspection']
    bidding_keywords = ['bid', 'bidding', 'auction', 'how to bid', 'offer']
    
    if any(kw in query_lower for kw in price_keywords):
        return 'price'
    elif any(kw in query_lower for kw in specs_keywords):
        return 'specifications'
    elif any(kw in query_lower for kw in location_keywords):
        return 'location'
    elif any(kw in query_lower for kw in bidding_keywords):
        return 'bidding'
    else:
        return 'general'
