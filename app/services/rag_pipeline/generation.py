"""
Generation module for creating AI responses to buyer enquiries.
"""
import asyncio
import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple


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
from app.services.rag_pipeline.config import (
    GENERIC_SIMILARITY_THRESHOLD,
    DEFAULT_MAX_DISTANCE_KM,
    DEFAULT_MAX_NEARBY_PROPERTIES,
)
from app.schemas import AIResponse, EnquiryLog
from app.core.exceptions import classify_llm_error
from app.db.connection import get_session_maker
from app.services.rag_pipeline.augmentation import QueryAugmenter
from app.services.rag_pipeline.preprocess import detect_enquiry_type, detect_query_source
from app.services.rag_pipeline.postprocess import sanitize_response
from app.services.rag_pipeline.google_maps_links import (
    generate_context_aware_links,
    generate_custom_search_link,
    is_amenity_query,
    is_invalid_amenity_query,
)
from app.services.tone_adaptation_service import ToneAdaptationService, ToneLevel


logger = logging.getLogger(__name__)

# Constants (some centralized in config.py)
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

# Queries that ask about inspection times/slots for a listing → we fetch from listing_inspections
INSPECTION_QUERY_KEYWORDS = [
    # Explicit inspection phrases
    'inspection slot', 'inspection slots', 'inspection time', 'inspection times',
    'inspection schedule', 'inspection dates', 'when can i inspect', 'when to inspect',
    'open for inspection', 'book inspection', 'book a viewing', 'closest to be booked',
    'which inspection', 'next inspection', 'upcoming inspection', 'viewing times',
    # Open home / open house / open times (common natural language)
    'open time', 'open times', 'open day', 'open days', 'open house', 'open homes',
    'opening time', 'opening times', 'opening day', 'opening days',
    'when is it open', 'when are the opens', 'when can i view',
    'when can i visit', 'when can i see', 'can i view', 'can i visit',
    'viewing', 'viewings', 'home open', 'home opens',
    # Generic "when" queries about property access
    'when is the inspection', 'when are the inspections',
    'scheduled inspection', 'scheduled inspections',
    'private inspection', 'private inspections',
]

# Tone adaptation only when user is sufficiently conversational (has asked at least this many questions)
# Set TONE_ADAPTATION_MIN_USER_MESSAGES=10 in env to require 10+ messages instead of 7.
TONE_ADAPTATION_MIN_USER_MESSAGES = int(os.getenv("TONE_ADAPTATION_MIN_USER_MESSAGES", "7"))

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
    
    def close(self):
        """Close the response generator and release all resources."""
        if hasattr(self, 'augmenter') and self.augmenter:
            try:
                self.augmenter.close()
            except Exception as e:
                logger.warning("⚠️  Error closing augmenter: %s", e)
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures cleanup."""
        self.close()
    
    async def _do_conversational_reply(
        self,
        query: str,
        conversation_history: Optional[List[Dict[str, str]]],
        listing_id: Optional[str],
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        """Build and return the standard response dict for conversational/acknowledgment replies."""
        try:
            answer = await self._generate_conversational_reply(query, conversation_history)
        except Exception as e:
            logger.warning("⚠️ Conversational LLM fallback error: %s", e)
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

    def _handle_greeting(
        self,
        query: str,
        listing_id: Optional[str],
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        """Return the standard greeting response dict."""
        answer = (
            "Hello! 👋 I'm here to help you learn more about this property. "
            "You can ask me about:\n\n"
            "• **Pricing** and sale methods\n"
            "• **Property features** (bedrooms, bathrooms, land area, etc.)\n"
            "• **Location** and nearby amenities\n"
            "• **Nearby properties** for sale\n"
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

    def _handle_negotiation(
        self,
        query: str,
        listing_id: Optional[str],
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        """Return the standard negotiation escalation response dict."""
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

    async def _try_generic_knowledge_first(
        self,
        query: str,
        n_retrieval_results: int,
        is_enquiry_message: bool,
        listing_id: Optional[str],
        user_id: Optional[str],
        timings_breakdown: Dict[str, float],
    ) -> Tuple[Optional[Dict[str, Any]], str, List[Any], Any, str]:
        """
        Try generic knowledge store first. Returns (early_return_dict_or_None, context, data_sources, location_context, query_source).
        If early_return_dict is not None, caller should return it. Otherwise caller uses the context/data_sources/query_source.
        """
        logger.info(
            "🔍 Step 1: Generic query detected → trying generic knowledge store first",
        )
        _t = time.perf_counter()
        generic_context, generic_data_sources, _ = await self.augmenter.augment_query(
            query=query,
            listing_id=None,
            n_results=n_retrieval_results,
            query_source='generic'
        )
        timings_breakdown["augment_generic_ms"] = (time.perf_counter() - _t) * 1000.0

        if generic_data_sources and generic_context and generic_context.strip():
            logger.info("✅ Generic knowledge found → using generic data")
            logger.debug("   Context length: %d chars", len(generic_context))
            logger.debug("   Data sources: %d", len(generic_data_sources))
            top_sim = (
                generic_data_sources[0].similarity_score
                if generic_data_sources[0].similarity_score is not None
                else 0.0
            )
            logger.debug("   First source similarity: %.4f", top_sim)
            return (None, generic_context, generic_data_sources, None, 'generic')

        # Generic query but no results from generic KB.
        # Note: this path is only reached when there is no listing_id (or is_strong_generic).
        # When listing_id is present, routing sends the query to the property-first cascade
        # which handles generic KB fallback internally via similarity thresholds.
        logger.info("⚠️  Generic query returned no results from generic KB")
        logger.debug(
            "   Debug: generic_data_sources=%d, context_length=%d",
            len(generic_data_sources) if generic_data_sources else 0,
            len(generic_context) if generic_context else 0,
        )
        _trend_kw = (
            'price trend', 'price trends', 'market trend', 'market trends',
            'trends for this area', 'trends in this area', 'trends in the area',
        )
        is_trend = any(kw in query.lower() for kw in _trend_kw)
        if is_enquiry_message:
            answer = (
                "This is an automated email. We don't have enough information to answer this enquiry "
                "right now, but we will get back to you shortly."
            )
        elif is_trend and listing_id:
            answer = (
                "I don't have price or market trend data for this area in the listing documents. "
                "For a detailed market report, please contact the agent or Unreserved. "
                "I can help with this property's asking price, features, inspections, and location."
            )
        else:
            answer = (
                "I don't have sufficient information in the available listing data "
                "to answer this fully.\n\n"
                "Please contact the Unreserved Admin for more information."
            )
        response_dict = self._create_response_dict(
            answer=answer,
            needs_vendor_contact=False,
            escalation_reason="No relevant information found in generic knowledge base",
            data_sources=[],
            query=query,
            listing_id=listing_id,
            user_id=user_id,
        )
        return (response_dict, "", [], None, 'property')

    # ------------------------------------------------------------------
    # MAIN GENERATION METHOD
    # ------------------------------------------------------------------
    async def generate_response(
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
            logger.info("🔄 Query rewritten: '%s' → '%s'", query, rewritten_query)
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

        if is_conversational or is_acknowledgment:
            logger.info("✅ Conversational/acknowledgment detected → LLM replying naturally (skipping retrieval)")
            return await self._do_conversational_reply(query, conversation_history, listing_id, user_id)

        # For short or ambiguous messages, let the LLM decide if this needs listing data or is conversational
        word_count = len(query_stripped.split())
        char_count = len(query_stripped)
        is_short_or_ambiguous = word_count <= 12 or char_count <= 80
        if is_short_or_ambiguous:
            intent = await self._classify_intent_listing_vs_conversational(query, conversation_history)
            if intent == "conversational":
                logger.info("✅ Intent classifier → conversational (skipping retrieval)")
                return await self._do_conversational_reply(query, conversation_history, listing_id, user_id)

        # 0.5️⃣ Check for greetings FIRST (before any routing)
        _t = time.perf_counter()
        enquiry_type = detect_enquiry_type(query)
        timings_breakdown["detect_enquiry_type_ms"] = (time.perf_counter() - _t) * 1000.0
        if enquiry_type == "greeting":
            logger.info("👋 Greeting detected → returning friendly welcome message")
            return self._handle_greeting(query, listing_id, user_id)

        # 1️⃣ Check for negotiation/pricing advice queries FIRST (must escalate to vendor)
        query_lower = query.lower()
        is_negotiation_query = any(keyword in query_lower for keyword in NEGOTIATION_KEYWORDS)

        if is_negotiation_query:
            logger.info("🚨 Negotiation query detected → escalating to vendor/agent")
            return self._handle_negotiation(query, listing_id, user_id)

        # 2️⃣ Detect query source (property vs generic)
        _t = time.perf_counter()
        query_source_detected = detect_query_source(
            query,
            conversation_history=conversation_history,
            listing_id=listing_id,
        )
        timings_breakdown["detect_query_source_ms"] = (time.perf_counter() - _t) * 1000.0

        # Strong generic indicators (legal/process questions that will never be in property PDFs)
        is_strong_generic = any(kw in query.lower() for kw in STRONG_GENERIC_KEYWORDS)

        logger.debug(
            "🔍 Query detection: query_source_detected=%s, is_strong_generic=%s, listing_id=%s",
            query_source_detected,
            is_strong_generic,
            listing_id,
        )

        # 3️⃣ ROUTING LOGIC
        #
        # Go to generic-first ONLY when:
        #   a) query is about real-estate law/process (is_strong_generic) — these are never in
        #      property PDFs so property search would just waste a retrieval round-trip, OR
        #   b) classified as generic AND there is no listing_id — nothing property-specific
        #      to search anyway.
        #
        # In ALL other cases (including when LLM says "generic" but listing_id is present),
        # go to the property-first path.  The property cascade (JSON → PDF → generic KB →
        # escalate) uses cosine-similarity thresholds to decide relevance semantically, so
        # keyword-based overrides are no longer needed.
        if is_strong_generic or (query_source_detected == 'generic' and not listing_id):
            early_return, context, data_sources, location_context, query_source = (
                await self._try_generic_knowledge_first(
                    query=query,
                    n_retrieval_results=n_retrieval_results,
                    is_enquiry_message=is_enquiry_message,
                    listing_id=listing_id,
                    user_id=user_id,
                    timings_breakdown=timings_breakdown,
                )
            )
            if early_return is not None:
                return early_return
            # else context, data_sources, location_context, query_source are set
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
                    from app.db.connection import get_session_maker
                    async_session_maker = get_session_maker()
                    async with async_session_maker() as db_session:
                        listing_repo = ListingRepository(db_session)
                        listing_data = await listing_repo._execute_query_one(
                            "SELECT display_price FROM listings WHERE id = :listing_id",
                            {"listing_id": listing_id}
                        )
                        if listing_data:
                            display_price = listing_data.get('display_price', True)
                            logger.debug(
                                "🔒 Price visibility check: displayPrice=%s for listing %s",
                                display_price,
                                listing_id,
                            )
                   
                except Exception as e:
                    logger.warning(
                        "⚠️  Failed to fetch displayPrice from database for %s: %s: %s",
                        listing_id,
                        type(e).__name__,
                        e,
                    )
                timings_breakdown["display_price_db_ms"] = (time.perf_counter() - _t_db) * 1000.0
                    # Default to True (show price) if we can't fetch - safer default
                
                # ============================================================
                # NEW APPROACH: PARALLEL RETRIEVAL - ALWAYS COMBINE JSON + PDFs
                # This ensures PDF content is always available to the LLM
                # ============================================================
                
                logger.info("🔍 PARALLEL RETRIEVAL: Getting JSON + PDF chunks together (listing_id: %s)", listing_id)
                
                _t = time.perf_counter()
                
                # Run BOTH retrievals in parallel for speed + completeness
                json_task = self.augmenter.augment_query_json_chunks(
                    query=query,
                    listing_id=listing_id,
                    n_results=n_retrieval_results
                )
                pdf_task = self.augmenter.augment_query_pdf_chunks(
                    query=query,
                    listing_id=listing_id,
                    n_results=n_retrieval_results
                )
                
                # Wait for both to complete
                (
                    (property_json_context, property_json_data_sources, property_location_context),
                    (property_pdf_context, property_pdf_data_sources, _)
                ) = await asyncio.gather(json_task, pdf_task)
                
                timings_breakdown["augment_json_ms"] = (time.perf_counter() - _t) * 1000.0
                timings_breakdown["augment_pdf_ms"] = (time.perf_counter() - _t) * 1000.0
                
                logger.info("✅ PARALLEL RETRIEVAL complete: JSON=%d chunks, PDF=%d chunks",
                    len(property_json_data_sources), len(property_pdf_data_sources))
                
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
                        logger.info(
                            "🔒 RETRIEVAL LAYER: Filtered out %d pricing chunk(s) (displayPrice = false)",
                            filtered_count,
                        )
                        # Also remove pricing content from context
                        property_json_context = re.sub(
                            r'=== PROPERTY LISTING:.*?===\s*\[PRICING\].*?(?=\[|===|$)',
                            '',
                            property_json_context,
                            flags=re.DOTALL
                        )
                
                # ============================================================
                # ALWAYS COMBINE: JSON + PDF chunks together
                # Let the LLM decide which source to use, don't block based on "sufficiency"
                # ============================================================
                
                # Build combined context - JSON first (has structured data), then PDF (has detailed docs)
                context_parts = []
                data_sources = []
                
                if property_json_context and property_json_context.strip():
                    context_parts.append(property_json_context)
                    data_sources.extend(property_json_data_sources)
                    logger.info("   📄 Including JSON chunks: %d", len(property_json_data_sources))
                
                if property_pdf_context and property_pdf_context.strip():
                    context_parts.append(property_pdf_context)
                    property_pdf_filtered = [
                        ds for ds in property_pdf_data_sources 
                        if ds.chunk_type == 'property_document'
                    ]
                    data_sources.extend(property_pdf_filtered)
                    logger.info("   📄 Including PDF chunks: %d", len(property_pdf_filtered))
                
                # Combine both contexts
                context = "\n\n".join(context_parts)
                query_source = 'property'
                property_sufficient = len(data_sources) > 0

                # ── KEYWORD BOOST ──────────────────────────────────────────
                # If the query mentions a specific address / proper noun (e.g.
                # "Fingal Court", "fingal court"), cosine-similarity ranking may
                # not surface the exact chunk at the top.  Detect street-name
                # patterns (case-insensitive) and prepend directly-matching
                # chunks so the LLM sees them first.
                if listing_id and property_sufficient:
                    _STREET_SFXS = (
                        r'(?:court|drive|street|road|avenue|way|boulevard|'
                        r'blvd|lane|place|terrace|close|circuit|crescent|'
                        r'grove|rise|park|parade|highway|run|vale|mews|'
                        r'ct|rd|ave)'
                    )
                    # Capture 1-3 words immediately before a street suffix
                    _raw = re.findall(
                        rf'\b([a-zA-Z]+(?:\s+[a-zA-Z]+)?)\s+{_STREET_SFXS}\b',
                        query,
                        re.IGNORECASE,
                    )
                    # Reconstruct full phrase (name + suffix)
                    _full = re.findall(
                        rf'\b([a-zA-Z]+(?:\s+[a-zA-Z]+)?\s+{_STREET_SFXS})\b',
                        query,
                        re.IGNORECASE,
                    )
                    # Strip leading prepositions (e.g. "in fingal court" → "fingal court")
                    _PREP = {
                        'in', 'at', 'on', 'from', 'near', 'around', 'off',
                        'along', 'the', 'a', 'an', 'to', 'for', 'of', 'by',
                        'with', 'about', 'into', 'there', 'this', 'that',
                        'did', 'does', 'do', 'was', 'is', 'are', 'were',
                        'has', 'have', 'had', 'what', 'which', 'how',
                    }
                    addr_terms = []
                    for phrase in _full:
                        words = phrase.lower().split()
                        while words and words[0] in _PREP:
                            words = words[1:]
                        cleaned = ' '.join(words)
                        if cleaned and len(cleaned) > 4:
                            addr_terms.append(cleaned)

                    # Also extract capitalized multi-word proper nouns (e.g. "Casuarina Drive")
                    _COMMON = {
                        'The','This','These','Those','That','What','When',
                        'Where','Why','How','I','We','They','He','She','It',
                        'Is','Are','Was','Were','Did','Does','Can','Could',
                        'Would','Should','Please','For','In','At','On',
                        'From','With','And','Or','But','If','As','By','To',
                        'A','An','Do','Not','No','My','Your','Our','Their',
                        'Has','Have','Had','Will','Get',
                    }
                    cap_terms = re.findall(
                        r'\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+)\b',
                        query,
                    )
                    for t in cap_terms:
                        if not all(w in _COMMON for w in t.split()):
                            addr_terms.append(t.lower())

                    addr_terms = list(dict.fromkeys(addr_terms))  # deduplicate, preserve order

                    if addr_terms:
                        logger.info(
                            "🔍 KEYWORD BOOST: found address terms %s — running ILIKE search",
                            addr_terms,
                        )
                        kw_ctx, kw_sources = self.augmenter.keyword_search_chunks(
                            listing_id=listing_id,
                            keywords=addr_terms,
                        )
                        if kw_ctx:
                            boost_terms_str = ", ".join(addr_terms)
                            context = (
                                f"🚨🚨🚨 CRITICAL — NEW INFORMATION FOUND FOR: {boost_terms_str.upper()} 🚨🚨🚨\n"
                                f"The following property data was retrieved specifically for '{boost_terms_str}'.\n"
                                f"REGARDLESS of any previous conversation where you said you had no information,\n"
                                f"you MUST use the data below to answer the current question.\n"
                                f"DO NOT say 'I don't have information' — the answer IS in the data below.\n\n"
                                + kw_ctx
                                + "\n\n=== FULL LISTING CONTEXT ===\n"
                                + context
                            )
                            # Deduplicate: remove kw_sources content already in data_sources
                            existing_previews = {ds.content_preview for ds in data_sources}
                            new_sources = [
                                s for s in kw_sources
                                if s.content_preview not in existing_previews
                            ]
                            data_sources = new_sources + data_sources
                            logger.info(
                                "✅ KEYWORD BOOST: prepended %d chunk(s) for terms %s",
                                len(new_sources),
                                addr_terms,
                            )
                # ── END KEYWORD BOOST ──────────────────────────────────────

                if property_sufficient:
                    logger.info("✅ Combined context: JSON + PDF = %d total chunks", len(data_sources))
                else:
                    logger.warning("⚠️ No property chunks found (neither JSON nor PDF)")
            else:
                logger.info("🔍 No listing_id provided → skipping property data")
                # Initialize for the generic fallback check
                property_json_data_sources = []
                property_pdf_data_sources = []
                property_location_context = None
            
            # Step 3/4: Try generic knowledge as fallback (if property data insufficient)
            generic_context = ""
            generic_data_sources = []

            # Skip generic knowledge if we already have sufficient data (including location_context with nearby properties)
            has_location_data = property_location_context and property_location_context.get('nearby_properties_json')
            if not property_sufficient or (not property_json_data_sources and not property_pdf_data_sources and not has_location_data):
                logger.info("🔍 Step 3/4: Trying generic knowledge (generic PDFs from generic_knowledge)")
                generic_context, generic_data_sources, _ = await self.augmenter.augment_query(
                    query=query,
                    listing_id=None,
                    n_results=n_retrieval_results,
                    query_source='generic'
                )
                
                if generic_data_sources and generic_context and generic_context.strip():
                    # Check if generic data has good similarity
                    top_similarity = (
                        generic_data_sources[0].similarity_score
                        if generic_data_sources
                        and generic_data_sources[0].similarity_score is not None
                        else 0.0
                    )
                    logger.debug(
                        "           → Found %d generic chunks",
                        len(generic_data_sources),
                    )
                    logger.debug("           → Top similarity: %.4f", top_similarity)

                    if top_similarity > GENERIC_SIMILARITY_THRESHOLD:
                        logger.info(
                            "✅ Step 3/4: Generic knowledge found and relevant → using generic data",
                        )
                        context = generic_context
                        data_sources = generic_data_sources
                        location_context = None
                        query_source = 'generic'
                    else:
                        logger.info(
                            "⚠️  Step 3/4: Generic knowledge found but low relevance (similarity: %.4f)",
                            top_similarity,
                        )
                        # Continue to Step 4
                        property_sufficient = False
                else:
                    logger.info("⚠️  Step 3/4: No generic knowledge found")
            
            # Step 4/4: If all previous steps failed, escalate to vendor
            # UNLESS listing has lat/lon AND query is an amenity query → we can answer amenity queries with Google Maps links
            has_location_data = property_location_context and property_location_context.get('nearby_properties_json')
            if not property_sufficient or (not property_json_data_sources and not property_pdf_data_sources and not has_location_data):
                if not (generic_data_sources and generic_context and generic_context.strip()):
                    # Check if this is actually an amenity query before generating amenity links
                    query_is_amenity = is_amenity_query(query)
                    logger.info(f"🔍 Step 4/4: Checking amenity links - is_amenity_query: {query_is_amenity}")
                    
                    skip_escalation_for_amenity_links = False
                    if listing_id and query_is_amenity:
                        try:
                            from app.db.postgres.repositories.listing_repository import ListingRepository
                            async_session_maker = get_session_maker()
                            async with async_session_maker() as db_session:
                                listing_repo = ListingRepository(db_session)
                                loc = await listing_repo.get_listing_location(listing_id)
                                if loc and loc.get('latitude') is not None and loc.get('longitude') is not None:
                                    skip_escalation_for_amenity_links = True
                                    if not location_context:
                                        location_context = {}
                                    location_context['latitude'] = loc.get('latitude')
                                    location_context['longitude'] = loc.get('longitude')
                                    context = (
                                        "The user is asking about nearby amenities (e.g. police stations, schools, hospitals). "
                                        "Use the Google Maps links provided below to direct them."
                                    )
                                    logger.info("🗺️  Step 4/4: Query is amenity-related + listing has coordinates → using amenity links")
                        except Exception as e:
                            logger.debug("Step 4/4: Could not fetch listing location: %s", e)

                    if not skip_escalation_for_amenity_links:
                        logger.info("⚠️  Step 4/4: All data sources insufficient → escalating to vendor")
                        fallback_reason = insufficiency_reason if insufficiency_reason else (
                            "Insufficient information in property JSON, property PDFs, and no relevant generic knowledge found"
                        )
                        answer = await self._generate_vendor_contact_message(query, fallback_reason, is_enquiry_message)

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

        # NOTE: PDF chunks are always retrieved in parallel with JSON (asyncio.gather above),
        # so no additional PDF supplement is needed here.

        # 4️⃣ Final check - if we still don't have context, provide fallback
        # Last resort when we have listing_id: try location (for amenity links) and property PDF chunks (no keyword lists)
        has_location_data = location_context and location_context.get('nearby_properties_json')
        has_last_resort_data = False
        if (not context or not data_sources) and not has_location_data and listing_id:
            try:
                from app.db.postgres.repositories.listing_repository import ListingRepository
                async_session_maker = get_session_maker()
                async with async_session_maker() as db_session:
                    listing_repo = ListingRepository(db_session)
                    loc = await listing_repo.get_listing_location(listing_id)
                    if loc and loc.get('latitude') is not None and loc.get('longitude') is not None:
                        if not location_context:
                            location_context = {}
                        location_context['latitude'] = loc.get('latitude')
                        location_context['longitude'] = loc.get('longitude')
                        context = (
                            "The user is asking about nearby amenities. Use the Google Maps links provided below."
                        )
                        has_last_resort_data = True
                        logger.info("🗺️  Last resort: listing has coordinates → will add amenity links")
            except Exception as e:
                logger.debug("Last resort location fetch failed: %s", e)

            if not has_last_resort_data:
                pdf_ctx, pdf_sources, _ = await self.augmenter.augment_query_pdf_chunks(
                    query=query, listing_id=listing_id, n_results=5
                )
                if pdf_ctx and pdf_ctx.strip() and pdf_sources:
                    context = pdf_ctx
                    data_sources = pdf_sources
                    has_last_resort_data = True
                    logger.info("🗺️  Last resort: got property PDF context → will answer from PDF")

        if (not context or not data_sources) and not has_location_data and not has_last_resort_data:
            # Final fallback - no data from either source
            logger.info("⚠️  No data found in property or generic stores → providing fallback message")
            if is_enquiry_message:
                answer = (
                    "This is an automated email. We don't have enough information to answer this enquiry "
                    "right now, but we will get back to you shortly."
                )
            else:
                answer = (
                    "I don't have sufficient information in the available listing data "
                    "to answer this fully.\n\n"
                    "Please contact the Unreserved Admin for more information."
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
            answer = await self._generate_personal_advice_message(query)
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
        # Skip for inspection queries: "closest to be booked" contains "close" + "book" and would false-positive
        is_inspection_query = listing_id and any(kw in query.lower() for kw in INSPECTION_QUERY_KEYWORDS)
        if not is_inspection_query and is_invalid_amenity_query(query):
            logger.info("⚠️  Invalid/irrelevant amenity query detected: '%s'", query)

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
        # Only apply tone when the user is being sufficiently conversational (7+ questions).
        listing_activity_data = None
        tone_level = ToneLevel.NEUTRAL
        tone_context = ""
        user_msg_count = sum(
            1 for m in (conversation_history or [])
            if str(m.get("role", "")).lower() == "user"
        )
        total_user_messages = user_msg_count + 1  # include current query
        is_conversational_enough = total_user_messages >= TONE_ADAPTATION_MIN_USER_MESSAGES

        if query_source == "property" and listing_id and is_conversational_enough:
            try:
                
                from app.db.postgres.repositories.listing_activity_repository import ListingActivityRepository
                
                async_session_maker = get_session_maker()
                async with async_session_maker() as db_session:
                    activity_repo = ListingActivityRepository(db_session)
                    listing_activity_data = await activity_repo.get_activity_dict(listing_id)
                    
                    if listing_activity_data:
                        logger.info("🎭 Fetching tone adaptation for listing %s", listing_id)
                        logger.debug(
                            "   Activity metrics: enquiries=%s, offers=%s, contracts=%s",
                            listing_activity_data.get('enquiries_7d', 0),
                            listing_activity_data.get('genuine_offers_7d', 0),
                            listing_activity_data.get('contract_requests_7d', 0),
                        )
                        
                        tone_level, tone_context = self.tone_service.determine_tone(listing_activity_data)
                        
                        if tone_level != ToneLevel.NEUTRAL:
                            logger.info("🎭 Tone adaptation: %s", tone_level.value.upper())
                            logger.debug("   Context: %s", tone_context[:150] + "...")
                        else:
                            logger.info("🎭 Tone adaptation: NEUTRAL (no special conditions met)")
                    else:
                        logger.info(
                            "🎭 No activity data found for listing %s → using NEUTRAL tone",
                            listing_id,
                        )
         
            except Exception as e:
                logger.exception(
                    "⚠️  Failed to get listing activity metrics: %s: %s",
                    type(e).__name__,
                    e,
                )
        elif query_source == "property" and listing_id and not is_conversational_enough:
            logger.debug(
                "🎭 Skipping tone adaptation: user messages=%d (need >=%d to be conversational)",
                total_user_messages,
                TONE_ADAPTATION_MIN_USER_MESSAGES,
            )
        else:
            logger.debug(
                "🎭 Skipping activity metrics/tone adaptation (query_source=%s, listing_id=%s)",
                query_source,
                listing_id,
            )
        
        # 5.5️⃣ Google Maps links: create whenever the listing has latitude and longitude
        has_amenity_links_flag = False
        latitude = None
        longitude = None

        if location_context:
            latitude = location_context.get('latitude')
            longitude = location_context.get('longitude')

        if (latitude is None or longitude is None) and listing_id:
            try:
                from app.db.postgres.repositories.listing_repository import ListingRepository
                async_session_maker = get_session_maker()
                async with async_session_maker() as db_session:
                    listing_repo = ListingRepository(db_session)
                    location_data = await listing_repo.get_listing_location(listing_id)
                    if location_data:
                        latitude = location_data.get('latitude')
                        longitude = location_data.get('longitude')
                        if location_context is None:
                            location_context = {}
                        location_context['latitude'] = latitude
                        location_context['longitude'] = longitude
            except Exception as e:
                logger.warning(
                    "⚠️  Failed to fetch location for listing %s: %s",
                    listing_id,
                    e,
                )

        # Only add amenity links when the query is about amenities (schools, hospitals, bars, etc.),
        # not for price trends, inspections, or other non-amenity questions.
        # Step 1: fast keyword-based check (no API call)
        llm_amenity_terms: List[str] = []   # terms identified by LLM fallback (if used)
        if latitude is not None and longitude is not None and is_amenity_query(query):
            has_amenity_links_flag = True
        elif latitude is not None and longitude is not None and context:
            # Step 2: LLM fallback — only when keywords didn't match.
            # Only generates a link if the LLM confirms it's an amenity AND the term
            # actually appears in the retrieved property context (verified by regex).
            logger.info("🗺️  Keyword check missed — trying LLM amenity classifier fallback")
            llm_result = await self._classify_amenity_with_llm(query, context)
            if llm_result["is_amenity"] and llm_result["found_in_context"]:
                has_amenity_links_flag = True
                llm_amenity_terms = llm_result["amenity_terms"]
                logger.info(
                    "🗺️  LLM fallback matched amenity terms: %s (found in context)",
                    llm_amenity_terms,
                )
            else:
                logger.debug(
                    "🗺️  LLM fallback: is_amenity=%s found_in_context=%s — no link generated",
                    llm_result.get("is_amenity"),
                    llm_result.get("found_in_context"),
                )

        # Generate amenity links only when the query is amenity-related
        pre_generated_amenity_links = []
        if has_amenity_links_flag and latitude is not None and longitude is not None:
            logger.info(
                "🗺️  Pre-generating amenity links for prompt (lat: %s, lng: %s)",
                latitude,
                longitude,
            )
            if llm_amenity_terms:
                # LLM fallback path: build targeted links for exactly the terms the LLM found
                for term in llm_amenity_terms:
                    link = generate_custom_search_link(term, latitude, longitude)
                    pre_generated_amenity_links.append(link)
                logger.info(
                    "   → LLM fallback generated %d targeted link(s): %s",
                    len(pre_generated_amenity_links),
                    llm_amenity_terms,
                )
            else:
                # Keyword match path: use context-aware generation (relevant → common fallback)
                amenity_links_result = generate_context_aware_links(
                    query=query,
                    latitude=latitude,
                    longitude=longitude,
                    include_common=True,
                )
                relevant = amenity_links_result.get('relevant_links', [])
                suggested = amenity_links_result.get('suggested_links', [])
                pre_generated_amenity_links = relevant if relevant else suggested
            logger.debug(
                "   → Pre-generated %d links for prompt",
                len(pre_generated_amenity_links),
            )
        
        # 🏘️ Add nearby properties to context if available (for LLM to see)
        if location_context and location_context.get('nearby_properties_json'):
            nearby_props = location_context['nearby_properties_json']
            logger.info(
                "🏘️  Adding %d nearby properties to context for LLM",
                len(nearby_props),
            )
            
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
                school_lines = await self._extract_school_lines_from_context(context)
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
            logger.info(
                "🎭 ✅ Injected %s tone context into PROPERTY prompt (%d chars)",
                tone_level.value.upper(),
                len(tone_prompt_context),
            )
            logger.debug(
                "   Tone instruction preview: %s",
                tone_prompt_context[:200] + "...",
            )
        else:
            logger.debug(
                "🎭 No tone adaptation applied (source=%s, tone_level=%s, has_context=%s)",
                query_source,
                tone_level.value,
                bool(tone_context),
            )

        # Inject live inspection slots from listing_inspections when query is about inspections
        if listing_id and any(kw in query.lower() for kw in INSPECTION_QUERY_KEYWORDS):
            inspection_context = await self._get_listing_inspection_context(listing_id)
            if inspection_context:
                context = (context or "") + "\n\n" + inspection_context
                logger.info("📅 Injected inspection slots from listing_inspections into context")
        
        # 6️⃣ Prompt creation
        # DEBUG: Log context before prompt creation
        logger.debug("🔍 DEBUG: Before LLM call:")
        logger.debug("   Query: '%s'", query)
        logger.debug("   Query source: %s", query_source)
        logger.debug("   Context length: %d chars", len(context) if context else 0)
        logger.debug("   Data sources count: %d", len(data_sources) if data_sources else 0)
        if context:
            logger.debug("   Context preview (first 500 chars): %s", context[:500] + "...")
        else:
            logger.debug("   ⚠️  WARNING: Context is EMPTY!")
        
        # Build messages for generic vs property queries (and enquiry email style).
        messages = self._build_llm_messages(
            query=query,
            context=context or "",
            query_source=query_source,
            enquiry_type=enquiry_type,
            is_enquiry_message=is_enquiry_message,
            conversation_history=conversation_history,
            has_amenity_links_flag=has_amenity_links_flag,
            pre_generated_amenity_links=pre_generated_amenity_links,
        )
        user_prompt = messages[-1]["content"] if messages else ""
        logger.debug("   User prompt length: %d chars", len(user_prompt))
        logger.debug("   User prompt preview (first 500 chars): %s", user_prompt[:500] + "...")

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
                    logger.info(
                        "🔒 RESPONSE LAYER: Detected price disclosure in answer (displayPrice = false) → replacing with fallback",
                    )
                    answer = "Please contact the vendor / Unreserved for pricing details."
        
        except Exception as e:
            logger.exception("❌ LLM ERROR: %s", e)

            error_type = classify_llm_error(e)

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
        # ONLY include nearby properties (active listings) when user asked about "nearby properties" (for sale).
        # For "nearby SOLD" / comparable sales, keep empty - answer comes from PDF, not the active listings list.
        nearby_properties_json = []
        if location_context:
            from app.services.rag_pipeline.location_utils import detect_location_query
            is_location_query, query_type = detect_location_query(query)
            query_lower = query.lower()
            is_comparable_sold = any(
                term in query_lower for term in
                ("sold", "comparable", "recent sale", "recent sales", "properties sold")
            )
            if is_location_query and query_type == 'nearby_properties' and not is_comparable_sold:
                nearby_properties_json = location_context.get('nearby_properties_json', [])
                if nearby_properties_json:
                    logger.info(
                        "🏘️  User asked about nearby properties - including %d properties in response",
                        len(nearby_properties_json),
                    )
            else:
                logger.debug(
                    "✅ Excluding nearby_properties from response (query_type: %s, is_comparable_sold: %s)",
                    query_type,
                    is_comparable_sold,
                )

        now = time.perf_counter()
        # Merge retriever's fine-grained timers (from last retrieve call) into breakdown
        try:
            for k, v in getattr(self.augmenter.retriever, "_last_timings", {}).items():
                timings_breakdown[f"retrieval_{k}"] = round(v, 2)
        except Exception:
            pass
        # If LLM claimed no nearby properties but we actually have some, patch the answer
        # NOTE: Only do this for generic \"nearby properties\" queries – for \"nearby sold\" /
        # comparable sales questions we rely on property PDF content instead.
        try:
            query_lower = query.lower()
            if (
                nearby_properties_json
                and "nearby" in query_lower
                and not any(term in query_lower for term in ["sold", "comparable", "recent sale", "recent sales"])
            ):
                ans_lower = (ai_response.answer or "").lower()
                if "don't have information about nearby properties" in ans_lower:
                    # Build a concise deterministic summary from nearby_properties_json
                    snippets = []
                    for prop in nearby_properties_json[:3]:
                        title = prop.get("title") or prop.get("slug") or "nearby property"
                        address = prop.get("address") or ""
                        distance = prop.get("distance") or ""
                        bedrooms = prop.get("bedrooms")
                        bathrooms = prop.get("bathrooms")
                        parts = []
                        if distance:
                            parts.append(f"{distance} away")
                        if address:
                            parts.append(address)
                        if bedrooms is not None and bathrooms is not None:
                            parts.append(f"{bedrooms} bed, {bathrooms} bath")
                        snippet = " - ".join(p for p in parts if p)
                        if snippet:
                            snippets.append(f"- {title}: {snippet}")
                    if snippets:
                        intro = f"I've found {len(nearby_properties_json)} nearby properties for this location. Here are some of them:\n"
                        ai_response.answer = intro + "\n".join(snippets)
        except Exception:
            # Never let post-processing errors break the main response
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
    async def _get_listing_inspection_context(self, listing_id: str) -> str:
        """
        Fetch inspection slots for a listing from listing_inspections and format for LLM context.
        Filters out past/cancelled slots. Returns empty string if none found or on error.
        """
        try:
            from datetime import datetime, timezone, timedelta
            from app.db.postgres.repositories.listing_repository import ListingRepository
            from app.db.connection import get_session_maker
            session_maker = get_session_maker()
            async with session_maker() as db:
                repo = ListingRepository(db)
                inspections = await repo._fetch_inspections(listing_id)
            if not inspections:
                return ""

            # Display times in AEST (UTC+10). Melbourne is on AEDT in summer (UTC+11)
            # but UTC+10 is used as a safe conservative display offset.
            AEST = timezone(timedelta(hours=10))
            now_utc = datetime.now(timezone.utc)

            upcoming = []
            for insp in inspections:
                cancelled = insp.get("isCancelled") if isinstance(insp.get("isCancelled"), bool) else False
                if cancelled:
                    continue
                start_dt = insp.get("inspectionStartTime")
                # Skip slots that are already in the past
                if start_dt and hasattr(start_dt, "astimezone"):
                    if start_dt < now_utc:
                        continue
                upcoming.append(insp)

            if not upcoming:
                return "There are currently no upcoming inspection slots scheduled for this property."

            lines = [
                f"This property has {len(upcoming)} upcoming inspection slot(s), sorted nearest-first.",
                "IMPORTANT: List ALL of the following inspection slots in your response.",
                "The FIRST slot in the list is the NEXT/SOONEST upcoming inspection.\n",
            ]
            for i, insp in enumerate(upcoming, 1):
                insp_type = (insp.get("inspectionType") or "open").replace("_", " ").title()
                start_dt = insp.get("inspectionStartTime")
                end_dt = insp.get("inspectionEndTime")

                if start_dt and hasattr(start_dt, "astimezone"):
                    start_local = start_dt.astimezone(AEST)
                    end_local = end_dt.astimezone(AEST) if end_dt and hasattr(end_dt, "astimezone") else None
                    date_str = start_local.strftime("%-d %B %Y")
                    start_str = start_local.strftime("%-I:%M %p")
                    end_str = end_local.strftime("%-I:%M %p") if end_local else ""
                    time_range = f"{start_str} – {end_str} AEST" if end_str else start_str
                else:
                    date_str = str(insp.get("inspectionDate") or "")
                    time_range = f"{start_dt} – {end_dt}"

                next_label = " ← NEXT/SOONEST" if i == 1 else ""
                lines.append(f"  {i}. {insp_type} Inspection — {date_str}, {time_range}{next_label}")

            return "\n".join(lines)
        except Exception as e:
            logger.warning("Failed to fetch inspection slots for listing %s: %s", listing_id, e)
            return ""

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

    async def _extract_school_lines_from_context(self, context: str) -> List[str]:
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

    async def _generate_conversational_reply(
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

    async def _classify_intent_listing_vs_conversational(
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

    async def _generate_personal_advice_message(self, query: str) -> str:
        return (
            "I cannot provide personal advice, recommendations, or suggestions about whether to buy, "
            "purchase, invest in, or make offers on properties. These decisions require assessment by "
            "qualified professionals such as lawyers, financial advisors, or licensed real estate agents.\n\n"
            "I can help with factual details about the property instead, such as specifications, "
            "pricing information, location details, and property features."
        )

    def _build_llm_messages(
        self,
        query: str,
        context: str,
        query_source: str,
        enquiry_type: str,
        is_enquiry_message: bool,
        conversation_history: Optional[List[Dict[str, str]]],
        has_amenity_links_flag: bool,
        pre_generated_amenity_links: List[Any],
    ) -> List[Dict[str, str]]:
        """Build system + user messages for the LLM from context and query."""
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
        messages = [{"role": "system", "content": system_prompt}]
        messages.append({"role": "user", "content": user_prompt})
        return messages

    async def _generate_vendor_contact_message(
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

    async def _classify_amenity_with_llm(
        self,
        query: str,
        context: str,
    ) -> Dict[str, Any]:
        """
        LLM fallback for amenity query classification when keyword matching fails.

        Returns a dict with:
          - is_amenity (bool): True if the query is asking about a nearby place/service
          - amenity_terms (List[str]): 1-3 short search terms suitable for Google Maps
          - found_in_context (bool): True if any amenity term appears in the property context

        Only fires when the fast keyword-based check already returned False, so this
        is purposely lightweight: low max_tokens, deterministic (temperature=0), JSON only.
        """
        import json as _json

        system_msg = (
            "You are a strict classifier. Decide whether a real estate buyer's question "
            "is asking about a **nearby amenity** — a physical place or service they can "
            "visit in the neighbourhood (e.g. school, gym, cafe, park, hospital, train station).\n\n"
            "Rules:\n"
            "- Classify as amenity ONLY if the user wants to find a nearby place to visit.\n"
            "- Do NOT classify property features that are part of the property itself "
            "(e.g. parking space, built-in pool, garden, garage) as amenities.\n"
            "- Do NOT classify specs, dimensions, prices, bedrooms, legal/regulatory questions.\n"
            "- amenity_terms must be 1–3 short search words suitable for a Google Maps search "
            "(e.g. ['gym', 'fitness centre'] or ['primary school']). Return [] if not an amenity.\n\n"
            "Respond with valid JSON only, no markdown:\n"
            '{"is_amenity": true/false, "amenity_terms": ["term1", "term2"]}'
        )

        user_msg = (
            f'Buyer question: "{query}"\n\n'
            f"Property context excerpt (first 600 chars):\n{context[:600]}"
        )

        try:
            response = create_chat_completion(
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                model=self.model_config["model"],
                temperature=0,
                max_tokens=80,
            )
            raw = (response.choices[0].message.content or "").strip()
            # Strip markdown code fences if present
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
            result = _json.loads(raw)
        except Exception as e:
            logger.debug("_classify_amenity_with_llm failed: %s", e)
            return {"is_amenity": False, "amenity_terms": [], "found_in_context": False}

        is_amenity = bool(result.get("is_amenity", False))
        amenity_terms: List[str] = [
            t.strip().lower()
            for t in result.get("amenity_terms", [])
            if isinstance(t, str) and t.strip()
        ]

        # Verify at least one term is mentioned in the property context so we don't
        # generate Maps links for amenities the property data never references.
        context_lower = context.lower()
        found_in_context = any(
            re.search(r"\b" + re.escape(term) + r"\b", context_lower)
            for term in amenity_terms
        )

        logger.info(
            "🗺️  LLM amenity classifier → is_amenity=%s, terms=%s, found_in_context=%s",
            is_amenity,
            amenity_terms,
            found_in_context,
        )

        return {
            "is_amenity": is_amenity,
            "amenity_terms": amenity_terms,
            "found_in_context": found_in_context,
        }
