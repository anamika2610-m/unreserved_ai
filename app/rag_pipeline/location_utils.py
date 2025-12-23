"""
Location utilities for geospatial queries and distance calculations.
"""

import math
from typing import Dict, List, Tuple, Any, Optional


def haversine_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float
) -> float:
    """
    Calculate the great circle distance between two points on Earth.
    
    Args:
        lat1: Latitude of point 1 (in degrees)
        lon1: Longitude of point 1 (in degrees)
        lat2: Latitude of point 2 (in degrees)
        lon2: Longitude of point 2 (in degrees)
        
    Returns:
        Distance in kilometers
    """
    # Convert decimal degrees to radians
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    # Haversine formula
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2)
    c = 2 * math.asin(math.sqrt(a))
    
    # Radius of Earth in kilometers
    r = 6371.0
    
    return c * r


def get_location_from_chunk(chunk_metadata: Dict[str, Any]) -> Optional[Tuple[float, float, str]]:
    """
    Extract latitude, longitude, and address from chunk metadata.
    
    Args:
        chunk_metadata: Metadata dictionary from a vector store chunk
        
    Returns:
        Tuple of (latitude, longitude, display_address) or None if not found
    """
    try:
        lat = chunk_metadata.get('latitude')
        lon = chunk_metadata.get('longitude')
        address = chunk_metadata.get('displayAddress', '')
        
        if lat and lon:
            return (float(lat), float(lon), address)
    except (ValueError, TypeError):
        pass
    
    return None


def find_nearby_properties(
    current_lat: float,
    current_lon: float,
    all_properties: List[Dict[str, Any]],
    max_distance_km: float = 5.0,
    max_results: int = 5
) -> List[Dict[str, Any]]:
    """
    Find properties within a certain distance from given coordinates.
    
    Args:
        current_lat: Current property latitude
        current_lon: Current property longitude
        all_properties: List of all property chunks with metadata
        max_distance_km: Maximum distance in kilometers
        max_results: Maximum number of results to return
        
    Returns:
        List of nearby properties with distance information
    """
    nearby = []
    seen_listing_ids = set()
    
    for prop in all_properties:
        listing_id = prop.get('metadata', {}).get('listing_id')
        
        # Skip if we've already added this listing
        if listing_id in seen_listing_ids:
            continue
        
        location = get_location_from_chunk(prop.get('metadata', {}))
        if not location:
            continue
        
        prop_lat, prop_lon, address = location
        
        # Calculate distance
        distance = haversine_distance(current_lat, current_lon, prop_lat, prop_lon)
        
        if distance <= max_distance_km and distance > 0:  # Exclude same property (distance=0)
            nearby.append({
                'listing_id': listing_id,
                'distance_km': round(distance, 2),
                'latitude': prop_lat,
                'longitude': prop_lon,
                'address': address,
                'content': prop.get('content', ''),
                'metadata': prop.get('metadata', {})
            })
            seen_listing_ids.add(listing_id)
    
    # Sort by distance and limit results
    nearby.sort(key=lambda x: x['distance_km'])
    return nearby[:max_results]


def format_nearby_properties_context(
    nearby_properties: List[Dict[str, Any]],
    query: str
) -> str:
    """
    Format nearby properties information for inclusion in LLM context.
    
    Args:
        nearby_properties: List of nearby property dictionaries
        query: Original user query
        
    Returns:
        Formatted context string
    """
    if not nearby_properties:
        return ""
    
    context_parts = [
        "\n--- NEARBY PROPERTIES ---",
        f"Found {len(nearby_properties)} properties near this location:\n"
    ]
    
    for i, prop in enumerate(nearby_properties, 1):
        context_parts.append(
            f"{i}. Property at {prop['address']} "
            f"({prop['distance_km']} km away)"
        )
        
        # Include relevant property details if available in content
        if prop.get('content'):
            # Truncate content to keep context manageable
            content_preview = prop['content'][:200]
            context_parts.append(f"   Details: {content_preview}...\n")
    
    return "\n".join(context_parts)


def format_nearby_properties_json(
    nearby_properties: List[Dict[str, Any]],
    all_listings_data: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    """
    Format nearby properties as JSON array for API response.
    Returns properties in backend API format.
    
    Args:
        nearby_properties: List of nearby property dictionaries with metadata
        all_listings_data: Optional dict mapping listing_id to full listing data
        
    Returns:
        List of formatted property dicts in backend API format
    """
    import re
    formatted_properties = []
    
    for prop in nearby_properties:
        metadata = prop.get('metadata', {})
        content = prop.get('content', '')
        
        # Extract basic info from metadata
        listing_id = metadata.get('listing_id')
        slug = metadata.get('slug', '')
        title = metadata.get('title', '')
        
        # Extract listing type, status, and auction info
        listing_type = metadata.get('listing_type', metadata.get('listingType', 'private_sale'))
        listing_status = metadata.get('listing_status', metadata.get('listingStatus', 'active'))
        auction_status = metadata.get('auction_status', metadata.get('auctionStatus', ''))
        
        # Extract price
        price = metadata.get('price')
        if price:
            try:
                price = int(float(price))
            except (ValueError, TypeError):
                price = None
        
        # Extract address
        address = prop.get('address', metadata.get('address', ''))
        
        # Extract land area
        land_area = metadata.get('landArea', metadata.get('land_area'))
        if land_area:
            try:
                land_area = float(land_area)
            except (ValueError, TypeError):
                land_area = None
        
        land_area_unit = metadata.get('landArea_unit', metadata.get('land_area_unit', 'sqm'))
        
        # Extract bedrooms
        bedrooms = metadata.get('bedrooms')
        if bedrooms:
            try:
                bedrooms = int(bedrooms)
            except (ValueError, TypeError):
                bedrooms = None
        
        # Extract bathrooms
        bathrooms = metadata.get('bathrooms')
        if bathrooms:
            try:
                bathrooms = int(bathrooms)
            except (ValueError, TypeError):
                bathrooms = None
        
        # Extract propertyMedia array
        property_media = None
        property_media_json = metadata.get('propertyMedia_json')
        if property_media_json:
            try:
                import json
                property_media = json.loads(property_media_json)
            except (json.JSONDecodeError, TypeError):
                property_media = None
        
        # Build property dict in backend API format
        property_dict = {
            'id': listing_id,
            'slug': slug,
            'title': title,
            'listingType': listing_type,
            'listingStatus': listing_status,
            'auctionStatus': auction_status,
            'price': price,
            'address': address,
            'landArea': land_area,
            'landArea_unit': land_area_unit,
            'bedrooms': bedrooms,
            'bathrooms': bathrooms,
            'distance': f"{prop['distance_km']:.1f} km",
            'distanceKm': prop['distance_km']
        }
        
        # Add propertyMedia array if available
        if property_media:
            property_dict['propertyMedia'] = property_media
        
        formatted_properties.append(property_dict)
    
    return formatted_properties


def detect_location_query(query: str) -> Tuple[bool, Optional[str]]:
    """
    Detect if query is asking about nearby locations/amenities.
    
    Args:
        query: User query string
        
    Returns:
        Tuple of (is_location_query, query_type)
        query_type can be: 'nearby_properties', 'nearby_amenities', 'nearby_transport'
    """
    query_lower = query.lower()
    
    nearby_keywords = ['nearby', 'near', 'close to', 'around', 'surrounding', 'proximity', 'distance']
    property_keywords = ['property', 'properties', 'listing', 'listings', 'house', 'apartment']
    amenity_keywords = ['hospital', 'school', 'shop', 'restaurant', 'park', 'mall', 'store']
    transport_keywords = ['bus stop', 'train station', 'metro', 'transport', 'station', 'bus', 'train']
    
    # Check if it's a location-based query
    has_nearby = any(keyword in query_lower for keyword in nearby_keywords)
    
    if not has_nearby:
        return False, None
    
    # Determine query type
    if any(keyword in query_lower for keyword in property_keywords):
        return True, 'nearby_properties'
    elif any(keyword in query_lower for keyword in transport_keywords):
        return True, 'nearby_transport'
    elif any(keyword in query_lower for keyword in amenity_keywords):
        return True, 'nearby_amenities'
    
    # Generic nearby query
    return True, 'nearby_general'


def format_location_info_for_prompt(
    latitude: float,
    longitude: float,
    address: str,
    nearby_properties: Optional[List[Dict[str, Any]]] = None,
    query_type: Optional[str] = None
) -> str:
    """
    Format location information for inclusion in the generation prompt.
    
    Args:
        latitude: Property latitude
        longitude: Property longitude
        address: Property display address
        nearby_properties: Optional list of nearby properties
        query_type: Type of location query
        
    Returns:
        Formatted location context string
    """
    # NOTE: We intentionally do NOT expose raw latitude/longitude values in the LLM context,
    # so they don't appear in the user-facing answer. Coordinates are still used internally
    # for distance calculations and to generate Google Maps links, but the model should talk
    # about "this location" or "the property" instead of printing numeric lat/long.
    context_parts = [
        "\n=== LOCATION CONTEXT ===",
        f"Property Location: {address}\n",
    ]
    
    if nearby_properties:
        context_parts.append(format_nearby_properties_context(nearby_properties, ""))
    
    if query_type == 'nearby_amenities':
        context_text = (
            "Note: The user is asking about nearby amenities such as hospitals, schools, "
            "parks, gyms, or libraries. Do NOT mention numeric latitude/longitude values "
            "in your answer. If Google Maps links for specific amenities are provided, tell "
            "the user they can find nearby [amenity type] using the links below."
        )
        context_parts.append("\n" + context_text)
    elif query_type == 'nearby_transport':
        context_text = (
            "Note: The user is asking about nearby transport options (bus stops, train "
            "stations, metro, tram, etc.). First ask a brief follow-up question to clarify "
            "which type of transport they are interested in (e.g., bus stops or train "
            "stations). Once they specify the transport type, use the provided Google Maps "
            "links (or generate a link using that exact transport term) and tell the user "
            "they can find nearby [transport type] using the links below. Do NOT include "
            "numeric latitude/longitude values in your answer."
        )
        context_parts.append("\n" + context_text)
    
    return "\n".join(context_parts)


def extract_location_from_listing(listing_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract location information from a listing data structure.
    
    Args:
        listing_data: Property listing data
        
    Returns:
        Dictionary with location info or None
    """
    # Handle both direct data and nested data.location structure
    location = listing_data.get('location') or listing_data.get('data', {}).get('location')
    
    if not location:
        return None
    
    try:
        lat = location.get('latitude')
        lon = location.get('longitude')
        
        if lat is not None and lon is not None:
            return {
                'latitude': float(lat),
                'longitude': float(lon),
                'displayAddress': location.get('displayAddress', ''),
                'suburb': location.get('suburb', ''),
                'city': location.get('city', ''),
                'state': location.get('state', ''),
                'country': location.get('country', ''),
                'postalCode': location.get('postalCode', '')
            }
    except (ValueError, TypeError):
        pass
    
    return None

