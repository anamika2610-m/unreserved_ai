"""
Location utilities for geospatial queries and distance calculations.
"""
import json
import math
from typing import Dict, List, Tuple, Any, Optional

# Constants
EARTH_RADIUS_KM = 6371.0  # Earth's radius in kilometers


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
    
    return c * EARTH_RADIUS_KM


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


def get_suburb_from_chunk(chunk_metadata: Dict[str, Any]) -> Optional[str]:
    """
    Extract suburb from chunk metadata.
    
    Args:
        chunk_metadata: Metadata dictionary from a vector store chunk
        
    Returns:
        Suburb name or None if not found
    """
    try:
        suburb = chunk_metadata.get('suburb', '')
        if suburb and suburb.strip():
            return suburb.strip()
    except (ValueError, TypeError):
        pass
    
    return None


def _should_skip_property(
    prop: Dict[str, Any],
    current_listing_id: Optional[str],
    seen_listing_ids: set
) -> bool:
    """
    Check if a property should be skipped (current listing or already seen).
    
    Args:
        prop: Property dictionary
        current_listing_id: Current listing ID to exclude
        seen_listing_ids: Set of already seen listing IDs
        
    Returns:
        True if property should be skipped, False otherwise
    """
    listing_id = prop.get('metadata', {}).get('listing_id')
    
    # Skip if this is the current listing
    if current_listing_id and listing_id == current_listing_id:
        return True
    
    # Skip if we've already seen this listing_id
    if listing_id in seen_listing_ids:
        return True
    
    return False


def _create_property_dict(
    listing_id: str,
    address: str,
    prop: Dict[str, Any],
    distance_km: Optional[float] = None,
    prop_lat: Optional[float] = None,
    prop_lon: Optional[float] = None,
    same_suburb: bool = False
) -> Dict[str, Any]:
    """
    Create a standardized property dictionary.
    
    Args:
        listing_id: Property listing ID
        address: Property address
        prop: Original property dictionary
        distance_km: Optional distance in km
        prop_lat: Optional latitude
        prop_lon: Optional longitude
        same_suburb: Whether this is a same-suburb property
        
    Returns:
        Standardized property dictionary
    """
    result = {
        'listing_id': listing_id,
        'distance_km': distance_km,
        'latitude': prop_lat,
        'longitude': prop_lon,
        'address': address,
        'content': prop.get('content', ''),
        'metadata': prop.get('metadata', {})
    }
    
    if same_suburb:
        result['same_suburb'] = True
    
    return result


def find_nearby_properties(
    current_lat: float,
    current_lon: float,
    all_properties: List[Dict[str, Any]],
    max_distance_km: float = 5.0,
    max_results: int = 5,
    current_listing_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Find properties within a certain distance from given coordinates.
    
    Args:
        current_lat: Current property latitude
        current_lon: Current property longitude
        all_properties: List of all property chunks with metadata
        max_distance_km: Maximum distance in kilometers
        max_results: Maximum number of results to return
        current_listing_id: Optional listing ID to exclude from results (the current property)
        
    Returns:
        List of nearby properties with distance information
    """
    nearby = []
    seen_listing_ids = set()
    
    for prop in all_properties:
        # Skip if this is the current listing or already seen
        if _should_skip_property(prop, current_listing_id, seen_listing_ids):
            continue
        
        listing_id = prop.get('metadata', {}).get('listing_id')
        location = get_location_from_chunk(prop.get('metadata', {}))
        if not location:
            continue
        
        prop_lat, prop_lon, address = location
        
        distance = haversine_distance(current_lat, current_lon, prop_lat, prop_lon)
        
        # Include properties within max_distance_km (including distance=0 for same coordinates)
        # We already excluded the current_listing_id above, so distance=0 is fine for other listings
        if distance <= max_distance_km:
            nearby.append(_create_property_dict(
                listing_id=listing_id,
                address=address,
                prop=prop,
                distance_km=round(distance, 2),
                prop_lat=prop_lat,
                prop_lon=prop_lon
            ))
            seen_listing_ids.add(listing_id)
    
    # Sort by distance and limit results
    nearby.sort(key=lambda x: x['distance_km'])
    return nearby[:max_results]


def find_same_suburb_properties(
    current_suburb: str,
    all_properties: List[Dict[str, Any]],
    max_results: int = 5,
    current_listing_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Find properties in the same suburb when no nearby properties are found within distance threshold.
    
    Args:
        current_suburb: Current property suburb
        all_properties: List of all property chunks with metadata
        max_results: Maximum number of results to return
        current_listing_id: Optional listing ID to exclude from results (the current property)
        
    Returns:
        List of same-suburb properties
    """
    if not current_suburb or not current_suburb.strip():
        return []
    
    same_suburb = []
    seen_listing_ids = set()
    current_suburb_lower = current_suburb.strip().lower()
    
    for prop in all_properties:
        # Skip if this is the current listing or already seen
        if _should_skip_property(prop, current_listing_id, seen_listing_ids):
            continue
        
        listing_id = prop.get('metadata', {}).get('listing_id')
        prop_suburb = get_suburb_from_chunk(prop.get('metadata', {}))
        if not prop_suburb:
            continue
        
        # Check if suburb matches (case-insensitive)
        if prop_suburb.lower() == current_suburb_lower:
            location = get_location_from_chunk(prop.get('metadata', {}))
            prop_lat = location[0] if location else None
            prop_lon = location[1] if location else None
            address = location[2] if location else prop.get('metadata', {}).get('displayAddress', '')
            
            same_suburb.append(_create_property_dict(
                listing_id=listing_id,
                address=address,
                prop=prop,
                distance_km=None,  # No distance calculated for same-suburb
                prop_lat=prop_lat,
                prop_lon=prop_lon,
                same_suburb=True
            ))
            seen_listing_ids.add(listing_id)
    
    return same_suburb[:max_results]


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
        metadata = prop.get('metadata', {})
        
        # Extract key details
        title = metadata.get('title', 'Property')
        address = prop.get('address', metadata.get('address', 'Address not available'))
        distance_km = prop.get('distance_km')
        distance_str = f"{distance_km} km away" if distance_km is not None else "same suburb"
        
        # Extract and format price
        price = _safe_int_convert(metadata.get('price'))
        price_str = f"**Price: ${price:,}**" if price else "**Price: Contact vendor for pricing**"
        
        # Extract bedrooms/bathrooms
        bedrooms = _safe_int_convert(metadata.get('bedrooms'))
        bathrooms = _safe_int_convert(metadata.get('bathrooms'))
        specs = []
        if bedrooms and bedrooms > 0:
            specs.append(f"{bedrooms} bed")
        if bathrooms and bathrooms > 0:
            specs.append(f"{bathrooms} bath")
        specs_str = ", ".join(specs) if specs else "specs not available"
        
        context_parts.append(
            f"{i}. **{address}** ({distance_str})\n"
            f"   Title: *{title}*\n"
            f"   {specs_str}\n"
            f"   {price_str}"
        )
        
        # Include relevant property details if available in content (optional)
        if prop.get('content') and len(prop['content']) > 50:
            # Truncate content to keep context manageable
            content_preview = prop['content'][:150]
            context_parts.append(f"   Additional info: {content_preview}...\n")
        else:
            context_parts.append("")  # Empty line for separation
    
    return "\n".join(context_parts)


def _safe_int_convert(value: Any) -> Optional[int]:
    """
    Safely convert a value to integer.
    
    Args:
        value: Value to convert
        
    Returns:
        Integer value or None if conversion fails
    """
    if value is None or value == '':
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _safe_float_convert(value: Any) -> Optional[float]:
    """
    Safely convert a value to float.
    
    Args:
        value: Value to convert
        
    Returns:
        Float value or None if conversion fails
    """
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _format_distance_string(distance_km: Optional[float]) -> str:
    """
    Format distance as a string.
    
    Args:
        distance_km: Distance in kilometers
        
    Returns:
        Formatted distance string
    """
    if distance_km is not None:
        try:
            return f"{float(distance_km):.1f} km"
        except (ValueError, TypeError):
            return "Same suburb"
    return "Same suburb"


def format_nearby_properties_json(
    nearby_properties: List[Dict[str, Any]],
    all_listings_data: Optional[Dict[str, Any]] = None
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
    formatted_properties = []
    
    for prop in nearby_properties:
        metadata = prop.get('metadata', {})
        
        listing_id = metadata.get('listing_id')
        slug = metadata.get('slug', '')
        title = metadata.get('title', '')
        
        listing_type = metadata.get('listing_type', metadata.get('listingType', 'private_sale'))
        listing_status = metadata.get('listing_status', metadata.get('listingStatus', 'active'))
        auction_status = metadata.get('auction_status', metadata.get('auctionStatus', ''))
        
        # Extract and convert values safely
        price = _safe_int_convert(metadata.get('price'))
        address = prop.get('address', metadata.get('address', ''))
        land_area = _safe_float_convert(metadata.get('landArea', metadata.get('land_area')))
        land_area_unit = metadata.get('landArea_unit', metadata.get('land_area_unit', 'sqm'))
        bedrooms = _safe_int_convert(metadata.get('bedrooms'))
        bathrooms = _safe_int_convert(metadata.get('bathrooms'))
        
        # Parse property media JSON
        property_media = None
        property_media_json = metadata.get('propertyMedia_json')
        if property_media_json:
            try:
                property_media = json.loads(property_media_json)
            except (json.JSONDecodeError, TypeError):
                property_media = None
        
        # Format distance
        distance_km = prop.get('distance_km')
        distance_str = _format_distance_string(distance_km)
        
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
            'distance': distance_str,
            'distanceKm': distance_km
        }
        
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
    property_keywords = ['propert', 'listing', 'house', 'apartment']  # Use "propert" to match "property", "properties", "propertues"
    amenity_keywords = ['amenit', 'hospital', 'school', 'shop', 'restaurant', 'park', 'mall', 'store', 'gym', 'library', 'cafe', 'supermarket', 'pharmacy', 'bank']
    transport_keywords = ['bus stop', 'train station', 'metro', 'transport', 'station', 'bus', 'train']
    
    has_nearby = any(keyword in query_lower for keyword in nearby_keywords)
    
    if not has_nearby:
        return False, None
    
    # Priority order: amenities > transport > properties
    # This ensures that if a query mentions both "property" (referring to current property) 
    # and "amenities" (what they're asking about), we correctly identify it as an amenity query
    if any(keyword in query_lower for keyword in amenity_keywords):
        return True, 'nearby_amenities'
    elif any(keyword in query_lower for keyword in transport_keywords):
        return True, 'nearby_transport'
    elif any(keyword in query_lower for keyword in property_keywords):
        return True, 'nearby_properties'
    
    return True, 'nearby_general'


def format_location_info_for_prompt(
    latitude: Optional[float],
    longitude: Optional[float],
    address: Optional[str],
    suburb: Optional[str] = None,
    nearby_properties: Optional[List[Dict[str, Any]]] = None,
    same_suburb_properties: Optional[List[Dict[str, Any]]] = None,
    query_type: Optional[str] = None
) -> str:
    """
    Format location information for inclusion in the generation prompt.
    
    Args:
        latitude: Property latitude (optional)
        longitude: Property longitude (optional)
        address: Property display address (optional)
        suburb: Property suburb
        nearby_properties: Optional list of nearby properties (within distance threshold)
        same_suburb_properties: Optional list of properties in the same suburb (when no nearby found)
        query_type: Type of location query
        
    Returns:
        Formatted location context string
    """
    
    context_parts = [
        "\n=== LOCATION CONTEXT ===",
    ]
    
    if address:
        context_parts.append(f"Property Location: {address}\n")
    elif latitude is not None and longitude is not None:
        context_parts.append(f"Property Coordinates: ({latitude}, {longitude})\n")
    
    if suburb:
        context_parts.append(f"Property Suburb: {suburb}\n")
    
    if nearby_properties:
        context_parts.append(format_nearby_properties_context(nearby_properties, ""))
    elif same_suburb_properties:
        # Format same-suburb properties
        context_parts.append("\n--- SAME SUBURB PROPERTIES ---")
        context_parts.append(f"Note: No properties found within the distance threshold, but found {len(same_suburb_properties)} properties in the same suburb ({suburb or 'this suburb'}):\n")
        
        for i, prop in enumerate(same_suburb_properties, 1):
            context_parts.append(
                f"{i}. Property at {prop['address']} (same suburb)"
            )
            
            # Include relevant property details if available in content
            if prop.get('content'):
                content_preview = prop['content'][:200]
                context_parts.append(f"   Details: {content_preview}...\n")
    
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

