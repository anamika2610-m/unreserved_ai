"""
Chunker module for splitting property listings into semantic chunks for RAG.
"""
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from uuid import UUID


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
    
    Uses semantic chunking (by topic) rather than fixed-size text splitting
    to preserve complete context for each property aspect.
    """
    
    def __init__(self):
        """Initialize the chunker."""
        pass
    
    @staticmethod
    def _convert_uuids_to_strings(obj: Any) -> Any:
        """
        Recursively convert UUID objects to strings for JSON serialization.
        
        Args:
            obj: Any object that might contain UUIDs
            
        Returns:
            Object with UUIDs converted to strings
        """
        if isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, dict):
            return {key: PropertyListingChunker._convert_uuids_to_strings(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [PropertyListingChunker._convert_uuids_to_strings(item) for item in obj]
        else:
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
        listing_id = listing.get('id', 'unknown')
        property_id = listing.get('propertyId', 'unknown')
        
        location_meta = self._extract_location_metadata(listing)
        
        media_meta = self._extract_media_metadata(listing)
        
        # Chunk 1: Comprehensive Overview
        overview_content = self._create_overview_chunk(listing)
        overview_metadata = self._convert_uuids_to_strings({
                'listing_id': listing_id,
                'property_id': property_id,
                'chunk_type': 'overview',
                'title': listing.get('title', ''),
                'property_type': listing.get('propertyType', ''),
                'location': listing.get('location', ''),
            **location_meta,  # Include lat/long in metadata
            **media_meta  # Include media metadata
        })
        chunks.append(Chunk(
            content=overview_content,
            metadata=overview_metadata,
            chunk_type='overview',
            chunk_index=0,
            listing_id=str(listing_id)  # Convert to string
        ))
        
        # Chunk 2: Pricing and Sale Method
        pricing_content = self._create_pricing_chunk(listing)
        if pricing_content:
            pricing_metadata = self._convert_uuids_to_strings({
                    'listing_id': listing_id,
                    'property_id': property_id,
                    'chunk_type': 'pricing',
                    'listing_type': listing.get('listingType', ''),
                    'auction_status': listing.get('auctionStatus', ''),
                    'price': listing.get('price'),
                'displayPrice': listing.get('displayPrice', False), 
                    **location_meta  # Include lat/long in metadata
            })
            chunks.append(Chunk(
                content=pricing_content,
                metadata=pricing_metadata,
                chunk_type='pricing',
                chunk_index=1,
                listing_id=str(listing_id)  # Convert to string
            ))
        
        # Chunk 3: Specifications and Features
        specs_content = self._create_specifications_chunk(listing)
        if specs_content:
            specs_metadata = self._convert_uuids_to_strings({
                    'listing_id': listing_id,
                    'property_id': property_id,
                    'chunk_type': 'specifications',
                    'bedrooms': listing.get('bedrooms'),
                    'bathrooms': listing.get('bathrooms'),
                    'property_type': listing.get('propertyType', ''),
                    **location_meta  # Include lat/long in metadata
            })
            chunks.append(Chunk(
                content=specs_content,
                metadata=specs_metadata,
                chunk_type='specifications',
                chunk_index=2,
                listing_id=str(listing_id)
            ))
        
        # Chunk 4: Location and Neighborhood
        location_content = self._create_location_chunk(listing)
        if location_content:
            location_chunk_metadata = self._convert_uuids_to_strings({
                    'listing_id': listing_id,
                    'property_id': property_id,
                    'chunk_type': 'location',
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
                **location_meta,  # Include lat/long in metadata
                **media_meta  # Include media metadata
            })
            chunks.append(Chunk(
                content=location_content,
                metadata=location_chunk_metadata,
                chunk_type='location',
                chunk_index=3,
                listing_id=str(listing_id)
            ))
        
        # Chunk 5: Bidding and Auction Details (if applicable)
        bidding_content = self._create_bidding_chunk(listing)
        if bidding_content:
            bidding_metadata = self._convert_uuids_to_strings({
                    'listing_id': listing_id,
                    'property_id': property_id,
                    'chunk_type': 'bidding',
                    'listing_type': listing.get('listingType', ''),
                    'auction_status': listing.get('auctionStatus', ''),
                    **location_meta  # Include lat/long in metadata
            })
            chunks.append(Chunk(
                content=bidding_content,
                metadata=bidding_metadata,
                chunk_type='bidding',
                chunk_index=4,
                listing_id=str(listing_id)
            ))
        
        return chunks
    
    def _extract_location_metadata(self, listing: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract location metadata (latitude, longitude, address) from listing.
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
        media_meta = {}
        
        # Get propertyMedia array
        property_media = listing.get('propertyMedia', [])
        
        if property_media and isinstance(property_media, list) and len(property_media) > 0:
            # Store the entire propertyMedia array as JSON string
            # ChromaDB metadata doesn't support nested objects, so we stringify it
            media_meta['propertyMedia_json'] = json.dumps(property_media)
        
        return media_meta
    
    def _extract_highest_bid_amount(self, listing: Dict[str, Any]) -> Optional[float]:
        """
        Extract highest bid amount from listing.
        Handles both nested highestBid object and flat highestBidAmount field.
        
        Args:
            listing: Formatted listing dictionary
            
        Returns:
            Highest bid amount or None if not available
        """
        highest_bid = listing.get('highestBid')
        if highest_bid and isinstance(highest_bid, dict):
            return highest_bid.get('bidAmount')
        return listing.get('highestBidAmount')
    
    def _format_price(self, amount: Any, label: str) -> str:
        """
        Format a price amount with a label.
        
        Args:
            amount: Price amount (numeric or string)
            label: Label for the price (e.g., "Highest Bid", "Asking Price")
            
        Returns:
            Formatted price string
        """
        if isinstance(amount, (int, float)):
            return f"{label}: ${amount:,.0f}"
        return f"{label}: {amount}"
    
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
        if listing.get('bedrooms'):
            specs.append(f"{listing.get('bedrooms')} bedrooms")
        if listing.get('bathrooms'):
            specs.append(f"{listing.get('bathrooms')} bathrooms")
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
        
        # Check if displayPrice is false, null, empty, or not applicable
        # If so, hide ALL price information
        if not display_price:
            parts.append("Sale Method: " + ("Auction" if listing_type == 'auction' else "Private Sale" if listing_type == 'private_sale' else listing_type))
            # Only include non-price information
            if listing.get('auctionStartDate'):
                parts.append(f"Auction Start: {listing.get('auctionStartDate')}")
            if listing.get('auctionEndDate'):
                parts.append(f"Auction End: {listing.get('auctionEndDate')}")
            # Add price visibility message
            parts.append("Price: Contact agent for pricing")
            # Still include bid/offer counts (not price amounts)
            active_bid_count = listing.get('activeBidCount') or 0
            if active_bid_count > 0:
                parts.append(f"Active Bids: {active_bid_count}")
            active_offer_count = listing.get('activeOfferCount') or 0
            if active_offer_count > 0:
                parts.append(f"Active Offers: {active_offer_count}")
            return "\n".join(parts) if parts else None
        
        # If displayPrice is true, show all price information
        if listing_type == 'auction':
            parts.append("Sale Method: Auction")
            if auction_start_price:
                parts.append(f"Auction Start Price: ${auction_start_price:,.0f}" if isinstance(auction_start_price, (int, float)) else f"Auction Start Price: {auction_start_price}")
            if listing.get('auctionStartDate'):
                parts.append(f"Auction Start: {listing.get('auctionStartDate')}")
            if listing.get('auctionEndDate'):
                parts.append(f"Auction End: {listing.get('auctionEndDate')}")
        elif listing_type == 'private_sale':
            parts.append("Sale Method: Private Sale")
            if price:
                parts.append(f"Asking Price: ${price:,.0f}" if isinstance(price, (int, float)) else f"Asking Price: {price}")
        
        # Current bidding status (only if displayPrice is true)
        active_bid_count = listing.get('activeBidCount') or 0
        if active_bid_count > 0:
            parts.append(f"Active Bids: {active_bid_count}")
            highest_bid_amount = self._extract_highest_bid_amount(listing)
            if highest_bid_amount:
                parts.append(self._format_price(highest_bid_amount, "Highest Bid"))
        
        active_offer_count = listing.get('activeOfferCount') or 0
        if active_offer_count > 0:
            parts.append(f"Active Offers: {active_offer_count}")
        
        # Reverse auction info (only if displayPrice is true)
        if listing.get('reverseAuctionNextDecreaseAt'):
            parts.append(f"Reverse Auction: Next decrease at {listing.get('reverseAuctionNextDecreaseAt')}")
            if listing.get('reverseAuctionDecreaseAmount'):
                parts.append(f"Decrease Amount: ${listing.get('reverseAuctionDecreaseAmount'):,.0f}" if isinstance(listing.get('reverseAuctionDecreaseAmount'), (int, float)) else f"Decrease Amount: {listing.get('reverseAuctionDecreaseAmount')}")
        
        return "\n".join(parts) if parts else None
    
    def _create_specifications_chunk(self, listing: Dict[str, Any]) -> Optional[str]:
        """Create a specifications-specific chunk."""
        parts = []
        
        # Basic specs
        if listing.get('bedrooms'):
            parts.append(f"Bedrooms: {listing.get('bedrooms')}")
        if listing.get('bathrooms'):
            parts.append(f"Bathrooms: {listing.get('bathrooms')}")
        if listing.get('toilets'):
            parts.append(f"Toilets: {listing.get('toilets')}")
        if listing.get('ensuites'):
            parts.append(f"Ensuites: {listing.get('ensuites')}")
        if listing.get('garages'):
            parts.append(f"Garages: {listing.get('garages')}")
        
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
            if listing.get('auctionEndDate'):
                parts.append(f"End Date: {listing.get('auctionEndDate')}")
            
            if listing.get('activeBidCount', 0) > 0:
                parts.append(f"\nCurrent Bidding Status:")
                parts.append(f"Total Bids: {listing.get('activeBidCount')}")
                # Only show highest bid amount if displayPrice is true
                if display_price:
                    highest_bid_amount = self._extract_highest_bid_amount(listing)
                    if highest_bid_amount:
                        parts.append(self._format_price(highest_bid_amount, "Highest Bid"))
        
        # Reverse auction details (only show price amounts if displayPrice is true)
        if listing.get('reverseAuctionNextDecreaseAt'):
            parts.append("\nReverse Auction Details:")
            parts.append(f"Next Price Decrease: {listing.get('reverseAuctionNextDecreaseAt')}")
            if display_price and listing.get('reverseAuctionDecreaseAmount'):
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

