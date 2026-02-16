"""
Generation module for creating AI responses to buyer enquiries.
"""
import re
import time
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
    ENQUIRY_EMAIL_SYSTEM_PROMPT,
    CONVERSATIONAL_SYSTEM_PROMPT,
    INTENT_CLASSIFIER_SYSTEM,
    create_user_prompt,
    create_bid_advice_prompt,
    create_enquiry_email_user_prompt,
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
from app.services.tone_adaptation_service import ToneAdaptationService, ToneLevel

# Constants
CONVERSATIONAL_PHRASES = [
    'recording', 'testing', 'test', 'checking', 'see how', 'let\'s see',
    'just testing', 'trying out', 'how does this work', 'how does it work',
    'chatbot usage', 'for my chatbot',
]
# Short acknowledgments / positive reactions – respond conversationally, no retrieval
ACKNOWLEDGMENT_PHRASES = [
    'nice', 'good', 'great', 'thanks', 'thank you', 'sounds good', 'cool',
    'lovely', 'good to know', 'good features', 'that is good', "that's good",
    'that is good features', 'perfect', 'awesome', 'appreciate it', 'noted',
    'got it', 'understood', 'that helps', 'helpful', 'cheers', 'sweet',
]

NEGOTIATION_KEYWORDS = [
    'negotiate', 'negotiation', 'negotiable', 'lower the price', 'reduce the price',
    'discount', 'offer less', 'make an offer', 'counter offer', 'counteroffer',
    'bargain', 'price reduction', 'can i offer', 'would they accept',
    'talk down', 'bring down the price', 'flexible on price', 'wiggle room'
]

STRONG_GENERIC_KEYWORDS = [
    'sale of land act', 'estate agents act', 'section 32 statement', 'vendor statement',
    'vendor disclosure', 'section 32', 'cooling off', 'underquoting', 'trust account', 
    'licensing', 'aml', 'anti-money laundering', 'aml requirements', 'aml requirement', 'aml laws',
    'how do i become', 'license do i need',
    'statement of information', 'what license', 'which license',
    'estate agents act', 'property law act', 'conveyancing act',
    'buying process', 'purchase process', 'sale process', 'settlement process',
    'auction process', 'how auctions work', 'deposit handling', 'buyer deposit',
    'auction', 'auctions', 'how auction', 'how auctions', 'auction function', 'auctions function'
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
        self.tone_service = ToneAdaptationService()
    
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
        is_enquiry_message: bool = False,
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
        t_start = time.perf_counter()
        t_llm_start = None  # set right before main LLM call for eval latency breakdown
        timings_breakdown: Dict[str, float] = {}

        # 0️⃣ Check for conversational / acknowledgment queries FIRST (before any retrieval)
        query_lower = query.lower()
        query_stripped = query_lower.strip().rstrip('?!.,').strip()
        is_conversational = any(phrase in query_lower for phrase in CONVERSATIONAL_PHRASES)
        is_acknowledgment = (
            len(query_stripped) <= 50
            and any(phrase in query_lower for phrase in ACKNOWLEDGMENT_PHRASES)
        )

        def _do_conversational_reply() -> Dict[str, Any]:
            try:
                answer = self._generate_conversational_reply(query, conversation_history)
            except Exception as e:
                print(f"⚠️ Conversational LLM fallback error: {e}")
                answer = (
                    "Glad that helped! Is there anything else you'd like to know about this property?"
                )
            if not answer:
                answer = (
                    "Glad that helped! Is there anything else you'd like to know about this property?"
                )
            ai_response = sanitize_response(
                AIResponse(
                    answer=answer,
                    needs_vendor_contact=False,
                    escalation_reason="Conversational reply (LLM)",
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
                escalation_reason="Conversational reply (LLM)",
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

        if is_conversational or is_acknowledgment:
            print("✅ Conversational/acknowledgment detected → LLM replying naturally (skipping retrieval)")
            return _do_conversational_reply()

        # For short or ambiguous messages, let the LLM decide if this needs listing data or is conversational
        word_count = len(query_stripped.split())
        char_count = len(query_stripped)
        is_short_or_ambiguous = word_count <= 12 or char_count <= 80
        if is_short_or_ambiguous:
            intent = self._classify_intent_listing_vs_conversational(query, conversation_history)
            if intent == "conversational":
                print("✅ Intent classifier → conversational (skipping retrieval)")
                return _do_conversational_reply()

        # 0.5️⃣ Check for greetings FIRST (before any routing)
        _t = time.perf_counter()
        enquiry_type = detect_enquiry_type(query)
        timings_breakdown["detect_enquiry_type_ms"] = (time.perf_counter() - _t) * 1000.0
        if enquiry_type == "greeting":
            print("👋 Greeting detected → returning friendly welcome message")
            answer = (
                "Hello! 👋 I'm here to help you learn more about this property. "
                "You can ask me about:\n\n"
                "• **Pricing** and sale methods\n"
                "• **Property features** (bedrooms, bathrooms, land area, etc.)\n"
                "• **Location** and nearby amenities\n"
                "• **Nearby properties** for sale\n"
                "• **Property documents** (aerial views, bushfire/flood information, etc.)\n\n"
                "What would you like to know?"
            )
            return self._create_response_dict(
                answer=answer,
                needs_vendor_contact=False,
                escalation_reason=None,
                data_sources=[],
                query=query,
                listing_id=listing_id,
                user_id=user_id,
            )
        
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
        _t = time.perf_counter()
        query_source_detected = detect_query_source(
            query,
            conversation_history=conversation_history,
            listing_id=listing_id,
        )
        timings_breakdown["detect_query_source_ms"] = (time.perf_counter() - _t) * 1000.0
        
        # Strong generic indicators (legal/process questions that should skip property data entirely)
        is_strong_generic = any(kw in query.lower() for kw in STRONG_GENERIC_KEYWORDS)
        
        print(f"🔍 Query detection: query_source_detected={query_source_detected}, is_strong_generic={is_strong_generic}, listing_id={listing_id}")
        
        # 3️⃣ CASCADING FALLBACK LOGIC
        # Priority 1: If query is detected as generic (legal/process), go to generic knowledge first
        # This includes both strong generic keywords AND queries routed to generic by detect_query_source
        if is_strong_generic or query_source_detected == 'generic':
            print(f"🔍 Step 1: Generic query detected (is_strong_generic={is_strong_generic}, query_source={query_source_detected}) → trying generic knowledge store first")
            _t = time.perf_counter()
            generic_context, generic_data_sources, _ = self.augmenter.augment_query(
                query=query,
                listing_id=None,
                n_results=n_retrieval_results,
                query_source='generic'
            )
            timings_breakdown["augment_generic_ms"] = (time.perf_counter() - _t) * 1000.0
            
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
                
                if is_enquiry_message:
                    answer = (
                        "This is an automated email. We don't have enough information to answer this enquiry "
                        "right now, but we will get back to you shortly."
                    )
                else:
                    answer = (
                        "I don't have detailed information on that topic. "
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
            display_price = True  # Initialize at function scope level
            property_sufficient = False  # Initialize to False
            
            # Step 1/4: Try property JSON chunks (excludes property_document)
            if listing_id:
                # 🚨 PRICE VISIBILITY CHECK: Fetch displayPrice from database
                display_price = True  # Default to True if we can't fetch
                _t_db = time.perf_counter()
                try:
                    from app.db.postgres.repositories.listing_repository import ListingRepository
                    from app.db.session import SessionLocal
                    
                    db_session = SessionLocal()
                    try:
                        listing_repo = ListingRepository(db_session)
                        listing_data = listing_repo._execute_query_one(
                            "SELECT display_price FROM listings WHERE id = :listing_id",
                            {"listing_id": listing_id}
                        )
                        if listing_data:
                            display_price = listing_data.get('display_price', True)
                            print(f"🔒 Price visibility check: displayPrice = {display_price} for listing {listing_id}")
                    finally:
                        db_session.close()
                except Exception as e:
                    print(f"⚠️  Failed to fetch displayPrice from database: {type(e).__name__}: {e}")
                timings_breakdown["display_price_db_ms"] = (time.perf_counter() - _t_db) * 1000.0
                    # Default to True (show price) if we can't fetch - safer default
                
                print(f"🔍 Step 1/4: Trying property JSON chunks (listing_id: {listing_id})")
                print(f"           → This includes: overview, pricing, specifications, location chunks (excludes property_document)")
                _t = time.perf_counter()
                property_json_context, property_json_data_sources, property_location_context = self.augmenter.augment_query_json_chunks(
                    query=query,
                    listing_id=listing_id,
                    n_results=n_retrieval_results
                )
                timings_breakdown["augment_json_ms"] = (time.perf_counter() - _t) * 1000.0
                
                # 🚨 RETRIEVAL LAYER ENFORCEMENT: Filter out price chunks if displayPrice = false
                if not display_price and enquiry_type == "price":
                    # Remove pricing chunks from data sources
                    original_count = len(property_json_data_sources)
                    property_json_data_sources = [
                        ds for ds in property_json_data_sources 
                        if ds.chunk_type != 'pricing'
                    ]
                    filtered_count = original_count - len(property_json_data_sources)
                    if filtered_count > 0:
                        print(f"🔒 RETRIEVAL LAYER: Filtered out {filtered_count} pricing chunk(s) (displayPrice = false)")
                        # Also remove pricing content from context
                        import re
                        # Remove pricing sections from context
                        property_json_context = re.sub(
                            r'=== PROPERTY LISTING:.*?===\s*\[PRICING\].*?(?=\[|===|$)',
                            '',
                            property_json_context,
                            flags=re.DOTALL
                        )
                
                # Check if property JSON data is sufficient
                # IMPORTANT: Also check if location_context has nearby properties (even if no JSON chunks)
                if property_json_data_sources or property_location_context:
                    # For sufficiency check, we need at least an empty list if no data sources
                    check_data_sources = property_json_data_sources if property_json_data_sources else []
                    
                    property_sufficient, insufficiency_reason = self.augmenter.check_data_sufficiency(
                        query=query,
                        retrieved_context=property_json_context,
                        data_sources=check_data_sources,
                        location_context=property_location_context
                    )
                    
                    if property_json_data_sources:
                        print(f"           → Found {len(property_json_data_sources)} JSON chunks")
                        top_similarity = property_json_data_sources[0].similarity_score if property_json_data_sources[0].similarity_score is not None else 0.0
                        print(f"           → Top similarity: {top_similarity:.4f}")
                        print(f"           → Sufficient: {property_sufficient}")
                    elif property_location_context and property_location_context.get('nearby_properties_json'):
                        # No JSON chunks but we have location context with nearby properties
                        print(f"           → No property JSON chunks found, but location_context has nearby properties")
                        print(f"           → Sufficient: {property_sufficient}")
                    else:
                        print(f"           → No property JSON chunks found")
                else:
                    print(f"           → No property JSON chunks found")
                    insufficiency_reason = "No property JSON chunks found"
                
                # 🚨 CRITICAL: Check if this is a "document query" (aerial view, bushfire, flood, etc.)
                # For document queries, if JSON is insufficient, SKIP JSON and use ONLY property PDFs
                query_lower = query.lower()
                document_query_keywords = [
                    'aerial view', 'aerial', 'bird eye', 'bird\'s eye',
                    'bushfire', 'flood', 'erosion', 'heritage overlay',
                    'planning overlay', 'environmental', 'disclosure',
                    'vendor statement', 'section 32', 'contract'
                ]
                is_document_query = any(kw in query_lower for kw in document_query_keywords)
                
                # 🚨 CRITICAL: ALWAYS keep JSON data if it exists (especially pricing)
                # JSON data from backend should NEVER be overridden by PDFs
                # EXCEPTION: For document queries where JSON is insufficient, skip JSON and use ONLY PDFs
                if property_json_data_sources:
                    # If it's a document query AND JSON is insufficient → Skip JSON, use ONLY property PDFs
                    if is_document_query and not property_sufficient:
                        print(f"⚠️  Step 1/4: JSON chunks found but INSUFFICIENT for document query")
                        print(f"           → Reason: {insufficiency_reason}")
                        print(f"🔍 Step 2/4: Skipping JSON → Trying ONLY property-specific PDFs (document query)")
                        _t = time.perf_counter()
                        property_pdf_context, property_pdf_data_sources, property_location_context = self.augmenter.augment_query_pdf_chunks(
                            query=query,
                            listing_id=listing_id,
                            n_results=n_retrieval_results
                        )
                        timings_breakdown["augment_pdf_ms"] = timings_breakdown.get("augment_pdf_ms", 0) + (time.perf_counter() - _t) * 1000.0
                        
                        # Check if property PDF data is sufficient
                        if property_pdf_data_sources:
                            property_sufficient, insufficiency_reason = self.augmenter.check_data_sufficiency(
                                query=query,
                                retrieved_context=property_pdf_context,
                                data_sources=property_pdf_data_sources,
                                location_context=property_location_context
                            )
                            print(f"           → Found {len(property_pdf_data_sources)} PDF chunks")
                            top_similarity = property_pdf_data_sources[0].similarity_score if property_pdf_data_sources[0].similarity_score is not None else 0.0
                            print(f"           → Top similarity: {top_similarity:.4f}")
                            print(f"           → Sufficient: {property_sufficient}")
                            
                            if property_sufficient:
                                print(f"✅ Step 2/4: Using ONLY property PDFs (JSON skipped for document query)")
                                context = property_pdf_context  # Use ONLY PDFs, not JSON
                                data_sources = property_pdf_data_sources
                                location_context = property_location_context
                                query_source = 'property'
                            else:
                                print(f"⚠️  Step 2/4: Property PDF chunks insufficient")
                                print(f"           → Reason: {insufficiency_reason}")
                                # Will fall through to generic or escalation
                                context = ""
                                data_sources = []
                                location_context = None
                        else:
                            print(f"           → No property PDF chunks found")
                            # Will fall through to generic or escalation
                            context = ""
                            data_sources = []
                            location_context = None
                    else:
                        # Normal case: Use JSON as primary source
                        print(f"✅ Step 1/4: Property JSON chunks found → using JSON data as PRIMARY source")
                        context = property_json_context
                        data_sources = property_json_data_sources
                        location_context = property_location_context
                        query_source = 'property'
                        
                        # If JSON data is insufficient, SUPPLEMENT (not replace) with PDF data
                        # BUT: Check if JSON context already contains the answer before supplementing
                        json_context_lower = property_json_context.lower()
                        
                        # Check if JSON context already answers the query
                        # For specific attribute queries (zoning, energy rating, etc.), if JSON has it, don't supplement
                        backend_attribute_keywords = [
                            'zoning', 'energy rating', 'frontage', 'car port', 'open parking', 
                            'ensuite', 'year built', 'highlights', 'garage', 'car ports',
                            'land area', 'floor area', 'land', 'bedroom', 'bathroom', 'garages',
                            'ensuites', 'frontage', 'year built', 'energy'
                        ]
                        query_has_backend_attribute = any(kw in query_lower for kw in backend_attribute_keywords)
                        # Check if JSON context contains the same keywords that are in the query
                        json_has_answer = False
                        if query_has_backend_attribute:
                            matching_keywords = [kw for kw in backend_attribute_keywords if kw in query_lower]
                            json_has_answer = any(kw in json_context_lower for kw in matching_keywords)
                        
                        if not property_sufficient and not (query_has_backend_attribute and json_has_answer):
                            print(f"⚠️  Step 1/4: JSON data found but may be insufficient for full answer")
                            print(f"           → Reason: {insufficiency_reason}")
                            print(f"🔍 Step 2/4: Trying property-specific PDFs to SUPPLEMENT JSON data")
                            _t = time.perf_counter()
                            property_pdf_context, property_pdf_data_sources, _ = self.augmenter.augment_query_pdf_chunks(
                                query=query,
                                listing_id=listing_id,
                                n_results=n_retrieval_results
                            )
                            timings_breakdown["augment_pdf_ms"] = timings_breakdown.get("augment_pdf_ms", 0) + (time.perf_counter() - _t) * 1000.0
                            
                            if property_pdf_data_sources:
                                print(f"           → Found {len(property_pdf_data_sources)} PDF chunks to supplement")
                                # SUPPLEMENT JSON context with PDF context (not replace)
                                context = property_json_context + "\n\n" + property_pdf_context
                                # Add PDF sources AFTER JSON sources (JSON has priority)
                                data_sources = property_json_data_sources + property_pdf_data_sources
                                print(f"✅ Step 2/4: Combined JSON + PDF data (JSON takes priority)")
                                property_sufficient = True  # Combined data should be sufficient
                            else:
                                print(f"           → No property PDF chunks found to supplement")
                        elif query_has_backend_attribute and json_has_answer:
                            print(f"✅ Step 1/4: JSON data contains answer for backend attribute query - NOT supplementing with PDFs")
                            # Use JSON data only - don't supplement with PDFs
                else:
                    # Check if we already have sufficient data from location_context (e.g., nearby properties)
                    if property_sufficient and property_location_context and property_location_context.get('nearby_properties_json'):
                        print(f"✅ Step 1/4: No JSON chunks BUT location_context has nearby properties → Data SUFFICIENT")
                        # Use location context data even without traditional chunks
                        context = ""  # No text context needed for nearby properties
                        data_sources = []  # No traditional data sources, but we have location_context
                        location_context = property_location_context
                        query_source = 'property'
                    else:
                        print(f"⚠️  Step 1/4: No Property JSON chunks found")
                        print(f"           → Reason: {insufficiency_reason}")
                        
                        # Step 2/4: Try property-specific PDFs (only if NO JSON data exists)
                        print(f"🔍 Step 2/4: No JSON data → Trying property-specific PDFs (property_document chunks)")
                        _t = time.perf_counter()
                        property_pdf_context, property_pdf_data_sources, property_location_context = self.augmenter.augment_query_pdf_chunks(
                            query=query,
                            listing_id=listing_id,
                            n_results=n_retrieval_results
                        )
                        timings_breakdown["augment_pdf_ms"] = timings_breakdown.get("augment_pdf_ms", 0) + (time.perf_counter() - _t) * 1000.0
                        
                        # Check if property PDF data is sufficient
                        if property_pdf_data_sources:
                            property_sufficient, insufficiency_reason = self.augmenter.check_data_sufficiency(
                                query=query,
                                retrieved_context=property_pdf_context,
                                data_sources=property_pdf_data_sources,
                                location_context=property_location_context
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
            
            # Skip generic knowledge if we already have sufficient data (including location_context with nearby properties)
            has_location_data = property_location_context and property_location_context.get('nearby_properties_json')
            if not property_sufficient or (not property_json_data_sources and not property_pdf_data_sources and not has_location_data):
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
            # Don't escalate if we have location_context with nearby properties
            has_location_data = property_location_context and property_location_context.get('nearby_properties_json')
            if not property_sufficient or (not property_json_data_sources and not property_pdf_data_sources and not has_location_data):
                if not (generic_data_sources and generic_context and generic_context.strip()):
                    print("⚠️  Step 4/4: All data sources insufficient → escalating to vendor")
                    fallback_reason = insufficiency_reason if insufficiency_reason else "Insufficient information in property JSON, property PDFs, and no relevant generic knowledge found"
                    answer = self._generate_vendor_contact_message(query, fallback_reason, is_enquiry_message)
                    
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
            # NOTE: This section is now mostly redundant as we handle context/data_sources
            # assignment in the steps above, but keeping for safety
            if property_sufficient and not context:
                if property_json_data_sources:
                    # JSON data always has priority
                    context = property_json_context
                    data_sources = property_json_data_sources
                    # Supplement with PDF if available
                    if property_pdf_data_sources:
                        context = context + "\n\n" + property_pdf_context
                        data_sources = data_sources + property_pdf_data_sources
                elif property_pdf_data_sources:
                    context = property_pdf_context
                    data_sources = property_pdf_data_sources
                location_context = property_location_context
                query_source = 'property'
        
        # 4️⃣ Final check - if we still don't have context, provide fallback
        # BUT: Allow location_context with nearby properties as valid data (even if context/data_sources are empty)
        has_location_data = location_context and location_context.get('nearby_properties_json')
        if (not context or not data_sources) and not has_location_data:
            # Final fallback - no data from either source
            print("⚠️  No data found in property or generic stores → providing fallback message")
            if is_enquiry_message:
                answer = (
                    "This is an automated email. We don't have enough information to answer this enquiry "
                    "right now, but we will get back to you shortly."
                )
            else:
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

        # 3️⃣ Enquiry type routing (greeting already handled earlier)
        # Re-detect enquiry_type here for personal_advice check (greeting was already handled)
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

            # For enquiry messages, treat low-confidence amenity queries as "no data" and use
            # the automated email fallback instead of asking clarifying questions.
            if is_enquiry_message:
                answer = (
                    "This is an automated email. We don't have enough information to answer this enquiry "
                    "right now, but we will get back to you shortly."
                )
                return self._create_response_dict(
                    answer=answer,
                    needs_vendor_contact=False,
                    escalation_reason="Invalid/irrelevant query for enquiry message",
                    data_sources=[],
                    query=query,
                    listing_id=listing_id,
                    user_id=user_id,
                )

            # For interactive chat, keep the clarifying behaviour
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
        
        # 5️⃣ Get listing activity metrics for tone adaptation
        # IMPORTANT: Only fetch activity metrics (and compute tone) for PROPERTY queries.
        # For GENERIC knowledge queries (laws, processes, training PDFs), we skip
        # all activity/tone work to avoid unnecessary DB calls and side effects.
        listing_activity_data = None
        tone_level = ToneLevel.NEUTRAL
        tone_context = ""
        
        if query_source == "property" and listing_id:
            try:
                from app.db.session import SessionLocal
                from app.db.postgres.repositories.listing_activity_repository import ListingActivityRepository
                
                db_session = SessionLocal()
                try:
                    activity_repo = ListingActivityRepository(db_session)
                    listing_activity_data = activity_repo.get_activity_dict(listing_id)
                    
                    if listing_activity_data:
                        print(f"🎭 Fetching tone adaptation for listing {listing_id}")
                        print(
                            f"   Activity metrics: enquiries={listing_activity_data.get('enquiries_7d', 0)}, "
                            f"offers={listing_activity_data.get('genuine_offers_7d', 0)}, "
                            f"contracts={listing_activity_data.get('contract_requests_7d', 0)}"
                        )
                        
                        tone_level, tone_context = self.tone_service.determine_tone(listing_activity_data)
                        
                        if tone_level != ToneLevel.NEUTRAL:
                            print(f"🎭 Tone adaptation: {tone_level.value.upper()}")
                            print(f"   Context: {tone_context[:150]}...")
                        else:
                            print("🎭 Tone adaptation: NEUTRAL (no special conditions met)")
                    else:
                        print(f"🎭 No activity data found for listing {listing_id} → using NEUTRAL tone")
                finally:
                    db_session.close()
            except Exception as e:
                print(f"⚠️  Failed to get listing activity metrics: {type(e).__name__}: {e}")
                import traceback
                print(traceback.format_exc())
        else:
            print(
                f"🎭 Skipping activity metrics/tone adaptation "
                f"(query_source={query_source}, listing_id={listing_id})"
            )
        
        # 5.5️⃣ Check if this is an amenity query (to pass has_amenity_links flag)
        # We need to check this BEFORE creating the prompt so the LLM knows to mention the link
        # IMPORTANT: For pure pricing questions, we do NOT want amenity links at all.
        # IMPORTANT: For generic knowledge queries, we do NOT want amenity links at all.
        has_amenity_links_flag = False
        if query_source != 'generic' and enquiry_type != "price" and is_amenity_query(query):
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
        
        # 5.5️⃣ Generate amenity links BEFORE prompt creation (so we can include them in the prompt)
        pre_generated_amenity_links = []
        if has_amenity_links_flag and latitude and longitude:
            print(f"🗺️  Pre-generating amenity links for prompt (lat: {latitude}, lng: {longitude})")
            amenity_links_result = generate_context_aware_links(
                query=query,
                latitude=latitude,
                longitude=longitude,
                include_common=True
            )
            relevant = amenity_links_result.get('relevant_links', [])
            suggested = amenity_links_result.get('suggested_links', [])
            # Use relevant links if available, otherwise use suggested links
            pre_generated_amenity_links = relevant if relevant else suggested
            print(f"   → Pre-generated {len(pre_generated_amenity_links)} links for prompt")
        
        # 🏘️ Add nearby properties to context if available (for LLM to see)
        if location_context and location_context.get('nearby_properties_json'):
            nearby_props = location_context['nearby_properties_json']
            print(f"🏘️  Adding {len(nearby_props)} nearby properties to context for LLM")
            
            # Format nearby properties as text for the LLM
            nearby_context = "\n\n=== NEARBY PROPERTIES ===\n"
            nearby_context += f"There are {len(nearby_props)} properties for sale near this location:\n\n"
            
            for idx, prop in enumerate(nearby_props, 1):
                nearby_context += f"{idx}. **{prop.get('title', 'Untitled Property')}**\n"
                nearby_context += f"   Address: {prop.get('address', 'N/A')}\n"
                nearby_context += f"   Distance: {prop.get('distance', 'N/A')}\n"
                if prop.get('price'):
                    nearby_context += f"   Price: ${prop['price']:,.0f}\n"
                if prop.get('bedrooms'):
                    nearby_context += f"   Bedrooms: {prop['bedrooms']}\n"
                if prop.get('bathrooms'):
                    nearby_context += f"   Bathrooms: {prop['bathrooms']}\n"
                nearby_context += f"   Listing Type: {prop.get('listingType', 'N/A').replace('_', ' ').title()}\n"
                nearby_context += "\n"
            
            # Add to context
            context = context + nearby_context if context else nearby_context

        # 🏫 For "nearby schools" queries, extract school names (and any explicit distances)
        # from the listing context and prepend a short structured block.
        # This prevents the LLM from mentioning only one school when multiple are present in PDFs.
        # IMPORTANT: Only extract schools from PROPERTY-SPECIFIC context, not from generic knowledge.
        # Generic knowledge might contain schools from anywhere, not specific to this property location.
        if context and is_amenity_query(query) and query_source == 'property':
            ql = query.lower()
            if "school" in ql or "schools" in ql:
                school_lines = self._extract_school_lines_from_context(context)
                if school_lines:
                    schools_block = "\n\n=== SCHOOLS MENTIONED IN LISTING DATA ===\n" + "\n".join(
                        f"- {line}" for line in school_lines
                    ) + "\n"
                    context = schools_block + "\n" + context
        
        # 5.75️⃣ Inject tone adaptation context
        # IMPORTANT: Only inject tone / market-activity context for PROPERTY-SPECIFIC queries.
        # For GENERIC knowledge questions (laws, processes, etc.) we must not bias the answer
        # with listing-level activity.
        if query_source == 'property' and tone_level != ToneLevel.NEUTRAL and tone_context:
            tone_prompt_context = self.tone_service.format_tone_context_for_prompt(
                tone_level, tone_context
            )
            # Prepend tone context to the main context
            context = tone_prompt_context + "\n\n" + context
            print(
                f"🎭 ✅ Injected {tone_level.value.upper()} tone context into PROPERTY prompt "
                f"({len(tone_prompt_context)} chars)"
            )
            print(f"   Tone instruction preview: {tone_prompt_context[:200]}...")
        else:
            print(
                f"🎭 No tone adaptation applied "
                f"(source={query_source}, tone_level={tone_level.value}, has_context={bool(tone_context)})"
            )
        
        # 6️⃣ Prompt creation
        # DEBUG: Log context before prompt creation
        print(f"\n🔍 DEBUG: Before LLM call:")
        print(f"   Query: '{query}'")
        print(f"   Query source: {query_source}")
        print(f"   Context length: {len(context) if context else 0} chars")
        print(f"   Data sources count: {len(data_sources) if data_sources else 0}")
        if context:
            print(f"   Context preview (first 500 chars): {context[:500]}...")
        else:
            print(f"   ⚠️  WARNING: Context is EMPTY!")
        
        # Use different system prompts and user prompts for generic vs property queries.
        # Additionally, enquiry messages use a separate, formal email-style prompt.
        if query_source == 'generic':
            from app.services.rag_pipeline.prompts import create_generic_user_prompt
            if is_enquiry_message:
                system_prompt = ENQUIRY_EMAIL_SYSTEM_PROMPT
                user_prompt = create_enquiry_email_user_prompt(
                    query=query,
                    context=context or "",
                    is_property_query=False,
                    conversation_history=conversation_history,
                )
            else:
                system_prompt = GENERIC_SYSTEM_PROMPT
                user_prompt = create_generic_user_prompt(
                    query, context, conversation_history=conversation_history
                )
        else:
            if is_enquiry_message:
                system_prompt = ENQUIRY_EMAIL_SYSTEM_PROMPT
                user_prompt = create_enquiry_email_user_prompt(
                    query=query,
                    context=context or "",
                    is_property_query=True,
                    conversation_history=conversation_history,
                )
            else:
                system_prompt = SYSTEM_PROMPT
                if enquiry_type == "bidding":
                    user_prompt = create_bid_advice_prompt(
                        query, context, conversation_history=conversation_history
                    )
                else:
                    user_prompt = create_user_prompt(
                        query,
                        context,
                        has_amenity_links=has_amenity_links_flag,
                        amenity_links_list=pre_generated_amenity_links
                        if has_amenity_links_flag
                        else None,
                        conversation_history=conversation_history,
                    )
        
        print(f"   User prompt length: {len(user_prompt)} chars")
        print(f"   User prompt preview (first 500 chars): {user_prompt[:500]}...")

        messages = [{"role": "system", "content": system_prompt}]
        messages.append({"role": "user", "content": user_prompt})

        # 7️⃣ LLM CALL (SAFE)
        needs_vendor_contact = False
        escalation_reason = None
        rate_limit_error = False
        t_llm_start = time.perf_counter()

        try:
            response = create_chat_completion(
                messages=messages,
                model=self.model_config["model"],
                temperature=self.model_config["temperature"],
                max_tokens=self.model_config["max_tokens"],
            )
            answer = response.choices[0].message.content.strip()
            
            # 🚨 RESPONSE LAYER ENFORCEMENT: Check for price disclosure when displayPrice = false
            if listing_id and enquiry_type == "price" and not display_price:
                # Check if answer contains price information (dollar signs, numbers with currency symbols, etc.)
                import re
                price_patterns = [
                    r'\$\s*\d+[,\d]*',  # $500,000 or $500000
                    r'\d+[,\d]*\s*dollars?',  # 500,000 dollars
                    r'price[:\s]+\$?\d+',  # Price: $500,000
                    r'asking\s+price[:\s]+\$?\d+',  # Asking price: $500,000
                    r'auction\s+start\s+price[:\s]+\$?\d+',  # Auction start price: $500,000
                    r'highest\s+bid[:\s]+\$?\d+',  # Highest bid: $500,000
                ]
                
                contains_price = any(re.search(pattern, answer, re.IGNORECASE) for pattern in price_patterns)
                
                if contains_price:
                    print(f"🔒 RESPONSE LAYER: Detected price disclosure in answer (displayPrice = false) → replacing with fallback")
                    answer = "Please contact the vendor / Unreserved for pricing details."
        
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

        # 9️⃣ Use pre-generated amenity links (already generated before prompt creation)
        # Links were already generated in step 5.5 and included in the LLM prompt
        final_amenity_links = pre_generated_amenity_links if has_amenity_links_flag else []

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

        now = time.perf_counter()
        # Merge retriever's fine-grained timers (from last retrieve call) into breakdown
        try:
            for k, v in getattr(self.augmenter.retriever, "_last_timings", {}).items():
                timings_breakdown[f"retrieval_{k}"] = round(v, 2)
        except Exception:
            pass
        eval_timings = {
            "retrieval_ms": (t_llm_start - t_start) * 1000.0 if t_llm_start is not None else 0.0,
            "llm_ms": (now - t_llm_start) * 1000.0 if t_llm_start is not None else 0.0,
            "total_ms": (now - t_start) * 1000.0,
            "breakdown": {k: round(v, 2) for k, v in timings_breakdown.items()},
        }
        return {
            "ai_response": ai_response,
            "log_entry": log_entry,
            "nearby_properties": nearby_properties_json,
            "amenity_links": final_amenity_links,
            "eval_timings": eval_timings,
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

    def _extract_school_lines_from_context(self, context: str) -> List[str]:
        """
        Best-effort extraction of school names (and optional distances) from listing context.
        This is used to make responses deterministic for school questions without inventing data.
        """
        import re

        # Common school name patterns found in PDFs
        name_pat = re.compile(
            r"\b([A-Z][A-Za-z&'’\-\s]{2,}?\s(?:Primary School|Secondary College|Secondary School|College|Grammar|School))\b"
        )

        candidates = [m.group(1).strip() for m in name_pat.finditer(context)]

        # De-dupe preserving order
        seen = set()
        names: List[str] = []
        for n in candidates:
            key = re.sub(r"\s+", " ", n).strip().lower()
            if key and key not in seen:
                seen.add(key)
                names.append(n)

        if not names:
            return []

        lines: List[str] = []
        for name in names[:8]:  # cap
            idx = context.find(name)
            window = context[max(0, idx - 140): min(len(context), idx + 260)] if idx != -1 else context
            m = re.search(r"(?:approx(?:imately)?\\.?\\s*)?(\\d+(?:\\.\\d+)?)\\s*km", window, flags=re.IGNORECASE)
            if m:
                lines.append(f"**{name}** (approximately **{m.group(1)} km** away)")
            else:
                lines.append(f"**{name}**")

        return lines

    def _generate_conversational_reply(
        self,
        query: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Let the LLM respond naturally to conversational messages (thanks, nice, small talk). No retrieval."""
        messages = [{"role": "system", "content": CONVERSATIONAL_SYSTEM_PROMPT}]
        if conversation_history:
            for msg in conversation_history:
                role = (msg.get("role") or "user").lower()
                if role not in ("user", "assistant"):
                    role = "user"
                content = msg.get("content") or ""
                if content.strip():
                    messages.append({"role": role, "content": content.strip()})
        messages.append({"role": "user", "content": query})
        response = create_chat_completion(
            messages=messages,
            model=self.model_config["model"],
            temperature=self.model_config["temperature"],
            max_tokens=min(150, self.model_config["max_tokens"]),
        )
        return (response.choices[0].message.content or "").strip()

    def _classify_intent_listing_vs_conversational(
        self,
        query: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Classify whether the user message needs listing data (LISTING) or is conversational (CONVERSATIONAL). Returns 'listing' or 'conversational'."""
        user_content = f"User message: {query.strip()}"
        if conversation_history:
            recent = conversation_history[-4:]  # last 2 exchanges
            if recent:
                parts = [f"{m.get('role', 'user')}: {m.get('content', '')}" for m in recent]
                user_content = "Recent conversation:\n" + "\n".join(parts) + "\n\n" + user_content
        messages = [
            {"role": "system", "content": INTENT_CLASSIFIER_SYSTEM},
            {"role": "user", "content": user_content},
        ]
        try:
            response = create_chat_completion(
                messages=messages,
                model=self.model_config["model"],
                temperature=0,
                max_tokens=10,
            )
            raw = (response.choices[0].message.content or "").strip().upper()
            if "CONVERSATIONAL" in raw:
                return "conversational"
            return "listing"
        except Exception:
            return "listing"

    def _generate_personal_advice_message(self, query: str) -> str:
        return (
            "I cannot provide personal advice, recommendations, or suggestions about whether to buy, "
            "purchase, invest in, or make offers on properties. These decisions require assessment by "
            "qualified professionals such as lawyers, financial advisors, or licensed real estate agents.\n\n"
            "I can help with factual details about the property instead, such as specifications, "
            "pricing information, location details, and property features."
        )

    def _generate_vendor_contact_message(
        self, query: str, reason: Optional[str] = None, is_enquiry_message: bool = False
    ) -> str:
        # IMPORTANT (privacy/UX): never surface internal retrieval reasons to end users.
        # The `reason` is kept for logging/diagnostics via `escalation_reason`, but must
        # not appear in the user-facing answer.
        _ = reason  # explicitly unused
        
        # Use enquiry-specific message for enquiry messages
        if is_enquiry_message:
            return (
                "This is an automated email. We don't have enough information to answer this enquiry "
                "right now, but we will get back to you shortly."
            )
        
        return (
            "I don't have sufficient information in the available listing data "
            "to answer this fully.\n\n"
            "Please contact the vendor or listing agent for accurate details."
        )
