"""
Data formatting utilities for property listings.

This module converts raw listing data (from database or JSON) into a
normalized format suitable for the chunking pipeline.
"""
from typing import List, Dict, Any


def extract_amenity_names(listing: Dict[str, Any]) -> List[str]:
    """
    Extract amenity names from listing.
    
    Args:
        listing: Raw listing dictionary
        
    Returns:
        List of amenity names
    """
    amenities = listing.get('propertyAmenities') or []
    return [a.get('name', '') for a in amenities if isinstance(a, dict)]


def extract_inspection_times(listing: Dict[str, Any]) -> List[str]:
    """
    Extract and format inspection times from listing.
    
    Args:
        listing: Raw listing dictionary
        
    Returns:
        List of formatted inspection times (e.g., "2024-01-15 10:00 to 11:00")
    """
    inspections = listing.get('openInspections') or []
    inspection_times = []
    for insp in inspections:
        if isinstance(insp, dict):
            start = insp.get('inspectionStartTime', '')
            end = insp.get('inspectionEndTime', '')
            if start and end:
                inspection_times.append(f"{start} to {end}")
    return inspection_times


def extract_agent_names(listing: Dict[str, Any]) -> List[str]:
    """
    Extract agent full names from listing.
    
    Args:
        listing: Raw listing dictionary
        
    Returns:
        List of agent names
    """
    agents = listing.get('propertyAgents') or []
    return [a.get('fullName', '') for a in agents if isinstance(a, dict)]


def extract_highest_bid_amount(listing: Dict[str, Any]) -> Any:
    """
    Extract highest bid amount from listing.
    
    Args:
        listing: Raw listing dictionary
        
    Returns:
        Highest bid amount (number) or None
    """
    highest_bid = listing.get('highestBid')
    return highest_bid.get('bidAmount') if highest_bid and isinstance(highest_bid, dict) else None


def format_listing_for_chunking(listing: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format a listing dictionary for chunking.
    
    Normalizes raw listing data from database queries or JSON files into a
    consistent structure that the PropertyListingChunker expects.
    
    Args:
        listing: Raw listing dictionary from database or JSON
        
    Returns:
        Formatted listing dictionary with normalized fields
        
    Example:
        >>> raw_listing = fetch_from_database()
        >>> formatted = format_listing_for_chunking(raw_listing)
        >>> chunks = chunker.chunk_listing(formatted)
    """
    location = listing.get('location', {})
    # Handle both nested propertyAttributes (from JSON) and top-level attributes (from database)
    attrs = listing.get('propertyAttributes', {})
    if not attrs:
        # If propertyAttributes is empty, check if attributes are at top level (from database query)
        attrs = listing
    
    formatted = {
        'id': listing.get('id', ''),
        'slug': listing.get('slug', ''),
        'propertyId': listing.get('propertyId', ''),
        
        'title': listing.get('title', ''),
        'description': listing.get('description', ''),
        'propertyCategory': listing.get('propertyCategory', ''),
        'propertyType': listing.get('propertyType', '') or listing.get('propertyTypeName', ''),
        
        'listingType': listing.get('listingType', ''),
        'listingStatus': listing.get('listingStatus', ''),
        'auctionStatus': listing.get('auctionStatus', ''),
        
        'location': location.get('displayAddress', '') if isinstance(location, dict) else (listing.get('displayAddress', '') or listing.get('location', '')),
        'streetAddress': location.get('streetAddress', '') if isinstance(location, dict) else listing.get('streetAddress', ''),
        'suburb': location.get('suburb', '') if isinstance(location, dict) else listing.get('suburb', ''),
        'city': location.get('city', '') if isinstance(location, dict) else listing.get('city', ''),
        'state': location.get('state', '') if isinstance(location, dict) else listing.get('state', ''),
        'postalCode': location.get('postalCode', '') if isinstance(location, dict) else listing.get('postalCode', ''),
        'latitude': location.get('latitude') if isinstance(location, dict) else listing.get('latitude'),
        'longitude': location.get('longitude') if isinstance(location, dict) else listing.get('longitude'),
        
        'price': listing.get('price'),
        'displayPrice': listing.get('displayPrice', False),
        'auctionStartPrice': listing.get('auctionStartPrice'),
        'auctionStartDate': listing.get('auctionStartDate'),
        # 'auctionEndDate': listing.get('auctionEndDate'),
        
        'publishedAt': listing.get('publishedAt'),
        'allowPrivateInspection': listing.get('allowPrivateInspection', False),
        
        # Get attributes from nested propertyAttributes OR top-level (database format)
        # Note: 0 is a valid value, so we check for None explicitly
        'bedrooms': attrs.get('bedrooms') if attrs.get('bedrooms') is not None else listing.get('bedrooms'),
        'bathrooms': attrs.get('bathrooms') if attrs.get('bathrooms') is not None else listing.get('bathrooms'),
        'toilets': attrs.get('toilets') if attrs.get('toilets') is not None else listing.get('toilets'),
        'garages': attrs.get('garages') if attrs.get('garages') is not None else listing.get('garages'),
        'ensuites': attrs.get('ensuites') if attrs.get('ensuites') is not None else listing.get('ensuites'),
        'landArea': attrs.get('landArea') if attrs.get('landArea') is not None else listing.get('landArea'),
        'landAreaUnit': attrs.get('landAreaUnit', '') or listing.get('landAreaUnit', ''),
        'floorArea': attrs.get('floorArea') if attrs.get('floorArea') is not None else listing.get('floorArea'),
        'floorAreaUnit': attrs.get('floorAreaUnit', '') or listing.get('floorAreaUnit', ''),
        'frontage': attrs.get('frontage') if attrs.get('frontage') is not None else listing.get('frontage'),
        'frontageUnit': attrs.get('frontageUnit', '') or listing.get('frontageUnit', ''),
        'yearBuilt': attrs.get('yearBuilt') if attrs.get('yearBuilt') is not None else listing.get('yearBuilt'),
        'propertyAge': attrs.get('propertyAge', '') or listing.get('propertyAge', ''),
        'energyRating': attrs.get('energyRating') if attrs.get('energyRating') is not None else listing.get('energyRating'),
        'zoning': attrs.get('zoning', '') or listing.get('zoning', ''),
        'highlights': attrs.get('highlights', []) or listing.get('highlights', []),
        
        'amenities': extract_amenity_names(listing),
        'inspectionTimes': extract_inspection_times(listing),
        'agents': extract_agent_names(listing),
        
        'activeOfferCount': listing.get('activeOfferCount', 0),
        'activeBidCount': listing.get('activeBidCount', 0),
        'highestBidAmount': extract_highest_bid_amount(listing),
        'winningBid': listing.get('winningBid'),
        
        'saleHistory': listing.get('saleHistory'),
        
        'reverseAuctionNextDecreaseAt': listing.get('reverseAuctionNextDecreaseAt'),
        'reverseAuctionDecreaseAmount': listing.get('reverseAuctionDecreaseAmount'),
        
        'propertyMedia': listing.get('propertyMedia', []),
    }
    
    return formatted

