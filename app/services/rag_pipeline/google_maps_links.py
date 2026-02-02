"""
Generate Google Maps search links for nearby amenities.
No API key required - just deep links to Google Maps.
"""
import re
from typing import List, Dict, Any, Optional, Tuple

# Constants
DEFAULT_ZOOM_LEVEL = 15
DEFAULT_LOCATION_ICON = "📍"
GOOGLE_MAPS_BASE_URL = "https://www.google.com/maps/search"

# Location indicators for amenity queries
LOCATION_INDICATORS = [
    'nearby', 'near', 'close', 'around', 'surrounding', 'proximity',
    'are there', 'is there', 'any', 'find', 'where', 'list', 'show',
    'available', 'access to', 'close to', 'within', 'distance',
    'what about', 'how about', 'tell me', 'show me', 'find me',
    'looking for', 'search', 'locate', 'area', 'vicinity'
]

# Common amenity/place categories (comprehensive list with plurals)
AMENITY_INDICATORS = [
    # Medical & Health
    'hospital', 'hospitals', 'clinic', 'clinics', 'doctor', 'doctors', 
    'dentist', 'dentists', 'pharmacy', 'pharmacies', 'medical', 'health',
    # Education
    'school', 'schools', 'college', 'colleges', 'university', 'universities',
    'kindergarten', 'kindergartens', 'daycare', 'daycares', 'library', 'libraries',
    # Shopping & Retail
    'shop', 'shops', 'store', 'stores', 'mall', 'malls', 'market', 'markets',
    'supermarket', 'supermarkets', 'grocery', 'groceries', 'boutique', 'boutiques',
    # Food & Dining
    'restaurant', 'restaurants', 'cafe', 'cafes', 'coffee', 'bakery', 'bakeries',
    'pizzeria', 'pizzerias', 'diner', 'diners', 'eatery', 'eateries',
    # Fitness & Recreation
    'gym', 'gyms', 'fitness', 'park', 'parks', 'playground', 'playgrounds',
    'pool', 'pools', 'sports', 'yoga', 'studio', 'studios',
    # Transportation
    'station', 'stations', 'bus', 'buses', 'train', 'trains',
    'metro', 'airport', 'airports', 'taxi', 'taxis',
    # Financial
    'bank', 'banks', 'atm', 'atms', 'credit union',
    # Entertainment
    'theater', 'theaters', 'theatre', 'theatres', 'cinema', 'cinemas',
    'movie', 'movies', 'club', 'clubs', 'pub', 'pubs', 'bar', 'bars', 'nightclub', 'nightclubs',
    # Religious
    'church', 'churches', 'temple', 'temples', 'mosque', 'mosques', 'synagogue', 'synagogues',
    # Services
    'salon', 'salons', 'barber', 'barbers', 'spa', 'spas',
    'laundry', 'laundromat', 'laundromats', 'dry clean', 'dry cleaner', 'dry cleaners',
    'tailor', 'tailors',
    'gas station', 'gas stations', 'fuel', 'petrol', 'mechanic', 'mechanics', 'garage', 'garages',
    # Pets
    'vet', 'vets', 'veterinary', 'pet', 'pets', 'pet store', 'pet stores',
    # Emergency & Safety
    'police', 'fire station', 'fire stations', 'emergency',
    # Other common places
    'post office', 'post offices', 'convenience', 'bookstore', 'bookstores',
    'florist', 'florists', 'jewelry', 'jeweler', 'jewelers',
    # Generic amenity terms (must be last to avoid false positives)
    'amenity', 'amenities', 'places', 'facilities', 'services'
]

# Question indicators for amenity queries
QUESTION_INDICATORS = ['?', 'where', 'what', 'which', 'how', 'are', 'is', 'any']

# Location indicators for invalid query detection (subset)
INVALID_QUERY_LOCATION_INDICATORS = [
    'nearby', 'near', 'close', 'around', 'any', 'are there', 'is there'
]

# Invalid/nonsensical terms that people might ask about
INVALID_TERMS = [
    'song', 'songs', 'music', 'movie', 'movies', 'film', 'films',
    'book', 'books', 'story', 'stories', 'poem', 'poems',
    'game', 'games', 'toy', 'toys', 'pet', 'pets', 'animal', 'animals',
    'person', 'people', 'friend', 'friends', 'neighbor', 'neighbors',
    'job', 'jobs', 'work', 'employment', 'career', 'weather', 'temperature'
]

# Common stop words for search term extraction
STOP_WORDS = {
    'nearby', 'near', 'nearest', 'closest', 'close', 'around', 'surrounding', 'proximity', 'within',
    'are', 'is', 'there', 'any', 'the', 'a', 'an', 'to', 'by', 'me',
    'list', 'down', 'show', 'find', 'tell', 'me', 'about',
    'what', 'how', 'where', 'which', 'can', 'you', 'i',
    'want', 'need', 'looking', 'for', 'some',
    # Non-amenity terms that often appear alongside amenity questions
    # (e.g., "pricing and amenities") but should NEVER be used for Maps searches
    'price', 'prices', 'pricing', 'cost', 'costs',
    # Reference words
    'this', 'that', 'these', 'those', 'here', 'there'
}

# Generic amenity terms that should NOT be used as search terms
# These trigger fallback to predefined amenities instead
GENERIC_AMENITY_TERMS = {
    'amenity', 'amenities', 'amenities.', 'places', 'facilities', 'services', 
    'location', 'locations', 'area', 'nearby', 'things', 'stuff', 'options'
}

# Common amenities for default suggestions
COMMON_AMENITIES = ["hospitals", "schools", "bus_stops", "supermarkets"]


AMENITY_TYPES = {
    "hospitals": {
        "icon": "🏥",
        "label": "Hospitals & Medical Centers",
        "search_terms": ["hospitals"],
        "keywords": ["hospital", "medical", "clinic", "doctor", "healthcare", "emergency"]
    },
    "schools": {
        "icon": "🏫",
        "label": "Schools & Education",
        "search_terms": ["schools"],
        "keywords": ["school", "education", "college", "university", "kindergarten"]
    },
    "bus_stops": {
        "icon": "🚌",
        "label": "Bus Stops & Public Transport",
        "search_terms": ["bus+stops", "bus+station", "bus+stations"],
        "keywords": ["bus", "bus stop", "bus stops", "bus station", "bus stations"]
    },
    "supermarkets": {
        "icon": "🛒",
        "label": "Supermarkets & Grocery Stores",
        "search_terms": ["supermarkets", "grocery+stores"],
        "keywords": ["supermarket", "grocery", "shopping", "market", "store"]
    },
    "restaurants": {
        "icon": "🍽️",
        "label": "Restaurants & Cafes",
        "search_terms": ["restaurants", "cafes"],
        "keywords": ["restaurant", "cafe", "food", "dining", "eat"]
    },
    "parks": {
        "icon": "🌳",
        "label": "Parks & Recreation",
        "search_terms": ["parks"],
        "keywords": ["park", "recreation", "playground", "garden"]
    },
    "police_stations": {
        "icon": "🚓",
        "label": "Police Stations",
        "search_terms": ["police+stations"],
        "keywords": ["police", "police station", "safety", "security"]
    },
    "pharmacies": {
        "icon": "💊",
        "label": "Pharmacies",
        "search_terms": ["pharmacies"],
        "keywords": ["pharmacy", "chemist", "medicine", "drugs"]
    },
    "banks": {
        "icon": "🏦",
        "label": "Banks & ATMs",
        "search_terms": ["banks", "atms"],
        "keywords": ["bank", "atm", "banking"]
    },
    "gyms": {
        "icon": "💪",
        "label": "Gyms & Fitness Centers",
        "search_terms": ["gyms", "fitness+centers"],
        "keywords": ["gym", "fitness", "workout", "exercise"]
    }
}


def _build_google_maps_url(search_query: str, latitude: float, longitude: float, zoom: int) -> str:
    """
    Build a Google Maps search URL that forces search near the specified coordinates.
    
    Uses a format that explicitly centers the search at the property location.
    The coordinates are embedded in the search query itself to force Google Maps
    to search at that location rather than using the user's current location.
    
    Args:
        search_query: URL-encoded search query
        latitude: Property latitude
        longitude: Property longitude
        zoom: Map zoom level
        
    Returns:
        Google Maps search URL that forces search at the specified coordinates
    """
    # Format: /search/query+near+lat,lng/@lat,lng,zoomz
    # Embedding coordinates in both the search query ("near lat,lng") and as map center (@lat,lng)
    # This dual approach helps force Google Maps to use the property location
    # rather than the user's current location
    search_with_location = f"{search_query}+near+{latitude},{longitude}"
    return f"{GOOGLE_MAPS_BASE_URL}/{search_with_location}/@{latitude},{longitude},{zoom}z"


def generate_google_maps_link(
    amenity_type: str,
    latitude: float,
    longitude: float,
    zoom: int = DEFAULT_ZOOM_LEVEL
) -> str:
    """
    Generate a Google Maps search URL for a specific amenity type.
    
    Args:
        amenity_type: Type of amenity (e.g., 'hospitals', 'schools')
        latitude: Property latitude
        longitude: Property longitude
        zoom: Map zoom level (default: 15)
        
    Returns:
        Google Maps search URL
        
    Example:
        >>> generate_google_maps_link('hospitals', -33.8688, 151.2093)
        'https://www.google.com/maps/search/hospitals/@-33.8688,151.2093,15z'
    """
    amenity_config = AMENITY_TYPES.get(amenity_type, {})
    search_terms = amenity_config.get("search_terms", [amenity_type])
    
    # Use the first search term (or combine multiple)
    search_query = "+OR+".join(search_terms)
    
    return _build_google_maps_url(search_query, latitude, longitude, zoom)
    

def is_amenity_query(query: str) -> bool:
    """
    Check if the query is actually asking about nearby amenities/places.
    
    Args:
        query: User's query string
        
    Returns:
        True if query is asking about amenities, False otherwise
        
    Example:
        >>> is_amenity_query("Are there hospitals nearby?")
        True
        >>> is_amenity_query("What is the price?")
        False
        >>> is_amenity_query("Sing a song")
        False
        >>> is_amenity_query("Tell me about the market trends")
        False
    """
    query_lower = query.lower()
    
    # Exclude real estate market queries (market trends, market data, market analysis, etc.)
    # These are about property market data, not shopping markets/amenities
    market_data_terms = [
        'market trend', 'market trends', 'market data', 'market analysis',
        'market insight', 'market insights', 'market condition', 'market conditions',
        'market value', 'market values', 'market price', 'market prices',
        'real estate market', 'property market', 'housing market',
        'market report', 'market reports', 'market forecast', 'market forecasts',
        'market outlook', 'market performance', 'market statistics'
    ]
    
    # If query is about real estate market data, it's NOT an amenity query
    if any(term in query_lower for term in market_data_terms):
        return False
    
    # Exclude generic knowledge/regulatory queries (bushfire regulations, planning regulations, etc.)
    # These are about laws/regulations, not physical amenities
    regulatory_terms = [
        'bushfire', 'bushfire regulations', 'bushfire management', 'bushfire overlay',
        'zoning regulations', 'planning regulations', 'heritage overlay',
        'planning scheme', 'council regulations', 'building regulations',
        'planning permit', 'planning approval', 'council approval',
        'regulations', 'regulation', 'legislation', 'legislative',
        'compliance', 'legal requirements', 'statutory'
    ]
    
    # If query is about regulations/legislation, it's NOT an amenity query
    if any(term in query_lower for term in regulatory_terms):
        return False
    
    # Check for location and amenity context
    has_location_context = any(indicator in query_lower for indicator in LOCATION_INDICATORS)
    has_amenity_context = any(indicator in query_lower for indicator in AMENITY_INDICATORS)
    
    # Primary check: Must have both location and amenity indicators
    if has_location_context and has_amenity_context:
        return True
    
    # Fallback: If query has amenity but no explicit location word,
    # still treat as amenity query if it's a question or command about places
    if has_amenity_context:
        if any(indicator in query_lower for indicator in QUESTION_INDICATORS):
            return True
    
    return False


def is_invalid_amenity_query(query: str) -> bool:
    """
    Detect if the query appears to be asking about amenities but uses invalid/nonsensical terms.
    
    Args:
        query: User's query string
        
    Returns:
        True if query seems to be asking about amenities but with invalid terms
    """
    query_lower = query.lower()
    
    has_location = any(indicator in query_lower for indicator in INVALID_QUERY_LOCATION_INDICATORS)
    
    if not has_location:
        return False
    
    # Check if query has location indicator but mentions invalid terms
    if any(term in query_lower for term in INVALID_TERMS):
        return True
    
    return False


def extract_amenity_search_terms(query: str) -> List[str]:
    """
    Extract actual amenity search terms from the user's query.
    Only extracts if query is actually asking about nearby amenities.
    
    Args:
        query: User's query string
        
    Returns:
        List of search terms extracted from the query, or empty list if not an amenity query
        
    Example:
        >>> extract_amenity_search_terms("Are there any coffee shops nearby?")
        ['coffee shops']
        >>> extract_amenity_search_terms("list down nearby schools and hospitals")
        ['schools', 'hospitals']
        >>> extract_amenity_search_terms("Sing a song")
        []
    """
    # First check if this is actually an amenity query
    if not is_amenity_query(query):
        return []
    
    query_lower = query.lower()
    
    # Remove question marks, apostrophes, and extra spaces
    cleaned = query_lower.replace('?', ' ').replace("'", ' ').strip()
    
    # Normalize "the nearby" -> "nearby" (common pattern that causes issues)
    cleaned = re.sub(r'\bthe\s+nearby\b', 'nearby', cleaned)
    cleaned = re.sub(r'\bnearby\s+the\b', 'nearby', cleaned)
    # Fix concatenated words like "thenearby" -> "the nearby" -> "nearby"
    cleaned = re.sub(r'\bthenearby\b', 'nearby', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\bnearbythe\b', 'nearby', cleaned, flags=re.IGNORECASE)
    
    # Normalize multiple spaces
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    # Split by common separators (and, or, commas)
    terms = re.split(r'\s+and\s+|\s+or\s+|,\s*', cleaned)
    
    search_terms = []
    for term in terms:
        # Split into words and remove stop words
        words = term.split()
        filtered_words = [w for w in words if w not in STOP_WORDS and len(w) > 2]
        
        if filtered_words:
            search_term = ' '.join(filtered_words)
            # Skip if the search term is only generic amenity terms (amenities, places, etc.)
            # These should trigger fallback to predefined amenities instead
            search_term_lower = search_term.lower().rstrip('.')  # Remove trailing period
            
            # Check if the entire search term is a generic term (exact match)
            if search_term_lower in GENERIC_AMENITY_TERMS:
                print(f"   ⚠️  Skipping generic term: '{search_term}'")
                continue  # Skip exact generic terms
            
            if any(generic_term in search_term_lower for generic_term in GENERIC_AMENITY_TERMS):
                # If the term contains ONLY generic words, skip it
                words_in_term = search_term_lower.split()
                if all(word in GENERIC_AMENITY_TERMS for word in words_in_term):
                    print(f"   ⚠️  Skipping generic-only term: '{search_term}'")
                    continue  # Skip generic-only terms
            
            # Validation - should be 1-3 words and at least 3 characters total
            if 1 <= len(filtered_words) <= 3 and len(search_term) >= 3:
                search_terms.append(search_term)
            else:
                print(f"   ⚠️  Skipping invalid term (length): '{search_term}'")
    
    # Final check: if all extracted terms are generic, return empty list (no links)
    if search_terms:
        print(f"✅ Extracted {len(search_terms)} search terms: {search_terms}")
    else:
        print(f"⚠️  No valid search terms extracted (query too generic)")
    
    return search_terms


def detect_amenity_query(query: str) -> List[str]:
    """
    Detect which amenities the user is asking about.
    Returns predefined amenity types for backward compatibility.
    
    Args:
        query: User's query string
        
    Returns:
        List of matching amenity types
        
    Example:
        >>> detect_amenity_query("Are there any hospitals nearby?")
        ['hospitals']
        >>> detect_amenity_query("What about schools and supermarkets?")
        ['schools', 'supermarkets']
        >>> detect_amenity_query("Tell me about the market trends")
        []
    """
    query_lower = query.lower()
    
    # Exclude real estate market queries (market trends, market data, etc.)
    # These are about property market data, not shopping markets/amenities
    market_data_terms = [
        'market trend', 'market trends', 'market data', 'market analysis',
        'market insight', 'market insights', 'market condition', 'market conditions',
        'market value', 'market values', 'market price', 'market prices',
        'real estate market', 'property market', 'housing market',
        'market report', 'market reports', 'market forecast', 'market forecasts',
        'market outlook', 'market performance', 'market statistics'
    ]
    
    # If query is about real estate market data, return empty list
    if any(term in query_lower for term in market_data_terms):
        return []
    
    matched_amenities = []
    
    for amenity_type, config in AMENITY_TYPES.items():
        keywords = config.get("keywords", [])
        if any(keyword in query_lower for keyword in keywords):
            matched_amenities.append(amenity_type)
    
    return matched_amenities


def _find_matching_amenity_type(search_term: str) -> Tuple[str, str]:
    """
    Find matching icon and amenity type for a search term.
    
    Args:
        search_term: The search term to match
        
    Returns:
        Tuple of (icon, amenity_type)
    """
    search_lower = search_term.lower()
    for atype, config in AMENITY_TYPES.items():
        if any(keyword in search_lower for keyword in config.get("keywords", [])):
            return config["icon"], atype
    return DEFAULT_LOCATION_ICON, "custom"


def _normalize_search_term_for_maps(search_term: str) -> str:
    """
    Normalize a search term for Google Maps by removing location qualifiers
    and mapping query phrases to proper search terms.
    
    This ensures Google Maps searches for amenities near the property coordinates,
    not based on the user's location or query phrasing.
    
    Args:
        search_term: Raw search term from user query
        
    Returns:
        Normalized search term suitable for Google Maps
        
    Examples:
        >>> _normalize_search_term_for_maps("nearest school")
        'schools'
        >>> _normalize_search_term_for_maps("closest hospital")
        'hospitals'
        >>> _normalize_search_term_for_maps("nearby coffee shops")
        'coffee shops'
        >>> _normalize_search_term_for_maps("school")
        'schools'
    """
    term_lower = search_term.lower().strip()
    
    # Location qualifiers to remove (these cause Google Maps to search based on user location)
    location_qualifiers = ['nearest', 'closest', 'nearby', 'near', 'close', 'local']
    
    # Split into words and filter out location qualifiers
    words = term_lower.split()
    filtered_words = [w for w in words if w not in location_qualifiers]
    
    if not filtered_words:
        # If all words were qualifiers, return a generic term based on context
        # This shouldn't happen if STOP_WORDS is working, but safety check
        return "places"
    
    normalized = ' '.join(filtered_words)
    
    # Map singular to plural for common amenities (better for Google Maps search)
    singular_to_plural = {
        'school': 'schools',
        'hospital': 'hospitals',
        'supermarket': 'supermarkets',
        'restaurant': 'restaurants',
        'cafe': 'cafes',
        'pharmacy': 'pharmacies',
        'bank': 'banks',
        'gym': 'gyms',
        'park': 'parks',
        'bus stop': 'bus stops',
        'train station': 'train stations',
    }
    
    if normalized in singular_to_plural:
        normalized = singular_to_plural[normalized]
    
    return normalized


def generate_custom_search_link(
    search_term: str,
    latitude: float,
    longitude: float,
    zoom: int = DEFAULT_ZOOM_LEVEL
) -> Dict[str, Any]:
    """
    Generate a Google Maps search link for a custom search term.
    
    Args:
        search_term: The actual search term from user query
        latitude: Property latitude
        longitude: Property longitude
        zoom: Map zoom level
        
    Returns:
        Link object with metadata
        
    Example:
        >>> generate_custom_search_link('coffee shops', -33.8688, 151.2093)
        {
            'type': 'custom',
            'search_term': 'coffee shops',
            'label': 'Coffee Shops',
            'url': 'https://www.google.com/maps/search/coffee+shops/@-33.8688,151.2093,15z'
        }
    """
    # Normalize the search term to remove location qualifiers (nearest, closest, etc.)
    # This ensures Google Maps searches near the property coordinates, not user location
    normalized_term = _normalize_search_term_for_maps(search_term)
    
    # URL encode the normalized search term
    encoded_term = normalized_term.replace(' ', '+')
    url = _build_google_maps_url(encoded_term, latitude, longitude, zoom)
    
    # Create a nice label from the normalized term (title case)
    label = normalized_term.title()
    
    # Try to find a matching icon and amenity type from predefined types
    icon, amenity_type = _find_matching_amenity_type(normalized_term)
    
    return {
        "type": "custom",
        "amenity_type": amenity_type,
        "search_term": normalized_term,  # Use normalized term
        "label": label,
        "icon": icon,
        "url": url
    }


def generate_amenity_links(
    latitude: float,
    longitude: float,
    amenity_types: Optional[List[str]] = None,
    zoom: int = DEFAULT_ZOOM_LEVEL
) -> List[Dict[str, Any]]:
    """
    Generate Google Maps links for multiple amenities.
    
    Args:
        latitude: Property latitude
        longitude: Property longitude
        amenity_types: List of amenity types to generate links for.
                      If None, generates for all common amenities.
        zoom: Map zoom level
        
    Returns:
        List of link objects with metadata
        
    Example:
        >>> links = generate_amenity_links(-33.8688, 151.2093, ['hospitals', 'schools'])
        >>> links[0]
        {
            'type': 'hospitals',
            'icon': '🏥',
            'label': 'Hospitals & Medical Centers',
            'url': 'https://www.google.com/maps/search/hospitals/@-33.8688,151.2093,15z'
        }
    """
    # Default to all available amenities if not specified
    if amenity_types is None:
        amenity_types = list(AMENITY_TYPES.keys())
    
    links = []
    
    for amenity_type in amenity_types:
        if amenity_type not in AMENITY_TYPES:
            continue
            
        config = AMENITY_TYPES[amenity_type]
        
        link_obj = {
            "type": amenity_type,
            "amenity_type": amenity_type,  # Explicit amenity type identifier
            "icon": config["icon"],
            "label": config["label"],
            "url": generate_google_maps_link(amenity_type, latitude, longitude, zoom)
        }
        
        links.append(link_obj)
    
    return links


def generate_context_aware_links(
    query: str,
    latitude: float,
    longitude: float,
    include_common: bool = False
) -> Dict[str, Any]:
    """
    Generate amenity links based on user's query using their actual search terms.
    Intelligently includes relevant amenities based on what user asked.
    
    Args:
        query: User's query
        latitude: Property latitude
        longitude: Property longitude
        include_common: If True, includes common predefined amenities as suggestions
        
    Returns:
        Dictionary with relevant_links and suggested_links
        
    Example:
        >>> result = generate_context_aware_links(
        ...     "Are there coffee shops nearby?",
        ...     -33.8688,
        ...     151.2093
        ... )
        >>> result['relevant_links']  # User's exact search terms
        [{'search_term': 'coffee shops', 'icon': '🍽️', 'label': 'Coffee Shops', ...}]
    """
    # Extract actual search terms from the query
    search_terms = extract_amenity_search_terms(query)
    
    # Generate links for the user's exact search terms
    relevant_links = []
    if search_terms:
        for term in search_terms:
            link = generate_custom_search_link(term, latitude, longitude)
            relevant_links.append(link)
    
    # Fallback: if no custom terms found, try predefined amenities
    if not relevant_links:
        detected_amenities = detect_amenity_query(query)
        if detected_amenities:
            relevant_links = generate_amenity_links(latitude, longitude, detected_amenities)
    
    # Generate common suggested links (optional)
    suggested_links = []
    if include_common and not relevant_links:
        # Only show suggestions if we couldn't find any specific amenities
        suggested_links = generate_amenity_links(latitude, longitude, COMMON_AMENITIES)
    
    return {
        "relevant_links": relevant_links,
        "suggested_links": suggested_links,
        "all_links": relevant_links + suggested_links
    }


def format_links_for_prompt(links: List[Dict[str, Any]]) -> str:
    """
    Format amenity links for inclusion in the AI prompt.
    
    Args:
        links: List of link objects
        
    Returns:
        Formatted string for prompt
    """
    if not links:
        return ""
    
    formatted = "Available amenity search links:\n"
    for link in links:
        label = link.get('label', '')
        icon = link.get('icon', DEFAULT_LOCATION_ICON)
        formatted += f"- {icon} {label}: {link['url']}\n"
    
    return formatted

