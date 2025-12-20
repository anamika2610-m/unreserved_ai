"""
Schemas for property listing enquiry system.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


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
    """Property listing information from the knowledge base."""
    id: str = Field(..., description="The unique identifier for the property listing")
    property_id: str = Field(..., description="The property ID")
    slug: Optional[str] = Field(None, description="Property slug")
    title: str = Field(..., description="The title of the property listing")
    description: str = Field(..., description="The description of the property listing")
    price: Optional[float] = Field(None, description="The price of the property listing")
    display_price: bool = Field(False, description="Whether the price is displayed")
    auction_start_price: Optional[float] = Field(None, description="Auction start price if applicable")
    location: LocationInfo = Field(..., description="The location information of the property listing")
    property_type: str = Field(..., description="The type of the property listing")
    property_category: str = Field(..., description="The category of the property")
    listing_type: str = Field(..., description="The listing type (auction, private_sale, etc.)")
    listing_status: str = Field(..., description="The status of the listing")
    auction_status: Optional[str] = Field(None, description="Auction status if applicable")
    bedrooms: Optional[int] = Field(None, description="Number of bedrooms")
    bathrooms: Optional[int] = Field(None, description="Number of bathrooms")
    property_features: List[str] = Field(default_factory=list, description="The features/highlights of the property listing")
    property_amenities: List[str] = Field(default_factory=list, description="The amenities of the property listing")
    property_agents: List[PropertyAgent] = Field(default_factory=list, description="List of property agents")
    published_at: Optional[str] = Field(None, description="Publication date")
    auction_start_date: Optional[str] = Field(None, description="Auction start date if applicable")
    auction_end_date: Optional[str] = Field(None, description="Auction end date if applicable")


class BuyerEnquiry(BaseModel):
    """Buyer enquiry input."""
    question: str = Field(..., description="The buyer's question about the property")
    listing_id: Optional[str] = Field(None, description="Optional listing ID if enquiry is about a specific property")
    user_id: Optional[str] = Field(None, description="Optional user ID for logging")
    session_id: Optional[str] = Field(None, description="Optional session ID for tracking")


class DataSource(BaseModel):
    """Information about a data source used in the response."""
    chunk_type: str = Field(..., description="Type of chunk (overview, pricing, specifications, location, bidding)")
    listing_id: str = Field(..., description="Listing ID from which information was retrieved")
    content_preview: str = Field(..., description="Preview of the content used")
    similarity_score: Optional[float] = Field(None, description="Similarity score of the retrieved chunk")


class AIResponse(BaseModel):
    """AI-generated response to buyer enquiry."""
    answer: str = Field(..., description="The AI-generated answer to the buyer's question")
    needs_vendor_contact: bool = Field(False, description="Whether the enquiry requires contacting the vendor/agent")
    escalation_reason: Optional[str] = Field(None, description="Reason for vendor contact if needs_vendor_contact is True")
    data_sources: List[DataSource] = Field(default_factory=list, description="List of data sources used in the response")
    disclaimer: str = Field(
        default="Based on available listing details, this is general information only and does not constitute financial or legal advice. For specific questions or confirmation, please contact the listing agent or vendor.",
        description="Standard disclaimer included in all responses"
    )


class EnquiryLog(BaseModel):
    """Log entry for buyer enquiries."""
    id: Optional[str] = Field(None, description="Log entry ID")
    timestamp: datetime = Field(default_factory=datetime.now, description="When the enquiry was processed")
    question: str = Field(..., description="The buyer's question")
    answer: str = Field(..., description="The AI-generated answer")
    listing_id: Optional[str] = Field(None, description="Listing ID if enquiry was about a specific property")
    user_id: Optional[str] = Field(None, description="User ID if available")
    session_id: Optional[str] = Field(None, description="Session ID if available")
    data_sources: List[DataSource] = Field(default_factory=list, description="Data sources used")
    needs_vendor_contact: bool = Field(False, description="Whether vendor contact was recommended")
    escalation_reason: Optional[str] = Field(None, description="Reason for vendor contact recommendation")
    model_version: Optional[str] = Field(None, description="LLM model version used")
    prompt_version: Optional[str] = Field(None, description="Prompt version used")
    raw_listing_snapshot: Optional[Dict[str, Any]] = Field(None, description="Snapshot of listing data at time of enquiry")


class PropertyListingResponse(BaseModel):
    """Complete response including property listing and AI response."""
    property_listing: Optional[PropertyListing] = Field(None, description="The property listing if specific listing was queried")
    ai_response: AIResponse = Field(..., description="The AI-generated response")
    log_entry: Optional[EnquiryLog] = Field(None, description="Log entry for this enquiry")
