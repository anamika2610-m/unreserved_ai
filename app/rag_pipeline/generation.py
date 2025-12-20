"""
Generation module for creating AI responses to buyer enquiries.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime
from app.rag_pipeline.llms import get_llm_client, get_model_config, get_model_name, create_chat_completion
from app.rag_pipeline.prompts import SYSTEM_PROMPT, create_user_prompt, create_bid_advice_prompt
from app.rag_pipeline.schemas import AIResponse, DataSource, EnquiryLog
from app.rag_pipeline.augmentation import QueryAugmenter
from app.rag_pipeline.preprocess import detect_enquiry_type
from app.rag_pipeline.postprocess import sanitize_response
from app.rag_pipeline.google_maps_links import generate_context_aware_links, detect_amenity_query, extract_amenity_search_terms, is_amenity_query


class ResponseGenerator:
    """
    Generates AI responses to buyer enquiries with proper guardrails and logging.
    """
    
    def __init__(
        self,
        augmenter: Optional[QueryAugmenter] = None,
        collection_name: str = "property_listings",
        persist_directory: str = "./chroma_db"
    ):
        """
        Initialize the response generator.
        
        Args:
            augmenter: Optional pre-initialized query augmenter
            collection_name: Name of the ChromaDB collection
            persist_directory: Directory where ChromaDB data is persisted
        """
        if augmenter is None:
            self.augmenter = QueryAugmenter(
                collection_name=collection_name,
                persist_directory=persist_directory
            )
        else:
            self.augmenter = augmenter
        
        self.model_config = get_model_config()
        self.model_name = get_model_name()
    
    def generate_response(
        self,
        query: str,
        listing_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        n_retrieval_results: int = 8
    ) -> Dict[str, Any]:
        """
        Generate a complete AI response to a buyer enquiry.
        
        Args:
            query: The buyer's question
            listing_id: Optional listing ID if enquiry is about a specific property
            user_id: Optional user ID for logging
            n_retrieval_results: Number of chunks to retrieve
            
        Returns:
            Dictionary containing:
            - ai_response: AIResponse object
            - log_entry: EnquiryLog object
        """
        # Augment query with retrieved context
        context, data_sources, location_context = self.augmenter.augment_query(
            query=query,
            listing_id=listing_id,
            n_results=n_retrieval_results
        )
        
        # Generate Google Maps amenity links if we detect amenity queries
        amenity_links = []
        
        # Check if this is an amenity query (must explicitly ask about nearby places)
        has_amenity_query = is_amenity_query(query)
        
        # Try to get location data from either location_context or direct retrieval
        latitude = None
        longitude = None
        
        if location_context and location_context.get('listing_location'):
            # Location context available (for location queries)
            listing_loc = location_context['listing_location']
            latitude = listing_loc.get('latitude')
            longitude = listing_loc.get('longitude')
        elif has_amenity_query and listing_id:
            # Amenity query detected but no location_context - fetch location directly
            try:
                property_data = self.augmenter.retriever.vector_store.get_property_location(listing_id)
                if property_data:
                    latitude = property_data.get('latitude')
                    longitude = property_data.get('longitude')
            except Exception as e:
                # If we can't get location, amenity links won't be generated
                pass
        
        # Generate amenity links if we have location and detected an amenity query
        if latitude and longitude and has_amenity_query:
            links_data = generate_context_aware_links(
                query=query,
                latitude=latitude,
                longitude=longitude,
                include_common=False  # Only show specifically requested amenities
            )
            amenity_links = links_data['all_links']
        
        # Check data sufficiency
        is_sufficient, insufficiency_reason = self.augmenter.check_data_sufficiency(
            query=query,
            retrieved_context=context,
            data_sources=data_sources
        )
        
        # Determine if vendor contact is needed (instead of human agent escalation)
        needs_vendor_contact = not is_sufficient
        escalation_reason = insufficiency_reason
        
        # If data is insufficient, generate generic vendor contact message
        if needs_vendor_contact:
            vendor_contact_message = self._generate_vendor_contact_message(query, insufficiency_reason)
            disclaimer = "Based on available listing details, this is general information only and does not constitute financial or legal advice. For specific questions or confirmation, please contact the listing agent or vendor."
            
            ai_response = AIResponse(
                answer=vendor_contact_message,
                needs_vendor_contact=True,
                escalation_reason=escalation_reason,
                data_sources=data_sources,
                disclaimer=disclaimer
            )
            
            # Sanitize response to filter harmful content
            ai_response = sanitize_response(ai_response)
            
            log_entry = EnquiryLog(
                question=query,
                answer=vendor_contact_message,
                listing_id=listing_id,
                user_id=user_id,
                session_id=session_id,
                data_sources=data_sources,
                needs_vendor_contact=True,
                escalation_reason=escalation_reason,
                model_version=self.model_name,
                prompt_version="1.0",
                timestamp=datetime.now()
            )
            
            return {
                "ai_response": ai_response,
                "log_entry": log_entry,
                "nearby_properties": [],  # Empty for insufficient data cases
                "amenity_links": amenity_links  # Google Maps links
            }
        
        # Detect enquiry type for specialized prompts
        enquiry_type = detect_enquiry_type(query)
        
        # Standard disclaimer
        disclaimer = "Based on available listing details, this is general information only and does not constitute financial or legal advice. For specific questions or confirmation, please contact the listing agent or vendor."
        
        # Create appropriate prompt
        if enquiry_type == 'bidding' or 'bid' in query.lower() or 'offer' in query.lower():
            user_prompt = create_bid_advice_prompt(query, context)
        else:
            user_prompt = create_user_prompt(query, context)
        
        # Generate response with LLM
        try:
            response = create_chat_completion(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                model=self.model_config["model"],
                temperature=self.model_config["temperature"],
                max_tokens=self.model_config["max_tokens"]
            )
            
            answer = response.choices[0].message.content.strip()
            
            # Ensure response follows the required format
            answer = self._format_response(answer, query)
            
            # Ensure disclaimer is included
            if disclaimer.lower() not in answer.lower():
                answer += f"\n\n---\n\n{disclaimer}"
            
            # Check for escalation triggers in the response
            escalation_keywords = [
                "not available", "not specified", "not found", "not provided",
                "contact the agent", "speak with", "consult with", "contact the vendor"
            ]
            if not needs_vendor_contact:
                # Check if LLM indicates need for vendor contact
                answer_lower = answer.lower()
                if any(keyword in answer_lower for keyword in escalation_keywords):
                    # Count how many times these phrases appear
                    escalation_count = sum(1 for kw in escalation_keywords if kw in answer_lower)
                    if escalation_count >= 2:  # Multiple mentions suggest insufficient data
                        needs_vendor_contact = True
                        escalation_reason = "Response indicates multiple information gaps requiring vendor contact."
                        # Replace answer with vendor contact message
                        answer = self._generate_vendor_contact_message(query, escalation_reason)
        
        except Exception as e:
            # Fallback response if LLM fails
            disclaimer = "Based on available listing details, this is general information only and does not constitute financial or legal advice. For specific questions or confirmation, please contact the listing agent or vendor."
            answer = self._generate_vendor_contact_message(
                query, 
                f"System error occurred: {str(e)}"
            )
            needs_vendor_contact = True
            escalation_reason = f"LLM generation error: {str(e)}"
        
        # Create AI response object
        ai_response = AIResponse(
            answer=answer,
            needs_vendor_contact=needs_vendor_contact,
            escalation_reason=escalation_reason,
            data_sources=data_sources,
            disclaimer=disclaimer
        )
        
        # Sanitize response to filter harmful content
        ai_response = sanitize_response(ai_response)
        
        # Create log entry
        log_entry = EnquiryLog(
            question=query,
            answer=answer,
            listing_id=listing_id,
            user_id=user_id,
            session_id=session_id,
            data_sources=data_sources,
            needs_vendor_contact=needs_vendor_contact,
            escalation_reason=escalation_reason,
            model_version=self.model_name,
            prompt_version="1.0",
            timestamp=datetime.now()
        )
        
        # Extract nearby properties JSON if available
        nearby_properties_json = []
        if location_context and location_context.get('nearby_properties_json'):
            nearby_properties_json = location_context['nearby_properties_json']
        
        return {
            "ai_response": ai_response,
            "log_entry": log_entry,
            "nearby_properties": nearby_properties_json,
            "amenity_links": amenity_links  # Google Maps links for amenities
        }
    
    def generate_response_from_enquiry(
        self,
        enquiry_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate response from preprocessed enquiry data.
        
        Args:
            enquiry_data: Dictionary from preprocess_enquiry()
            
        Returns:
            Dictionary with ai_response and log_entry
        """
        return self.generate_response(
            query=enquiry_data["normalized_query"],
            listing_id=enquiry_data.get("listing_id"),
            user_id=enquiry_data.get("user_id"),
            session_id=enquiry_data.get("session_id")
        )
    
    def _format_response(self, answer: str, query: str) -> str:
        """
        Ensure response follows the required markdown format.
        
        Args:
            answer: Raw LLM response
            query: Original query for context
            
        Returns:
            Formatted response with proper markdown structure
        """
        # Check if response already has the required format
        has_main_answer = "## [Main Answer]" in answer or "## Main Answer" in answer
        has_supporting = "## [Supporting Details]" in answer or "## Supporting Details" in answer
        
        if has_main_answer and has_supporting:
            # Response already formatted, just ensure proper markdown
            return answer
        
        # If not formatted, try to structure it
        # Split answer into sentences
        sentences = [s.strip() for s in answer.split('.') if s.strip()]
        
        if len(sentences) == 0:
            return answer
        
        # Build formatted response
        formatted = "## [Main Answer]\n\n"
        
        # Main answer: first 1-3 sentences
        main_sentences = sentences[:min(3, len(sentences))]
        formatted += '. '.join(main_sentences)
        if not main_sentences[-1].endswith('.'):
            formatted += '.'
        formatted += "\n\n"
        
        # Supporting details: next 2-4 sentences
        if len(sentences) > 3:
            formatted += "## [Supporting Details]\n\n"
            supporting_sentences = sentences[3:min(7, len(sentences))]
            formatted += '. '.join(supporting_sentences)
            if not supporting_sentences[-1].endswith('.'):
                formatted += '.'
            formatted += "\n\n"
        
        # Add follow-up suggestion if there's more content
        if len(sentences) > 7:
            formatted += "## [Follow-up Suggestion]\n\n"
            formatted += "Would you like to know more about this property or have additional questions?\n\n"
        
        # Add any remaining content
        remaining = '. '.join(sentences[7:]) if len(sentences) > 7 else ""
        if remaining:
            formatted += remaining
            if not remaining.endswith('.'):
                formatted += '.'
            formatted += "\n\n"
        
        return formatted
    
    def _generate_vendor_contact_message(self, query: str, reason: Optional[str] = None) -> str:
        """
        Generate a generic message directing user to contact the vendor.
        Follows the required markdown format.
        
        Args:
            query: The original query
            reason: Optional reason for vendor contact
            
        Returns:
            Formatted message directing to vendor contact in required format
        """
        formatted = "## [Main Answer]\n\n"
        formatted += (
            "I apologize, but I don't have sufficient information in the available listing data "
            "to provide a complete answer to your question."
        )
        
        if reason:
            formatted += f" ({reason})"
        formatted += "\n\n"
        
        formatted += "## [Supporting Details]\n\n"
        formatted += (
            "For detailed information about this property, please contact the vendor or listing agent directly. "
            "They will be able to provide you with the specific details you're looking for."
        )
        formatted += "\n\n"
        
        formatted += "## [Follow-up Suggestion]\n\n"
        formatted += "Would you like to contact the vendor or listing agent to get more information about this property?\n\n"
        
        disclaimer = "Based on available listing details, this is general information only and does not constitute financial or legal advice. For specific questions or confirmation, please contact the listing agent or vendor."
        formatted += f"---\n\n{disclaimer}"
        
        return formatted


# Prevent running this module directly
if __name__ == "__main__":
    import sys
    from pathlib import Path
    
    print("=" * 70)
    print("ERROR: This module cannot be run directly.")
    print("=" * 70)
    print("\nThis is a library module. To test the enquiry system, use:")
    print(f"  python scripts/test_enquiry_system.py")
    print("\nOr run from the project root:")
    print(f"  cd {Path(__file__).parent.parent.parent}")
    print(f"  python scripts/test_enquiry_system.py")
    print("\n" + "=" * 70)
    sys.exit(1)

