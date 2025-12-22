"""
Loader module for reading and parsing property listing JSON data.
"""
import json
from typing import List, Dict, Any
from pathlib import Path


def load_property_listings(file_path: str) -> List[Dict[str, Any]]:
    """
    Load property listings from a JSON file.
    
    Args:
        file_path: Path to the JSON file containing property listings
        
    Returns:
        List of property listing dictionaries (extracted from 'data' field)
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Extract the 'data' field from each entry in the array
    listings = []
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and 'data' in entry:
                listings.append(entry['data'])
            elif isinstance(entry, dict):
                # If entry is already a listing object
                listings.append(entry)
    
    return listings


def format_listing_for_chunking(listing: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format a listing dictionary for chunking by extracting key information.
    
    Args:
        listing: Raw listing dictionary from JSON
        
    Returns:
        Formatted listing with structured fields for chunking
    """
    # Extract location information
    location = listing.get('location', {})
    location_str = location.get('displayAddress', '')
    
    # Extract property attributes
    attrs = listing.get('propertyAttributes', {})
    
    # Extract amenities
    amenities = listing.get('propertyAmenities') or []
    amenity_names = [a.get('name', '') for a in amenities if isinstance(a, dict)]
    
    # Extract inspection times
    inspections = listing.get('openInspections') or []
    inspection_times = []
    for insp in inspections:
        if isinstance(insp, dict):
            start = insp.get('inspectionStartTime', '')
            end = insp.get('inspectionEndTime', '')
            if start and end:
                inspection_times.append(f"{start} to {end}")
    
    # Extract agent information
    agents = listing.get('propertyAgents') or []
    agent_names = [a.get('fullName', '') for a in agents if isinstance(a, dict)]
    
    # Format pricing information
    price = listing.get('price')
    display_price = listing.get('displayPrice', False)
    auction_start_price = listing.get('auctionStartPrice')
    
    # Format bidding information
    highest_bid = listing.get('highestBid')
    highest_bid_amount = highest_bid.get('bidAmount') if highest_bid and isinstance(highest_bid, dict) else None
    
    formatted = {
        'id': listing.get('id', ''),
        'slug': listing.get('slug', ''),
        'propertyId': listing.get('propertyId', ''),
        'title': listing.get('title', ''),
        'description': listing.get('description', ''),
        'propertyCategory': listing.get('propertyCategory', ''),
        'propertyType': listing.get('propertyType', ''),
        'listingType': listing.get('listingType', ''),
        'listingStatus': listing.get('listingStatus', ''),
        'auctionStatus': listing.get('auctionStatus', ''),
        'location': location_str,
        'streetAddress': location.get('streetAddress', ''),
        'suburb': location.get('suburb', ''),
        'city': location.get('city', ''),
        'state': location.get('state', ''),
        'postalCode': location.get('postalCode', ''),
        'latitude': location.get('latitude'),  # Add latitude for location-based queries
        'longitude': location.get('longitude'),  # Add longitude for location-based queries
        'price': price,
        'displayPrice': display_price,
        'auctionStartPrice': auction_start_price,
        'auctionStartDate': listing.get('auctionStartDate'),
        'auctionEndDate': listing.get('auctionEndDate'),
        'publishedAt': listing.get('publishedAt'),
        'allowPrivateInspection': listing.get('allowPrivateInspection', False),
        'bedrooms': attrs.get('bedrooms'),
        'bathrooms': attrs.get('bathrooms'),
        'toilets': attrs.get('toilets'),
        'garages': attrs.get('garages'),
        'ensuites': attrs.get('ensuites'),
        'landArea': attrs.get('landArea'),
        'landAreaUnit': attrs.get('landAreaUnit', ''),
        'floorArea': attrs.get('floorArea'),
        'floorAreaUnit': attrs.get('floorAreaUnit', ''),
        'frontage': attrs.get('frontage'),
        'frontageUnit': attrs.get('frontageUnit', ''),
        'yearBuilt': attrs.get('yearBuilt'),
        'propertyAge': attrs.get('propertyAge', ''),
        'energyRating': attrs.get('energyRating'),
        'zoning': attrs.get('zoning', ''),
        'highlights': attrs.get('highlights', []),
        'amenities': amenity_names,
        'inspectionTimes': inspection_times,
        'agents': agent_names,
        'activeOfferCount': listing.get('activeOfferCount', 0),
        'activeBidCount': listing.get('activeBidCount', 0),
        'highestBidAmount': highest_bid_amount,
        'winningBid': listing.get('winningBid'),
        'saleHistory': listing.get('saleHistory'),
        'reverseAuctionNextDecreaseAt': listing.get('reverseAuctionNextDecreaseAt'),
        'reverseAuctionDecreaseAmount': listing.get('reverseAuctionDecreaseAmount'),
        'propertyMedia': listing.get('propertyMedia', []),  # Add media array
    }
    
    return formatted

