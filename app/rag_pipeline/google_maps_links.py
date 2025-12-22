"""
Generate Google Maps search links for nearby amenities.
No API key required - just deep links to Google Maps.
"""

from typing import List, Dict, Any, Optional
from urllib.parse import quote


# Amenity configuration with icons and search terms
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
        "search_terms": ["bus+stops", "public+transport"],
        "keywords": ["bus", "bus stop", "public transport", "metro", "train station"]
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


def generate_google_maps_link(
    amenity_type: str,
    latitude: float,
    longitude: float,
    zoom: int = 15
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
    
    # Google Maps search URL format: https://www.google.com/maps/search/{query}/@{lat},{lng},{zoom}z
    return f"https://www.google.com/maps/search/{search_query}/@{latitude},{longitude},{zoom}z"


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
    """
    query_lower = query.lower()
    
    # Keywords that indicate location/amenity queries
    location_indicators = [
        'nearby', 'near', 'close', 'around', 'surrounding', 'proximity',
        'are there', 'is there', 'any', 'find', 'where', 'list', 'show',
        'available', 'access to', 'close to', 'within', 'distance',
        'what about', 'how about', 'tell me', 'show me', 'find me',
        'looking for', 'search', 'locate', 'area', 'vicinity'
    ]
    
    # Common amenity/place categories - comprehensive list (includes plurals)
    amenity_indicators = [
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
        'station', 'stations', 'transport', 'bus', 'buses', 'train', 'trains',
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
        'florist', 'florists', 'jewelry', 'jeweler', 'jewelers'
    ]
    
    # Check for location and amenity context
    has_location_context = any(indicator in query_lower for indicator in location_indicators)
    has_amenity_context = any(indicator in query_lower for indicator in amenity_indicators)
    
    # Primary check: Must have both location and amenity indicators
    if has_location_context and has_amenity_context:
        return True
    
    # Fallback: If query has amenity but no explicit location word,
    # still treat as amenity query if it's a question or command about places
    if has_amenity_context:
        # Check if it's phrased as a question or location-seeking command
        question_indicators = ['?', 'where', 'what', 'which', 'how', 'are', 'is', 'any']
        if any(indicator in query_lower for indicator in question_indicators):
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
    import re
    
    # First check if this is actually an amenity query
    if not is_amenity_query(query):
        return []
    
    query_lower = query.lower()
    
    # Common stop words to remove
    stop_words = {
        'nearby', 'near', 'close', 'around', 'surrounding', 'proximity', 'within',
        'are', 'is', 'there', 'any', 'the', 'a', 'an', 'to', 'by', 'me',
        'list', 'down', 'show', 'find', 'tell', 'me', 'about',
        'what', 'how', 'where', 'which', 'can', 'you', 'i',
        'want', 'need', 'looking', 'for', 'some'
    }
    
    # Remove question marks, apostrophes, and extra spaces
    cleaned = query_lower.replace('?', ' ').replace("'", ' ').strip()
    
    # Split by common separators (and, or, commas)
    terms = re.split(r'\s+and\s+|\s+or\s+|,\s*', cleaned)
    
    search_terms = []
    for term in terms:
        # Split into words and remove stop words
        words = term.split()
        filtered_words = [w for w in words if w not in stop_words and len(w) > 2]
        
        if filtered_words:
            search_term = ' '.join(filtered_words)
            # Validation - should be 1-3 words and at least 3 characters total
            if 1 <= len(filtered_words) <= 3 and len(search_term) >= 3:
                search_terms.append(search_term)
    
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
    """
    query_lower = query.lower()
    matched_amenities = []
    
    for amenity_type, config in AMENITY_TYPES.items():
        keywords = config.get("keywords", [])
        if any(keyword in query_lower for keyword in keywords):
            matched_amenities.append(amenity_type)
    
    return matched_amenities


def generate_custom_search_link(
    search_term: str,
    latitude: float,
    longitude: float,
    zoom: int = 15
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
    # URL encode the search term
    encoded_term = search_term.replace(' ', '+')
    url = f"https://www.google.com/maps/search/{encoded_term}/@{latitude},{longitude},{zoom}z"
    
    # Create a nice label (title case)
    label = search_term.title()
    
    # Try to find a matching icon and amenity type from predefined types
    icon = "📍"  # Default location icon
    amenity_type = "custom"
    search_lower = search_term.lower()
    for atype, config in AMENITY_TYPES.items():
        if any(keyword in search_lower for keyword in config.get("keywords", [])):
            icon = config["icon"]
            amenity_type = atype
            break
    
    return {
        "type": "custom",
        "amenity_type": amenity_type,  # Add explicit amenity type identifier
        "search_term": search_term,
        "label": label,
        "icon": icon,
        "url": url
    }


def generate_amenity_links(
    latitude: float,
    longitude: float,
    amenity_types: Optional[List[str]] = None,
    zoom: int = 15
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
    # Default to most common amenities if not specified
    if amenity_types is None:
        amenity_types = [
            "hospitals",
            "schools",
            "bus_stops",
            "supermarkets",
            "restaurants",
            "parks"
        ]
    
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
        common_amenities = ["hospitals", "schools", "bus_stops", "supermarkets"]
        suggested_links = generate_amenity_links(latitude, longitude, common_amenities)
    
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
        icon = link.get('icon', '📍')
        formatted += f"- {icon} {label}: {link['url']}\n"
    
    return formatted

