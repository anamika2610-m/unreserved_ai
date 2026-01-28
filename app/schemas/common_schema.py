"""
Common schemas for the Unreserved application.
Includes property listings, enquiries, and response models.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from uuid import UUID


class LocationInfo(BaseModel):
    """Location information for a property."""
    display_address: str = Field(..., description="Full display address")
    street_address: Optional[str] = Field(None, description="Street address")
    suburb: Optional[str] = Field(None, description="Suburb")
    city: Optional[str] = Field(None, description="City")
    state: Optional[str] = Field(None, description="State")
    country: Optional[str] = Field(None, description="Country")
    postal_code: Optional[int] = Field(None, description="Postal code")
    latitude: Optional[float] = Field(None, description="Latitude")
    longitude: Optional[float] = Field(None, description="Longitude")


class PropertyAgent(BaseModel):
    """Property agent information."""
    id: str = Field(..., description="Agent ID")
    full_name: str = Field(..., description="Agent full name")
    is_verified: bool = Field(False, description="Whether agent is verified")
    avatar: Optional[str] = Field(None, description="Agent avatar URL")

class PropertyListing(BaseModel):
    """
    Property listing information.
    NOTE: Keep IDs as `str` if they come from external APIs.
    Change to UUID ONLY if sourced from your DB.
    """
    id: str = Field(..., description="Listing identifier")
    property_id: str = Field(..., description="Property ID")
    slug: Optional[str] = Field(None, description="URL-friendly slug")
    title: str = Field(..., description="Property title")
    description: str = Field(..., description="Property description")
    price: Optional[float] = Field(None, description="Property price")
    display_price: bool = Field(False, description="Whether to display price")
    auction_start_price: Optional[float] = Field(None, description="Auction start price")
    location: LocationInfo = Field(..., description="Property location")
    property_type: str = Field(..., description="Type of property")
    property_category: str = Field(..., description="Property category")
    listing_type: str = Field(..., description="Listing type (e.g., sale, auction)")
    listing_status: str = Field(..., description="Listing status")
    auction_status: Optional[str] = Field(None, description="Auction status")
    bedrooms: Optional[int] = Field(None, description="Number of bedrooms")
    bathrooms: Optional[int] = Field(None, description="Number of bathrooms")
    property_features: List[str] = Field(default_factory=list, description="Property features")
    property_amenities: List[str] = Field(default_factory=list, description="Property amenities")
    property_agents: List[PropertyAgent] = Field(default_factory=list, description="Property agents")
    published_at: Optional[str] = Field(None, description="Publication date")
    auction_start_date: Optional[str] = Field(None, description="Auction start date")
    # auction_end_date: Optional[str] = Field(None, description="Auction end date")

class BuyerEnquiry(BaseModel):
    """
    Buyer enquiry input.
    UUIDs are REQUIRED for consistency with DB & repositories.
    """
    question: str = Field(..., description="Buyer's question")
    listing_id: Optional[UUID] = Field(None, description="Listing ID (UUID)")
    user_id: Optional[UUID] = Field(None, description="User ID (UUID)")


class DataSource(BaseModel):
    """Information about a data source used in the response."""
    chunk_type: str = Field(..., description="Type of data chunk")
    listing_id: Optional[str] = Field(None, description="Listing ID (None for generic knowledge queries)")
    content_preview: str = Field(..., description="Preview of content")
    similarity_score: Optional[float] = Field(None, description="Similarity score (0.0-1.0)")


class AIResponse(BaseModel):
    """AI-generated response to buyer enquiry."""
    answer: str = Field(..., description="AI-generated answer")
    needs_vendor_contact: bool = Field(False, description="Whether vendor contact is needed")
    escalation_reason: Optional[str] = Field(None, description="Reason for escalation (if any)")
    data_sources: List[DataSource] = Field(default_factory=list, description="Data sources used")
    disclaimer: Optional[str] = Field(None, description="Optional disclaimer")
class EnquiryLog(BaseModel):
    """Log entry for buyer enquiries."""
    id: Optional[str] = Field(None, description="Log entry ID")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of the enquiry"
    )
    question: str = Field(..., description="User's question")
    answer: str = Field(..., description="AI-generated answer")
    listing_id: Optional[UUID] = Field(None, description="Listing ID (UUID)")
    user_id: Optional[UUID] = Field(None, description="User ID (UUID)")
    data_sources: List[DataSource] = Field(default_factory=list, description="Data sources used")
    needs_vendor_contact: bool = Field(False, description="Whether vendor contact is needed")
    escalation_reason: Optional[str] = Field(None, description="Reason for escalation (if any)")
    model_version: Optional[str] = Field(None, description="AI model version used")
    prompt_version: Optional[str] = Field(None, description="Prompt version used")
    raw_listing_snapshot: Optional[Dict[str, Any]] = Field(None, description="Raw listing snapshot")


class PropertyListingResponse(BaseModel):
    """Complete response including property listing and AI response."""
    property_listing: Optional[PropertyListing] = Field(None, description="Property listing (if available)")
    ai_response: AIResponse = Field(..., description="AI-generated response")
    log_entry: Optional[EnquiryLog] = Field(None, description="Log entry (if available)")
