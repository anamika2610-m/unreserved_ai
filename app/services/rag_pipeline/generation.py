"""
Generation module for creating AI responses to buyer enquiries.
"""
import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from app.services.rag_pipeline.llms import (
    get_model_config,
    get_model_name,
    create_chat_completion,
)
from app.services.rag_pipeline.prompts import (
    SYSTEM_PROMPT,
    GENERIC_SYSTEM_PROMPT,
    create_user_prompt,
    create_bid_advice_prompt,
)
from app.schemas import AIResponse, EnquiryLog
from app.services.rag_pipeline.augmentation import QueryAugmenter
from app.services.rag_pipeline.preprocess import detect_enquiry_type, detect_query_source
from app.services.rag_pipeline.postprocess import sanitize_response
from app.services.rag_pipeline.google_maps_links import (
    generate_context_aware_links,
    is_amenity_query,
    is_invalid_amenity_query,
)

# Constants
CONVERSATIONAL_PHRASES = [
    'recording', 'testing', 'test', 'checking', 'see how', 'let\'s see', 
    'just testing', 'trying out', 'how does this work', 'how does it work',
    'chatbot usage', 'for my chatbot'
]

NEGOTIATION_KEYWORDS = [
    'negotiate', 'negotiation', 'negotiable', 'lower the price', 'reduce the price',
    'discount', 'offer less', 'make an offer', 'counter offer', 'counteroffer',
    'bargain', 'price reduction', 'can i offer', 'would they accept',
    'talk down', 'bring down the price', 'flexible on price', 'wiggle room'
]

STRONG_GENERIC_KEYWORDS = [
    'sale of land act', 'estate agents act', 'section 32 statement', 'vendor statement',
    'cooling off', 'underquoting', 'trust account', 'licensing', 'aml',
    'anti-money laundering', 'how do i become', 'license do i need',
    'statement of information', 'what license', 'which license',
    'estate agents act', 'property law act', 'conveyancing act'
]

INVALID_AMENITY_TERMS = [
    'song', 'songs', 'music', 'movie', 'pets', 'animals', 'people', 'friends', 'job', 'work'
]

GENERIC_SIMILARITY_THRESHOLD = 0.3
PROMPT_VERSION = "1.0"


class ResponseGenerator:
    """
    Generates AI responses to buyer enquiries with proper guardrails and logging.
    """
    
    def __init__(self, augmenter: Optional[QueryAugmenter] = None):
        self.augmenter = augmenter or QueryAugmenter()
        self.model_config = get_model_config()
        self.model_name = get_model_name()
    
    # ------------------------------------------------------------------
    # 🔒 LLM ERROR CLASSIFIER (CRITICAL)
    # ------------------------------------------------------------------
    def _classify_llm_error(self, error: Exception) -> str:
        msg = str(error).lower()
        error_type_name = type(error).__name__.lower()
        
        # Rate limit errors
        if "429" in msg or "rate_limit" in msg or "rate limit" in msg:
            return "rate_limit"
        
        # Context length errors
        if "context_length" in msg or "maximum context" in msg or "context window" in msg:
            return "context_length"
        
        # Timeout errors
        if "timeout" in msg or "timed out" in msg:
            return "timeout"
        
        # Authentication/API key errors
        if "authentication" in msg or "api key" in msg or "unauthorized" in msg or "401" in msg:
            return "auth"
        
        # Model access/permission errors
        # Check for PermissionDeniedError or 403 errors related to models
        if "permissiondenied" in error_type_name or "403" in msg:
            if "model" in msg or "does not have access" in msg:
                return "model"
            return "auth"  # Other 403 errors are auth-related
        
        # Model not found or access denied
        if ("model" in msg and ("not found" in msg or "does not have access" in msg or "not available" in msg)):
            return "model"
        
        return "unknown"

    # ------------------------------------------------------------------
    # MAIN GENERATION METHOD
    # ------------------------------------------------------------------
    def generate_response(
        self,
        query: str,
        listing_id: Optional[str] = None,
        user_id: Optional[str] = None,
        n_retrieval_results: int = 8,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:

        # 1.5️⃣ Rewrite "yes" responses to explicit questions about suggested topics
        from app.services.rag_pipeline.preprocess import extract_suggested_topic_from_history
        rewritten_query = extract_suggested_topic_from_history(query, conversation_history)
        if rewritten_query:
            print(f"🔄 Query rewritten: '{query}' → '{rewritten_query}'")
            query = rewritten_query  # Use rewritten query for retrieval
        
        # Initialize variables
        context = ""
        data_sources = []
        location_context = None
        query_source = 'property'
        
        # 0️⃣ Check for conversational/test queries FIRST (before any retrieval)
        query_lower = query.lower()
        is_conversational = any(phrase in query_lower for phrase in CONVERSATIONAL_PHRASES)
        
        if is_conversational:
            # Conversational query - return friendly message immediately, no retrieval or LLM call needed
            print("✅ Conversational query detected → returning friendly welcome message (skipping retrieval)")
            answer = (
                "I'm here and ready to help! I can answer questions about property listings, "
                "real estate processes, legal requirements, and general real estate knowledge in Victoria. "
                "What would you like to know?"
            )
            
            ai_response = sanitize_response(
                AIResponse(
                    answer=answer,
                    needs_vendor_contact=False,
                    escalation_reason="Conversational/test query",
                    data_sources=[],
                )
            )
            
            log_entry = EnquiryLog(
                question=query,
                answer=answer,
            listing_id=listing_id,
                user_id=user_id,
                data_sources=[],
                needs_vendor_contact=False,
                escalation_reason="Conversational/test query",
                model_version=self.model_name,
                prompt_version=PROMPT_VERSION,
                timestamp=datetime.now(),
            )
            
            return {
                "ai_response": ai_response,
                "log_entry": log_entry,
                "nearby_properties": [],
                "amenity_links": [],
            }
        
        # 1️⃣ Check for negotiation/pricing advice queries FIRST (must escalate to vendor)
        query_lower = query.lower()
        is_negotiation_query = any(keyword in query_lower for keyword in NEGOTIATION_KEYWORDS)
        
        if is_negotiation_query:
            print("🚨 Negotiation query detected → escalating to vendor/agent")
            answer = (
                "I cannot provide advice on pricing or negotiation strategies. "
                "For discussions about price negotiation or making an offer, "
                "please contact the listing agent or vendor directly. They will be "
                "happy to discuss your interest in the property."
            )
            
            ai_response = sanitize_response(
                AIResponse(
                    answer=answer,
                    needs_vendor_contact=True,
                    escalation_reason="Negotiation/pricing advice query",
                    data_sources=[],
                )
            )
            
            log_entry = EnquiryLog(
                question=query,
                answer=answer,
                listing_id=listing_id,
                user_id=user_id,
                data_sources=[],
                needs_vendor_contact=True,
                escalation_reason="Negotiation/pricing advice query",
                model_version=self.model_name,
                prompt_version=PROMPT_VERSION,
                timestamp=datetime.now(),
            )
            
            return {
                "ai_response": ai_response,
                "log_entry": log_entry,
                "nearby_properties": [],
                "amenity_links": [],
            }
        
        # 2️⃣ Detect query source (property vs generic)
        # Check if it's a clear generic legal/process question
        query_source_detected = detect_query_source(query, conversation_history=conversation_history)
        
        # Strong generic indicators (legal/process questions that should skip property data entirely)
        is_strong_generic = any(kw in query.lower() for kw in STRONG_GENERIC_KEYWORDS)
        
        print(f"🔍 Query detection: query_source_detected={query_source_detected}, is_strong_generic={is_strong_generic}, listing_id={listing_id}")
        
        # 3️⃣ CASCADING FALLBACK LOGIC
        # Priority 1: If it's a STRONG generic query (legal/process), skip property data entirely
        if is_strong_generic:
            print(f"🔍 Step 1: Generic query detected → trying generic knowledge store first")
            generic_context, generic_data_sources, _ = self.augmenter.augment_query(
                query=query,
                listing_id=None,
                n_results=n_retrieval_results,
                query_source='generic'
            )
            
            if generic_data_sources and generic_context and generic_context.strip():
                print(f"✅ Generic knowledge found → using generic data")
                print(f"   Context length: {len(generic_context)} chars")
                print(f"   Data sources: {len(generic_data_sources)}")
                top_sim = generic_data_sources[0].similarity_score if generic_data_sources[0].similarity_score is not None else 0.0
                print(f"   First source similarity: {top_sim:.4f}")
                context = generic_context
                data_sources = generic_data_sources
                location_context = None
                query_source = 'generic'
            else:
                # Generic query but no results - provide fallback
                print("⚠️  Generic query returned no results → providing fallback message")
                print(f"   Debug: generic_data_sources={len(generic_data_sources) if generic_data_sources else 0}, context_length={len(generic_context) if generic_context else 0}")
                
                answer = (
                    "I don't have detailed information on that topic in my knowledge base. "
                    "For specific questions about real estate law, licensing, or processes in Victoria, "
                    "I recommend consulting with a qualified professional such as a lawyer, "
                    "licensed real estate agent, or Consumer Affairs Victoria (CAV)."
                )
                
                return self._create_response_dict(
                    answer=answer,
                    needs_vendor_contact=False,
                    escalation_reason="No relevant information found in generic knowledge base",
                    data_sources=[],
                    query=query,
                    listing_id=listing_id,
                    user_id=user_id,
                )
        else:
            # 🔄 CASCADING FALLBACK: Property JSON → Property PDFs → Generic PDFs → Escalation
            property_json_context = ""
            property_json_data_sources = []
            property_pdf_context = ""
            property_pdf_data_sources = []
            property_location_context = None
            property_sufficient = False
            insufficiency_reason = ""
            
            # Step 1/4: Try property JSON chunks (excludes property_document)
            if listing_id:
                print(f"🔍 Step 1/4: Trying property JSON chunks (listing_id: {listing_id})")
                print(f"           → This includes: overview, pricing, specifications, location chunks (excludes property_document)")
                property_json_context, property_json_data_sources, property_location_context = self.augmenter.augment_query_json_chunks(
                    query=query,
                    listing_id=listing_id,
                    n_results=n_retrieval_results
                )
                
                # Check if property JSON data is sufficient
                if property_json_data_sources:
                    property_sufficient, insufficiency_reason = self.augmenter.check_data_sufficiency(
                        query=query,
                        retrieved_context=property_json_context,
                        data_sources=property_json_data_sources
                    )
                    print(f"           → Found {len(property_json_data_sources)} JSON chunks")
                    top_similarity = property_json_data_sources[0].similarity_score if property_json_data_sources[0].similarity_score is not None else 0.0
                    print(f"           → Top similarity: {top_similarity:.4f}")
                    print(f"           → Sufficient: {property_sufficient}")
                else:
                    print(f"           → No property JSON chunks found")
                    insufficiency_reason = "No property JSON chunks found"
                
                if property_sufficient and property_json_data_sources:
                    print(f"✅ Step 1/4: Property JSON chunks sufficient → using JSON data")
                    context = property_json_context
                    data_sources = property_json_data_sources
                    location_context = property_location_context
                    query_source = 'property'
                else:
                    print(f"⚠️  Step 1/4: Property JSON chunks insufficient")
                    print(f"           → Reason: {insufficiency_reason}")
                    
                    # Step 2/4: Try property-specific PDFs (property_document chunks)
                    print(f"🔍 Step 2/4: Trying property-specific PDFs (property_document chunks)")
                    property_pdf_context, property_pdf_data_sources, property_location_context = self.augmenter.augment_query_pdf_chunks(
                        query=query,
                        listing_id=listing_id,
                        n_results=n_retrieval_results
                    )
                    
                    # Check if property PDF data is sufficient
                    if property_pdf_data_sources:
                        property_sufficient, insufficiency_reason = self.augmenter.check_data_sufficiency(
                            query=query,
                            retrieved_context=property_pdf_context,
                            data_sources=property_pdf_data_sources
                        )
                        print(f"           → Found {len(property_pdf_data_sources)} PDF chunks")
                        top_similarity = property_pdf_data_sources[0].similarity_score if property_pdf_data_sources[0].similarity_score is not None else 0.0
                        print(f"           → Top similarity: {top_similarity:.4f}")
                        print(f"           → Sufficient: {property_sufficient}")
                    else:
                        print(f"           → No property PDF chunks found")
                        insufficiency_reason = "No property PDF chunks found"
                    
                    if property_sufficient and property_pdf_data_sources:
                        print(f"✅ Step 2/4: Property PDF chunks sufficient → using PDF data")
                        context = property_pdf_context
                        data_sources = property_pdf_data_sources
                        location_context = property_location_context
                        query_source = 'property'
                    else:
                        print(f"⚠️  Step 2/4: Property PDF chunks insufficient")
                        print(f"           → Reason: {insufficiency_reason}")
            else:
                print(f"🔍 No listing_id provided → skipping property data (Steps 1-2/4)")
            
            # Step 3/4: Try generic knowledge as fallback (if property data insufficient)
            generic_context = ""
            generic_data_sources = []
            
            if not property_sufficient or (not property_json_data_sources and not property_pdf_data_sources):
                print(f"🔍 Step 3/4: Trying generic knowledge (generic PDFs from generic_knowledge)")
                generic_context, generic_data_sources, _ = self.augmenter.augment_query(
                    query=query,
                    listing_id=None,
                    n_results=n_retrieval_results,
                    query_source='generic'
                )
                
                if generic_data_sources and generic_context and generic_context.strip():
                    # Check if generic data has good similarity
                    top_similarity = generic_data_sources[0].similarity_score if generic_data_sources and generic_data_sources[0].similarity_score is not None else 0.0
                    print(f"           → Found {len(generic_data_sources)} generic chunks")
                    print(f"           → Top similarity: {top_similarity:.4f}")
                    
                    if top_similarity > GENERIC_SIMILARITY_THRESHOLD:
                        print(f"✅ Step 3/4: Generic knowledge found and relevant → using generic data")
                        context = generic_context
                        data_sources = generic_data_sources
                        location_context = None
                        query_source = 'generic'
                    else:
                        print(f"⚠️  Step 3/4: Generic knowledge found but low relevance (similarity: {top_similarity:.4f})")
                        # Continue to Step 4
                        property_sufficient = False
                else:
                    print(f"⚠️  Step 3/4: No generic knowledge found")
            
            # Step 4/4: If all previous steps failed, escalate to vendor
            if not property_sufficient or (not property_json_data_sources and not property_pdf_data_sources):
                if not (generic_data_sources and generic_context and generic_context.strip()):
                    print("⚠️  Step 4/4: All data sources insufficient → escalating to vendor")
                    fallback_reason = insufficiency_reason if insufficiency_reason else "Insufficient information in property JSON, property PDFs, and no relevant generic knowledge found"
                    answer = self._generate_vendor_contact_message(query, fallback_reason)
                    
                    # Combine all attempted data sources for logging
                    all_data_sources = property_json_data_sources + property_pdf_data_sources
                    
                    return self._create_response_dict(
                        answer=answer,
                        needs_vendor_contact=True,
                        escalation_reason=fallback_reason,
                        data_sources=all_data_sources,
                        query=query,
                        listing_id=listing_id,
                        user_id=user_id,
                    )
            
            # If we reach here, we have sufficient data (from one of the steps)
            if property_sufficient:
                if property_json_data_sources:
                    context = property_json_context
                    data_sources = property_json_data_sources
                elif property_pdf_data_sources:
                    context = property_pdf_context
                    data_sources = property_pdf_data_sources
                location_context = property_location_context
                query_source = 'property'
        
        # 4️⃣ Final check - if we still don't have context, provide fallback
        if not context or not data_sources:
            # Final fallback - no data from either source
            print("⚠️  No data found in property or generic stores → providing fallback message")
            answer = (
                "I don't have detailed information on that topic. "
                "For property-specific questions, please contact the vendor or listing agent. "
                "For questions about real estate law, licensing, or processes in Victoria, "
                "I recommend consulting with a qualified professional such as a lawyer, "
                "licensed real estate agent, or Consumer Affairs Victoria (CAV)."
            )
            
            ai_response = sanitize_response(
                AIResponse(
                    answer=answer,
                    needs_vendor_contact=False,
                    escalation_reason="No relevant information found in property or generic knowledge bases",
                    data_sources=[],
                )
            )
            
            log_entry = EnquiryLog(
                question=query,
                answer=answer,
                listing_id=listing_id,
                user_id=user_id,
                data_sources=[],
                needs_vendor_contact=False,
                escalation_reason="No relevant information found in property or generic knowledge bases",
                model_version=self.model_name,
                prompt_version=PROMPT_VERSION,
                timestamp=datetime.now(),
            )
            
            return {
                "ai_response": ai_response,
                "log_entry": log_entry,
                "nearby_properties": [],
                "amenity_links": [],
            }
        
        # Data sufficiency check is already done above, so we can proceed
        is_sufficient = True

        # 3️⃣ Enquiry type routing
        enquiry_type = detect_enquiry_type(query)
        
        if enquiry_type == "personal_advice":
            answer = self._generate_personal_advice_message(query)
            return self._create_response_dict(
                answer=answer,
                needs_vendor_contact=True,
                escalation_reason="Personal advice requires human expertise",
                data_sources=[],
                query=query,
                listing_id=listing_id,
                user_id=user_id,
            )

        # 4️⃣ Check if this is an invalid/irrelevant amenity query (check BEFORE valid amenity check)
        if is_invalid_amenity_query(query):
            print(f"⚠️  Invalid/irrelevant amenity query detected: '{query}'")
            # Extract the invalid term to make the response more helpful
            query_lower = query.lower()
            found_invalid = [term for term in INVALID_AMENITY_TERMS if term in query_lower]
            
            if found_invalid:
                invalid_term = found_invalid[0]
                answer = (
                    f"I'm not sure what you mean by 'nearby {invalid_term}'. "
                    f"Could you clarify what you're looking for? For example, are you asking about nearby "
                    f"**schools**, **hospitals**, **shops**, **restaurants**, **parks**, or other amenities? "
                    f"I can help you find nearby places if you specify what you're looking for."
                )
            else:
                answer = (
                    f"I'm not sure what you're looking for. "
                    f"Could you clarify? For example, are you asking about nearby "
                    f"**schools**, **hospitals**, **shops**, **restaurants**, or something else? "
                    f"I can help you find nearby amenities if you specify what you're looking for."
                )
            
            return self._create_response_dict(
                answer=answer,
                needs_vendor_contact=False,
                escalation_reason="Invalid/irrelevant query",
                data_sources=[],
                query=query,
                listing_id=listing_id,
                user_id=user_id,
            )
        
        # 5️⃣ Check if this is an amenity query (to pass has_amenity_links flag)
        # We need to check this BEFORE creating the prompt so the LLM knows to mention the link
        has_amenity_links_flag = False
        if is_amenity_query(query):
            # Try to get location from location_context first
            latitude = None
            longitude = None
            
            if location_context:
                latitude = location_context.get('latitude')
                longitude = location_context.get('longitude')
            
            # Fallback: If location_context is None but we have listing_id, fetch location from database
            if (latitude is None or longitude is None) and listing_id:
                print(f"🗺️  Location not in context, fetching from database for listing_id: {listing_id}")
                try:
                    from app.db.postgres.repositories.listing_repository import ListingRepository
                    from app.db.session import SessionLocal
                    
                    db_session = SessionLocal()
                    try:
                        listing_repo = ListingRepository(db_session)
                        location_data = listing_repo.get_listing_location(listing_id)
                        
                        if location_data:
                            latitude = location_data.get('latitude')
                            longitude = location_data.get('longitude')
                            print(f"   → Fetched location from DB: lat={latitude}, lng={longitude}")
                            
                            # Update location_context if it exists, or create it
                            if location_context is None:
                                location_context = {}
                            location_context['latitude'] = latitude
                            location_context['longitude'] = longitude
                    finally:
                        db_session.close()
                except Exception as e:
                    print(f"⚠️  Failed to fetch location from database: {type(e).__name__}: {e}")
            
            if latitude and longitude:
                has_amenity_links_flag = True
                print(f"🗺️  Amenity query detected - will generate links and include reference in response")
        
        # 6️⃣ Prompt creation
        # Use different system prompts and user prompts for generic vs property queries
        if query_source == 'generic':
            from app.services.rag_pipeline.prompts import create_generic_user_prompt
            system_prompt = GENERIC_SYSTEM_PROMPT
            user_prompt = create_generic_user_prompt(query, context, conversation_history=conversation_history)
        else:
            system_prompt = SYSTEM_PROMPT
            if enquiry_type == "bidding":
                user_prompt = create_bid_advice_prompt(query, context, conversation_history=conversation_history)
            else:
                user_prompt = create_user_prompt(query, context, has_amenity_links=has_amenity_links_flag, conversation_history=conversation_history)

        messages = [{"role": "system", "content": system_prompt}]
        messages.append({"role": "user", "content": user_prompt})

        # 7️⃣ LLM CALL (SAFE)
        needs_vendor_contact = False
        escalation_reason = None
        rate_limit_error = False
        
        try:
            response = create_chat_completion(
                messages=messages,
                model=self.model_config["model"],
                temperature=self.model_config["temperature"],
                max_tokens=self.model_config["max_tokens"],
            )
            answer = response.choices[0].message.content.strip()
        
        except Exception as e:
            import traceback

            print("❌ LLM ERROR")
            print(f"Error type: {type(e).__name__}")
            print(f"Error message: {str(e)}")
            print(traceback.format_exc())

            error_type = self._classify_llm_error(e)

            if error_type == "rate_limit":
                rate_limit_error = True
                
                # Try to extract retry_after time from error
                retry_after_seconds = None
                retry_time_str = None
                
                # Check if error has response attribute (OpenAI/Groq SDK)
                if hasattr(e, 'response') and hasattr(e.response, 'headers'):
                    retry_after = e.response.headers.get('retry-after')
                    if retry_after:
                        try:
                            retry_after_seconds = int(retry_after)
                        except (ValueError, TypeError):
                            pass
                
                # Also check if error has retry_after attribute directly
                if retry_after_seconds is None and hasattr(e, 'retry_after'):
                    try:
                        retry_after_seconds = int(e.retry_after)
                    except (ValueError, TypeError):
                        pass
                
                # Check error message for retry-after information
                if retry_after_seconds is None:
                    error_msg = str(e).lower()
                    # Look for patterns like "retry after 45" or "retry-after: 60"
                    retry_match = re.search(r'retry[-\s]after[:\s]+(\d+)', error_msg)
                    if retry_match:
                        try:
                            retry_after_seconds = int(retry_match.group(1))
                        except (ValueError, TypeError):
                            pass
                
                # Calculate retry time
                if retry_after_seconds:
                    retry_time = datetime.utcnow() + timedelta(seconds=retry_after_seconds)
                    # Format as "at HH:MM:SS UTC" or "in X seconds/minutes"
                    if retry_after_seconds < 60:
                        retry_time_str = f"in {retry_after_seconds} second{'s' if retry_after_seconds != 1 else ''}"
                    elif retry_after_seconds < 3600:
                        minutes = retry_after_seconds // 60
                        retry_time_str = f"in {minutes} minute{'s' if minutes != 1 else ''}"
                    else:
                        hours = retry_after_seconds // 3600
                        retry_time_str = f"in {hours} hour{'s' if hours != 1 else ''}"
                    
                    # Also include exact time in a clearer format
                    retry_time_formatted = retry_time.strftime("%H:%M:%S UTC")
                    # Format as "HH:MM UTC" for cleaner display
                    retry_time_short = retry_time.strftime("%H:%M UTC")
                    answer = (
                        f"I'm currently experiencing high demand. "
                        f"Please try again {retry_time_str} (retry available at {retry_time_short})."
                    )
                else:
                    # Fallback if we can't extract retry time
                    answer = (
                        "I'm currently experiencing high demand. "
                        "Please try again in a few minutes."
                    )
                
                escalation_reason = f"Rate limit exceeded. Retry {retry_time_str if retry_time_str else 'in a few minutes'}"

            elif error_type == "context_length":
                answer = (
                    "Your request is too detailed to process at once. "
                    "Please try a shorter or more specific question."
                )
                escalation_reason = "Context length exceeded"

            elif error_type == "auth":
                answer = (
                    "The service is temporarily unavailable due to an authentication issue. "
                    "Please contact support if this persists."
                )
                escalation_reason = "LLM authentication error"
            
            elif error_type == "model":
                # Extract model name from error if possible
                error_msg = str(e)
                model_name_match = re.search(r"model [`'\"]([^`'\"]+)[`'\"]", error_msg, re.IGNORECASE)
                model_name = model_name_match.group(1) if model_name_match else self.model_config.get("model", "the requested model")
                
                answer = (
                    f"The service is temporarily unavailable. "
                    f"The AI model ({model_name}) is not accessible with the current configuration. "
                    f"Please contact support."
                )
                escalation_reason = f"LLM model access error: {model_name} not available"

            elif error_type == "timeout":
                answer = (
                    "The request took too long to process. "
                    "Please try again in a moment."
                )
                escalation_reason = "LLM timeout"

            else:
                answer = (
                    "I’m unable to process your request at the moment. "
                    "Please try again shortly."
            )
                escalation_reason = "Unknown LLM error"
            
            # 🚫 Infra errors should NEVER escalate to vendor
            needs_vendor_contact = False
        
        # 8️⃣ Final response objects
        response_dict = self._create_response_dict(
            answer=answer,
            needs_vendor_contact=needs_vendor_contact,
            escalation_reason=escalation_reason,
            data_sources=data_sources,
            query=query,
            listing_id=listing_id,
            user_id=user_id,
        )
        
        ai_response = response_dict["ai_response"]
        log_entry = response_dict["log_entry"]

        # 9️⃣ Generate amenity links if it's an amenity query
        # IMPORTANT: Always generate links for amenity queries when listing_id is present,
        # regardless of where the answer came from (property PDFs, generic knowledge, etc.)
        amenity_links = []
        is_amenity = is_amenity_query(query)
        print(f"🔍 Query: '{query}'")
        print(f"🔍 Is amenity query? {is_amenity}")
        if is_amenity and listing_id:
            # Get latitude/longitude from location_context first
            latitude = None
            longitude = None
            
            if location_context:
                latitude = location_context.get('latitude')
                longitude = location_context.get('longitude')
            
            # Fallback: If location_context is None or missing lat/lng, fetch from database
            if (latitude is None or longitude is None) and listing_id:
                print(f"🗺️  Location not in context, fetching from database for listing_id: {listing_id}")
                try:
                    from app.db.postgres.repositories.listing_repository import ListingRepository
                    from app.db.session import SessionLocal
                    
                    db_session = SessionLocal()
                    try:
                        listing_repo = ListingRepository(db_session)
                        location_data = listing_repo.get_listing_location(listing_id)
                        
                        if location_data:
                            latitude = location_data.get('latitude')
                            longitude = location_data.get('longitude')
                            print(f"   → Fetched location from DB: lat={latitude}, lng={longitude}")
                            
                            # Update location_context for future use
                            if location_context is None:
                                location_context = {}
                            location_context['latitude'] = latitude
                            location_context['longitude'] = longitude
                    finally:
                        db_session.close()
                except Exception as e:
                    print(f"⚠️  Failed to fetch location from database: {type(e).__name__}: {e}")
            
            if latitude and longitude:
                print(f"🗺️  Generating amenity links (lat: {latitude}, lng: {longitude})")
                amenity_links = generate_context_aware_links(
                    query=query,
                    latitude=latitude,
                    longitude=longitude,
                    include_common=True
                )
                print(f"   → Generated {len(amenity_links.get('relevant_links', []))} relevant links")
                print(f"   → Generated {len(amenity_links.get('suggested_links', []))} suggested links")
            else:
                print(f"⚠️  Cannot generate amenity links: missing latitude/longitude (listing_id: {listing_id})")
        elif is_amenity_query(query) and not listing_id:
            print(f"⚠️  Amenity query detected but no listing_id provided - cannot generate links")
        else:
            if not is_amenity:
                print(f"✅ Not an amenity query - skipping amenity link generation")
            elif not listing_id:
                print(f"⚠️  No listing_id provided - skipping amenity link generation")

        # 🔟 Extract nearby properties from location_context
        # ONLY include nearby properties if the user explicitly asked about them
        nearby_properties_json = []
        if location_context:
            # Check if query is asking about nearby properties
            from app.services.rag_pipeline.location_utils import detect_location_query
            is_location_query, query_type = detect_location_query(query)
            
            if is_location_query and query_type == 'nearby_properties':
                nearby_properties_json = location_context.get('nearby_properties_json', [])
                if nearby_properties_json:
                    print(f"🏘️  User asked about nearby properties - including {len(nearby_properties_json)} properties in response")
            else:
                print(f"✅ User did not ask about nearby properties - excluding from response (query_type: {query_type})")
        
        # Combine relevant and suggested links (suggested only if no relevant)
        final_amenity_links = []
        if amenity_links:
            relevant = amenity_links.get('relevant_links', [])
            suggested = amenity_links.get('suggested_links', [])
            # Use relevant links if available, otherwise use suggested links
            final_amenity_links = relevant if relevant else suggested
        
        return {
            "ai_response": ai_response,
            "log_entry": log_entry,
            "nearby_properties": nearby_properties_json,
            "amenity_links": final_amenity_links,
        }
    
    # ------------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------------
    def _create_response_dict(
        self,
        answer: str,
        needs_vendor_contact: bool,
        escalation_reason: Optional[str],
        data_sources: List,
        query: str,
        listing_id: Optional[str],
        user_id: Optional[str],
        nearby_properties: Optional[List] = None,
        amenity_links: Optional[List] = None,
    ) -> Dict[str, Any]:
        """
        Create a standardized response dictionary with ai_response and log_entry.
        
        Args:
            answer: The answer text
            needs_vendor_contact: Whether vendor contact is needed
            escalation_reason: Reason for escalation (if any)
            data_sources: List of data sources
            query: Original query
            listing_id: Listing ID (if any)
            user_id: User ID (if any)
            nearby_properties: Nearby properties list (default: empty)
            amenity_links: Amenity links list (default: empty)
            
        Returns:
            Dictionary with ai_response, log_entry, nearby_properties, and amenity_links
        """
        ai_response = sanitize_response(
            AIResponse(
                answer=answer,
                needs_vendor_contact=needs_vendor_contact,
                escalation_reason=escalation_reason,
                data_sources=data_sources,
            )
        )
        
        log_entry = EnquiryLog(
            question=query,
            answer=answer,
            listing_id=listing_id,
            user_id=user_id,
            data_sources=data_sources,
            needs_vendor_contact=needs_vendor_contact,
            escalation_reason=escalation_reason,
            model_version=self.model_name,
            prompt_version=PROMPT_VERSION,
            timestamp=datetime.now(),
        )
        
        return {
            "ai_response": ai_response,
            "log_entry": log_entry,
            "nearby_properties": nearby_properties or [],
            "amenity_links": amenity_links or [],
        }

    def _generate_personal_advice_message(self, query: str) -> str:
        return (
            "I'm not able to provide personalized advice on pricing, negotiation, "
            "or investment decisions. These require assessment by qualified professionals.\n\n"
            "I can help with factual details about the property instead."
        )

    def _generate_vendor_contact_message(
        self, query: str, reason: Optional[str] = None
    ) -> str:
        message = (
            "I don't have sufficient information in the available listing data "
            "to answer this fully."
        )
        if reason:
            message += f" ({reason})"
        message += (
            "\n\nPlease contact the vendor or listing agent for accurate details."
        )
        return message
