"""
Chunker module for splitting property listings into semantic chunks for RAG.
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from uuid import UUID

# Constants
CHUNK_TYPE_OVERVIEW = 'overview'
CHUNK_TYPE_PRICING = 'pricing'
CHUNK_TYPE_SPECIFICATIONS = 'specifications'
CHUNK_TYPE_LOCATION = 'location'
CHUNK_TYPE_BIDDING = 'bidding'

DEFAULT_LISTING_ID = 'unknown'
DEFAULT_PROPERTY_ID = 'unknown'


@dataclass
class Chunk:
    """Represents a single chunk of property listing data."""
    content: str
    metadata: Dict[str, Any]
    chunk_type: str
    chunk_index: int
    listing_id: str


class PropertyListingChunker:
    """
    Chunks property listings into semantic pieces for better retrieval.
    
    Strategy:
    1. Create a comprehensive overview chunk (all key info)
    2. Create specific chunks for: pricing, specifications, location, bidding
    3. Each chunk includes metadata for filtering and source tracking
    """
    
    def __init__(self):
        """Initialize the chunker."""
        pass  # No initialization needed currently
    
    @staticmethod
    def _convert_uuids_to_strings(obj: Any) -> Any:
        """
        Recursively convert any UUID values in a nested structure to strings.
        
        This ensures all metadata is JSON-serializable and safe to store
        in PostgreSQL JSONB columns.
        
        Args:
            obj: Any nested structure (dict, list, tuple, UUID, etc.)
            
        Returns:
            Same structure with any uuid.UUID instances converted to str
        """
        import uuid
        
        # Primitive types are returned as-is
        if isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        
        # Convert UUIDs to strings
        if isinstance(obj, uuid.UUID):
            return str(obj)
        
        # Recurse into dictionaries
        if isinstance(obj, dict):
            return {k: PropertyListingChunker._convert_uuids_to_strings(v) for k, v in obj.items()}
        
        # Recurse into lists/tuples
        if isinstance(obj, (list, tuple)):
            return [PropertyListingChunker._convert_uuids_to_strings(v) for v in obj]
        
        # Fallback: return object as-is
        return obj
    
    def chunk_listing(self, listing: Dict[str, Any]) -> List[Chunk]:
        """
        Chunk a single property listing into multiple semantic chunks.
        
        Args:
            listing: Formatted listing dictionary from loader
            
        Returns:
            List of Chunk objects
        """
        chunks = []
        listing_id = listing.get('id', DEFAULT_LISTING_ID)
        property_id = listing.get('propertyId', DEFAULT_PROPERTY_ID)
        listing_id_str = str(listing_id)
        
        # Extract location metadata (lat/long) to include in ALL chunks
        location_meta = self._extract_location_metadata(listing)
        media_meta = self._extract_media_metadata(listing)
        
        # Chunk 1: Comprehensive Overview (always created)
        overview_content = self._create_overview_chunk(listing)
        overview_metadata = self._build_base_metadata(
            listing_id=listing_id,
            property_id=property_id,
            chunk_type=CHUNK_TYPE_OVERVIEW,
            listing=listing,
            location_meta=location_meta,
            media_meta=media_meta,
            additional_fields={
                'title': listing.get('title', ''),
                'property_type': listing.get('propertyType', ''),
                'location': listing.get('location', ''),
            }
        )
        chunks.append(self._create_chunk(
            content=overview_content,
            metadata=overview_metadata,
            chunk_type=CHUNK_TYPE_OVERVIEW,
            chunk_index=0,
            listing_id=listing_id_str
        ))
        
        # Chunk 2: Pricing and Sale Method
        pricing_content = self._create_pricing_chunk(listing)
        if pricing_content:
            pricing_metadata = self._build_base_metadata(
                listing_id=listing_id,
                property_id=property_id,
                chunk_type=CHUNK_TYPE_PRICING,
                listing=listing,
                location_meta=location_meta,
                additional_fields={
                    'listing_type': listing.get('listingType', ''),
                    'auction_status': listing.get('auctionStatus', ''),
                    'price': listing.get('price'),
                    'displayPrice': listing.get('displayPrice', False),
                }
            )
            chunks.append(self._create_chunk(
                content=pricing_content,
                metadata=pricing_metadata,
                chunk_type=CHUNK_TYPE_PRICING,
                chunk_index=1,
                listing_id=listing_id_str
            ))
        
        # Chunk 3: Specifications and Features
        specs_content = self._create_specifications_chunk(listing)
        if specs_content:
            specs_metadata = self._build_base_metadata(
                listing_id=listing_id,
                property_id=property_id,
                chunk_type=CHUNK_TYPE_SPECIFICATIONS,
                listing=listing,
                location_meta=location_meta,
                additional_fields={
                    'bedrooms': listing.get('bedrooms'),
                    'bathrooms': listing.get('bathrooms'),
                    'property_type': listing.get('propertyType', ''),
                }
            )
            chunks.append(self._create_chunk(
                content=specs_content,
                metadata=specs_metadata,
                chunk_type=CHUNK_TYPE_SPECIFICATIONS,
                chunk_index=2,
                listing_id=listing_id_str
            ))
        
        # Chunk 4: Location and Neighborhood
        location_content = self._create_location_chunk(listing)
        if location_content:
            location_metadata = self._build_base_metadata(
                listing_id=listing_id,
                property_id=property_id,
                chunk_type=CHUNK_TYPE_LOCATION,
                listing=listing,
                location_meta=location_meta,
                media_meta=media_meta,
                additional_fields={
                    'slug': listing.get('slug', ''),
                    'title': listing.get('title', ''),
                    'listing_type': listing.get('listingType', ''),
                    'listing_status': listing.get('listingStatus', ''),
                    'auction_status': listing.get('auctionStatus', ''),
                    'price': listing.get('price'),
                    'bedrooms': listing.get('bedrooms'),
                    'bathrooms': listing.get('bathrooms'),
                    'landArea': listing.get('landArea'),
                    'landArea_unit': listing.get('landAreaUnit', ''),
                    'suburb': listing.get('suburb', ''),
                    'city': listing.get('city', ''),
                    'state': listing.get('state', ''),
                }
            )
            chunks.append(self._create_chunk(
                content=location_content,
                metadata=location_metadata,
                chunk_type=CHUNK_TYPE_LOCATION,
                chunk_index=3,
                listing_id=listing_id_str
            ))
        
        # Chunk 5: Bidding and Auction Details (if applicable)
        bidding_content = self._create_bidding_chunk(listing)
        if bidding_content:
            bidding_metadata = self._build_base_metadata(
                listing_id=listing_id,
                property_id=property_id,
                chunk_type=CHUNK_TYPE_BIDDING,
                listing=listing,
                location_meta=location_meta,
                additional_fields={
                    'listing_type': listing.get('listingType', ''),
                    'auction_status': listing.get('auctionStatus', ''),
                }
            )
            chunks.append(self._create_chunk(
                content=bidding_content,
                metadata=bidding_metadata,
                chunk_type=CHUNK_TYPE_BIDDING,
                chunk_index=4,
                listing_id=listing_id_str
            ))
        
        return chunks
    
    def _extract_location_metadata(self, listing: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract location metadata (latitude, longitude, address, suburb) from listing.
        This will be included in all chunk metadata for location-based queries.
        
        Args:
            listing: Formatted listing dictionary
            
        Returns:
            Dictionary with location metadata
        """
        location_meta = {}
        
        # Extract latitude and longitude
        if listing.get('latitude') is not None:
            location_meta['latitude'] = listing.get('latitude')
        if listing.get('longitude') is not None:
            location_meta['longitude'] = listing.get('longitude')
        if listing.get('location'):
            location_meta['displayAddress'] = listing.get('location')
        
        # Extract suburb, city, state for same-suburb property matching
        if listing.get('suburb'):
            location_meta['suburb'] = listing.get('suburb')
        if listing.get('city'):
            location_meta['city'] = listing.get('city')
        if listing.get('state'):
            location_meta['state'] = listing.get('state')
        if listing.get('postalCode'):
            location_meta['postalCode'] = listing.get('postalCode')
        
        return location_meta
    
    def _extract_media_metadata(self, listing: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract media metadata (images) from listing.
        Stores the entire propertyMedia array as JSON string.
        
        Args:
            listing: Formatted listing dictionary
            
        Returns:
            Dictionary with media metadata
        """
        import json
        media_meta = {}
        
        # Get propertyMedia array
        property_media = listing.get('propertyMedia', [])
        
        if property_media and isinstance(property_media, list) and len(property_media) > 0:
            # Store the entire propertyMedia array as JSON string
            # ChromaDB metadata doesn't support nested objects, so we stringify it
            media_meta['propertyMedia_json'] = json.dumps(property_media)
        
        return media_meta
    
    def _create_overview_chunk(self, listing: Dict[str, Any]) -> str:
        """Create a comprehensive overview chunk."""
        parts = []
        
        parts.append(f"Property: {listing.get('title', 'N/A')}")
        parts.append(f"Type: {listing.get('propertyType', 'N/A')} ({listing.get('propertyCategory', 'N/A')})")
        parts.append(f"Location: {listing.get('location', 'N/A')}")
        
        if listing.get('description'):
            parts.append(f"\nDescription: {listing.get('description')}")
        
        # Key specs summary
        specs = []
        bedrooms = listing.get('bedrooms')
        if bedrooms is not None:  # 0 is a valid value, so check for None explicitly
            specs.append(f"{bedrooms} bedrooms")
        bathrooms = listing.get('bathrooms')
        if bathrooms is not None:  # 0 is a valid value, so check for None explicitly
            specs.append(f"{bathrooms} bathrooms")
        if listing.get('garages'):
            specs.append(f"{listing.get('garages')} garages")
        if listing.get('floorArea'):
            unit = listing.get('floorAreaUnit', 'sqm')
            specs.append(f"{listing.get('floorArea')} {unit} floor area")
        if listing.get('landArea'):
            unit = listing.get('landAreaUnit', 'sqm')
            specs.append(f"{listing.get('landArea')} {unit} land")
        
        if specs:
            parts.append(f"\nKey Features: {', '.join(specs)}")
        
        # Zoning (important planning information)
        if listing.get('zoning'):
            parts.append(f"\nZoning: {listing.get('zoning')}")
        
        # Highlights
        highlights = listing.get('highlights', [])
        if highlights:
            parts.append(f"\nHighlights: {', '.join(highlights)}")
        
        # Amenities
        amenities = listing.get('amenities', [])
        if amenities:
            parts.append(f"\nAmenities: {', '.join(amenities)}")
        
        return "\n".join(parts)
    
    def _create_pricing_chunk(self, listing: Dict[str, Any]) -> Optional[str]:
        """Create a pricing-specific chunk."""
        parts = []
        
        listing_type = listing.get('listingType', '')
        price = listing.get('price')
        display_price = listing.get('displayPrice', False)
        auction_start_price = listing.get('auctionStartPrice')
        
        if listing_type == 'auction':
            parts.append("Sale Method: Auction")
            if auction_start_price:
                parts.append(f"Auction Start Price: ${auction_start_price:,.0f}" if isinstance(auction_start_price, (int, float)) else f"Auction Start Price: {auction_start_price}")
            if listing.get('auctionStartDate'):
                parts.append(f"Auction Start: {listing.get('auctionStartDate')}")
        elif listing_type == 'private_sale':
            parts.append("Sale Method: Private Sale")
            if price and display_price:
                parts.append(f"Asking Price: ${price:,.0f}" if isinstance(price, (int, float)) else f"Asking Price: {price}")
            elif price and not display_price:
                parts.append("Price: Contact agent for pricing")
        
        # Current bidding status
        active_bid_count = listing.get('activeBidCount') or 0
        if active_bid_count > 0:
            parts.append(f"Active Bids: {active_bid_count}")
            if listing.get('highestBidAmount'):
                parts.append(f"Highest Bid: ${listing.get('highestBidAmount'):,.0f}" if isinstance(listing.get('highestBidAmount'), (int, float)) else f"Highest Bid: {listing.get('highestBidAmount')}")
        
        active_offer_count = listing.get('activeOfferCount') or 0
        if active_offer_count > 0:
            parts.append(f"Active Offers: {active_offer_count}")
        
        # Reverse auction info
        if listing.get('reverseAuctionNextDecreaseAt'):
            parts.append(f"Reverse Auction: Next decrease at {listing.get('reverseAuctionNextDecreaseAt')}")
            if listing.get('reverseAuctionDecreaseAmount'):
                parts.append(f"Decrease Amount: ${listing.get('reverseAuctionDecreaseAmount'):,.0f}" if isinstance(listing.get('reverseAuctionDecreaseAmount'), (int, float)) else f"Decrease Amount: {listing.get('reverseAuctionDecreaseAmount')}")
        
        return "\n".join(parts) if parts else None
    
    def _create_specifications_chunk(self, listing: Dict[str, Any]) -> Optional[str]:
        """Create a specifications-specific chunk."""
        parts = []
        
        # Basic specs
        bedrooms = listing.get('bedrooms')
        if bedrooms is not None:  # 0 is a valid value, so check for None explicitly
            parts.append(f"Bedrooms: {bedrooms}")
        bathrooms = listing.get('bathrooms')
        if bathrooms is not None:  # 0 is a valid value, so check for None explicitly
            parts.append(f"Bathrooms: {bathrooms}")
        toilets = listing.get('toilets')
        if toilets is not None:  # 0 is a valid value, so check for None explicitly
            parts.append(f"Toilets: {toilets}")
        ensuites = listing.get('ensuites')
        if ensuites is not None:  # 0 is a valid value, so check for None explicitly
            parts.append(f"Ensuites: {ensuites}")
        garages = listing.get('garages')
        if garages is not None:  # 0 is a valid value, so check for None explicitly
            parts.append(f"Garages: {garages}")
        car_ports = listing.get('carPorts')
        if car_ports is not None:  # 0 is a valid value, so check for None explicitly
            parts.append(f"Car Ports: {car_ports}")
        open_parking = listing.get('openParkingSpace')
        if open_parking is not None:  # 0 is a valid value, so check for None explicitly
            parts.append(f"Open Parking Spaces: {open_parking}")
        
        # Areas
        if listing.get('floorArea'):
            unit = listing.get('floorAreaUnit', 'sqm')
            parts.append(f"Floor Area: {listing.get('floorArea')} {unit}")
        if listing.get('landArea'):
            unit = listing.get('landAreaUnit', 'sqm')
            parts.append(f"Land Area: {listing.get('landArea')} {unit}")
        if listing.get('frontage'):
            unit = listing.get('frontageUnit', 'm')
            parts.append(f"Frontage: {listing.get('frontage')} {unit}")
        
        # Additional details
        if listing.get('yearBuilt'):
            parts.append(f"Year Built: {listing.get('yearBuilt')}")
        if listing.get('propertyAge'):
            parts.append(f"Property Age: {listing.get('propertyAge')}")
        if listing.get('energyRating'):
            parts.append(f"Energy Rating: {listing.get('energyRating')}")
        if listing.get('zoning'):
            parts.append(f"Zoning: {listing.get('zoning')}")
        
        # Highlights
        highlights = listing.get('highlights', [])
        if highlights:
            parts.append(f"\nSpecial Features: {', '.join(highlights)}")
        
        return "\n".join(parts) if parts else None
    
    def _create_location_chunk(self, listing: Dict[str, Any]) -> Optional[str]:
        """Create a location-specific chunk."""
        parts = []
        
        location = listing.get('location', '')
        if location:
            parts.append(f"Address: {location}")
        
        street = listing.get('streetAddress')
        suburb = listing.get('suburb')
        city = listing.get('city')
        state = listing.get('state')
        postal = listing.get('postalCode')
        
        if street:
            parts.append(f"Street: {street}")
        if suburb:
            parts.append(f"Suburb: {suburb}")
        if city:
            parts.append(f"City: {city}")
        if state:
            parts.append(f"State: {state}")
        if postal:
            parts.append(f"Postal Code: {postal}")
        
        # Inspection information
        inspections = listing.get('inspectionTimes', [])
        if inspections:
            parts.append(f"\nOpen Inspections:")
            for insp_time in inspections:
                parts.append(f"  - {insp_time}")
        
        if listing.get('allowPrivateInspection'):
            parts.append("\nPrivate inspections available by appointment")
        
        # Agent information
        agents = listing.get('agents', [])
        if agents:
            parts.append(f"\nContact Agents: {', '.join(agents)}")
        
        return "\n".join(parts) if parts else None
    
    def _create_bidding_chunk(self, listing: Dict[str, Any]) -> Optional[str]:
        """Create a bidding/auction-specific chunk."""
        parts = []
        
        listing_type = listing.get('listingType', '')
        auction_status = listing.get('auctionStatus', '')
        display_price = listing.get('displayPrice', False)  
        
        if listing_type == 'auction':
            parts.append("Auction Details:")
            parts.append(f"Status: {auction_status}")
            
            if listing.get('auctionStartDate'):
                parts.append(f"Start Date: {listing.get('auctionStartDate')}")

            
            if listing.get('activeBidCount', 0) > 0:
                parts.append(f"\nCurrent Bidding Status:")
                parts.append(f"Total Bids: {listing.get('activeBidCount')}")
                if listing.get('highestBidAmount'):
                    parts.append(f"Highest Bid: ${listing.get('highestBidAmount'):,.0f}" if isinstance(listing.get('highestBidAmount'), (int, float)) else f"Highest Bid: {listing.get('highestBidAmount')}")
        
        # Reverse auction details
        if listing.get('reverseAuctionNextDecreaseAt'):
            parts.append("\nReverse Auction Details:")
            parts.append(f"Next Price Decrease: {listing.get('reverseAuctionNextDecreaseAt')}")
            if listing.get('reverseAuctionDecreaseAmount'):
                parts.append(f"Decrease Amount: ${listing.get('reverseAuctionDecreaseAmount'):,.0f}" if isinstance(listing.get('reverseAuctionDecreaseAmount'), (int, float)) else f"Decrease Amount: {listing.get('reverseAuctionDecreaseAmount')}")
        
        # Sale history (only show price if displayPrice is true)
        if display_price:
            sale_history = listing.get('saleHistory')
            if sale_history and isinstance(sale_history, dict):
                sale_price = sale_history.get('salePrice')
                if sale_price:
                    parts.append(f"\nPrevious Sale Price: ${sale_price:,.0f}" if isinstance(sale_price, (int, float)) else f"\nPrevious Sale Price: {sale_price}")
        
        return "\n".join(parts) if parts else None
    
    def chunk_all_listings(self, listings: List[Dict[str, Any]]) -> List[Chunk]:
        """
        Chunk multiple listings.
        
        Args:
            listings: List of formatted listing dictionaries
            
        Returns:
            List of all Chunk objects from all listings
        """
        all_chunks = []
        for listing in listings:
            chunks = self.chunk_listing(listing)
            all_chunks.extend(chunks)
        return all_chunks

    def _build_base_metadata(
        self,
        listing_id: Any,
        property_id: Any,
        chunk_type: str,
        listing: Dict[str, Any],
        location_meta: Dict[str, Any],
        media_meta: Optional[Dict[str, Any]] = None,
        additional_fields: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build base metadata for a chunk.
        
        Args:
            listing_id: Listing ID
            property_id: Property ID
            chunk_type: Type of chunk
            listing: Full listing dictionary
            location_meta: Location metadata
            media_meta: Optional media metadata
            additional_fields: Optional additional fields to include
            
        Returns:
            Metadata dictionary with UUIDs converted to strings
        """
        metadata = {
            'listing_id': listing_id,
            'property_id': property_id,
            'chunk_type': chunk_type,
        }
        
        if additional_fields:
            metadata.update(additional_fields)
        
        metadata.update(location_meta)
        
        if media_meta:
            metadata.update(media_meta)
        
        return self._convert_uuids_to_strings(metadata)
    
    def _create_chunk(
        self,
        content: str,
        metadata: Dict[str, Any],
        chunk_type: str,
        chunk_index: int,
        listing_id: str
    ) -> Chunk:
        """
        Create a Chunk object.
        
        Args:
            content: Chunk content
            metadata: Chunk metadata
            chunk_type: Type of chunk
            chunk_index: Index of chunk
            listing_id: Listing ID (as string)
            
        Returns:
            Chunk object
        """
        return Chunk(
            content=content,
            metadata=metadata,
            chunk_type=chunk_type,
            chunk_index=chunk_index,
            listing_id=listing_id
        )

