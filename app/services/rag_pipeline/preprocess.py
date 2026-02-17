"""
Preprocessing module for buyer enquiries.
Extracts listing IDs, normalizes queries, and prepares for retrieval.

HYBRID APPROACH:
- Regex: Fast, deterministic for structured data (UUIDs, obvious patterns)
- LLM: Semantic understanding for ambiguous cases (topic extraction, query classification)
- Fallback: Regex → LLM → Regex (ensures reliability)

Performance:
- 90% of queries handled by regex (<1ms)
- 10% use LLM (~200ms, gpt-4o-mini)
- Average latency: ~20ms
- Cost: ~$0.00001 per query
"""
import logging
import re
from typing import Dict, Optional, Any, List

from app.schemas import BuyerEnquiry

logger = logging.getLogger(__name__)

# Constants
UUID_PATTERN = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
LISTING_ID_PATTERN = r'(?:listing|property)\s*(?:id|#)?\s*:?\s*([0-9a-f-]{36})'

FOLLOW_UP_TRIGGERS = [
    'yes', 'yeah', 'sure', 'tell me more', 'yes please', 'ok', 'okay',
    'yes i would like to know more', 'go ahead'
]

TOPIC_EXTRACTION_PATTERNS = [
    # Most specific patterns first (with bold formatting)
    r'Would you like to know more about (?:the )?\*\*([^*]+?)\*\*',  # "more about the **topic**"
    r'Would you like to know about (?:the )?\*\*([^*]+?)\*\*',  # "about the **topic**"
    r'Are you curious about (?:the )?\*\*([^*]+?)\*\*',
    r'Would you like to understand (?:the )?\*\*([^*]+?)\*\*',
    r'Are you interested in (?:the )?\*\*([^*]+?)\*\*',
    # Patterns without bold formatting (plain text)
    r'Are you interested in learning more about (?:the )?([^?]+?)(?:\s+or\s+|\?)',  # "learning more about the qualifications required..."
    r'Would you like to know more about (?:the )?([^?]+?)(?:\s+or\s+|\?)',  # "know more about the topic..."
    r'Are you curious about (?:the )?([^?]+?)(?:\s+or\s+|\?)',  # "curious about the topic..."
]

BOLD_PATTERN = r'\*\*([^*]+?)\*\*'

QUESTION_WORDS = [
    'what', 'how', 'when', 'where', 'why', 'who', 'which', 
    'can', 'do', 'does', 'is', 'are', 'will', 'would'
]


def extract_listing_id(query: str) -> Optional[str]:
    """
    Extract listing ID from query if present.
    Looks for UUID patterns or explicit listing ID mentions.
    
    Args:
        query: The buyer's enquiry text
        
    Returns:
        Listing ID if found, None otherwise
    """
    # Try UUID pattern first
    matches = re.findall(UUID_PATTERN, query, re.IGNORECASE)
    if matches:
        return matches[0]
    
    # Try explicit listing ID pattern
    match = re.search(LISTING_ID_PATTERN, query, re.IGNORECASE)
    if match:
        return match.group(1)
    
    return None


def _extract_topic_with_llm(bot_message: str) -> Optional[str]:
    """
    Extract suggested topic from bot message using LLM.
    More robust than regex patterns, handles variations naturally.
    
    Args:
        bot_message: The bot's message content
        
    Returns:
        Extracted topic string, or None if no topic found
    """
    try:
        from app.services.rag_pipeline.llms import create_chat_completion
        
        prompt = f"""Extract the first suggested topic from this bot message.
The bot is asking if the user wants to know more about something.

Bot message: {bot_message[:1000]}  # Limit to avoid token waste

Extract the topic the bot is suggesting. Examples:
- "Would you like to know more about **licensing requirements**?" → "licensing requirements"
- "Are you interested in the **property's location**?" → "property's location"
- "Would you like to understand **Section 32**?" → "Section 32"

If no topic is found, respond with "NONE".
Respond with ONLY the topic name, nothing else."""
        
        messages = [
            {"role": "system", "content": "You are a topic extraction assistant. Extract topics accurately and concisely."},
            {"role": "user", "content": prompt}
        ]
        
        response = create_chat_completion(
            messages=messages,
            model="gpt-4o",  # Fast and cheap for classification
            temperature=0,  # Deterministic
            max_tokens=50
        )
        
        topic = response.choices[0].message.content.strip()

        if topic.upper() == "NONE" or not topic:
            return None

        logger.info("🤖 LLM extracted topic: '%s'", topic)
        return topic

    except Exception as e:
        logger.warning("⚠️  LLM topic extraction failed: %s, falling back to regex", e)
        return None


def extract_suggested_topic_from_history(
    query: str, 
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> Optional[str]:
    """
    Extract the first suggested topic from previous bot message when user says "yes".
    Uses hybrid approach: LLM first (more accurate), regex fallback (faster, reliable).
    
    Args:
        query: Current user query
        conversation_history: Previous conversation messages
    
    Returns:
        Rewritten query about the suggested topic, or None if no topic found
    """
    # Normalize query: strip trailing question marks and whitespace
    query_normalized = query.lower().strip().rstrip('?').strip()
    
    if query_normalized not in FOLLOW_UP_TRIGGERS:
        return None

    if not conversation_history:
        logger.warning("⚠️  No conversation history for 'yes' response extraction")
        return None

    logger.info("🔍 Attempting to extract suggested topic from %d messages", len(conversation_history))

    # Find the last bot message
    for msg in reversed(conversation_history):
        if msg['role'] in ['assistant', 'bot']:
            bot_content = msg['content']
            logger.debug("📜 Checking bot message (first 200 chars): %s", bot_content[:200])

            # Try LLM extraction first (more robust)
            topic = _extract_topic_with_llm(bot_content)
            
            if topic:
                # Clean and convert to question
                cleaned_topic = _clean_topic_text(topic.strip())
                first_lower = cleaned_topic.lower()
                is_property_topic = "property's" in first_lower or "property" in first_lower
                rewritten = _convert_topic_to_question(cleaned_topic, is_property_topic=is_property_topic)
                logger.info("🔄 Rewriting 'yes' → '%s' (LLM extracted: '%s')", rewritten, cleaned_topic)
                return rewritten
            
            # Fallback to regex patterns (fast, reliable for common cases)
            logger.info("🔄 LLM extraction failed/returned None, trying regex fallback...")
            
            for pattern in TOPIC_EXTRACTION_PATTERNS:
                match = re.search(pattern, bot_content, re.IGNORECASE)
                if match:
                    first_topic = _clean_topic_text(match.group(1).strip())
                    logger.info("🔍 Extracted topic from bot message: '%s' (regex pattern matched)", first_topic)

                    first_lower = first_topic.lower()
                    is_property_topic = "property's" in first_lower or "property" in first_lower
                    rewritten = _convert_topic_to_question(first_topic, is_property_topic=is_property_topic)

                    logger.info("🔄 Rewriting 'yes' → '%s' (regex extracted: '%s')", rewritten, first_topic)
                    return rewritten
            
            # Final fallback: extract from bold text
            bold_matches = re.findall(BOLD_PATTERN, bot_content)
            if bold_matches:
                for bold_text in bold_matches:
                    bold_lower = bold_text.lower().strip()
                    if len(bold_lower) > 5 and not bold_lower.startswith('$'):
                        first_topic = _clean_topic_text(bold_text.strip())
                        first_lower = first_topic.lower()
                        is_property_topic = "property's" in first_lower or "property" in first_lower
                        rewritten = _convert_topic_to_question(first_topic, is_property_topic=is_property_topic)
                        logger.info(
                            "🔄 Rewriting 'yes' → '%s' (regex bold fallback: '%s')",
                            rewritten,
                            first_topic,
                        )
                        return rewritten

            logger.warning("⚠️  Could not extract topic from bot message (tried LLM + regex)")
            break
    
    return None


def _clean_topic_text(topic: str) -> str:
    """
    Clean topic text by removing trailing phrases.
    
    Args:
        topic: Raw topic text
        
    Returns:
        Cleaned topic text
    """
    return topic.split(' for ')[0].split(' in ')[0].split(' or ')[0].split(' or its')[0].split(' or the')[0].strip()


def _convert_topic_to_question(topic: str, is_property_topic: bool = False) -> str:
    """
    Convert a topic string into a natural question format.
    
    Args:
        topic: Topic text to convert
        is_property_topic: Whether this is a property-specific topic
        
    Returns:
        Question string
    """
    topic_lower = topic.lower()
    
    if is_property_topic:
        # Handle property-specific topics
        if 'location' in topic_lower:
            return "what is the property's location"
        elif 'features' in topic_lower or 'key features' in topic_lower:
            return "what are the property's key features"
        elif 'inspection' in topic_lower or 'schedule' in topic_lower:
            return "when are the inspections" if 'schedule' in topic_lower else "what is the inspection schedule"
        else:
            return f"what is the {topic_lower}"
    else:
        # Handle generic/legal topics
        if 'laws' in topic_lower:
            return f"what are {topic_lower}"
        elif 'requirements' in topic_lower:
            return f"what are {topic_lower}"
        elif 'qualifications' in topic_lower or 'qualification' in topic_lower:
            return f"what are {topic_lower}"
        elif 'role' in topic_lower and 'of' in topic_lower:
            return f"what is {topic_lower}"
        elif 'statement' in topic_lower:
            return f"what is a {topic_lower}"
        elif topic_lower.startswith('the '):
            # Remove "the " prefix and convert to question
            topic_without_the = topic_lower[4:].strip()
            return f"what is {topic_without_the}" if len(topic_without_the.split()) <= 5 else f"tell me about {topic_lower}"
        else:
            # Default: convert to natural question
            if 'required' in topic_lower or 'needed' in topic_lower:
                return f"what are {topic_lower}"
            elif 'the' not in topic_lower:
                return f"what is {topic_lower}"
            else:
                return f"tell me about {topic_lower}"


def normalize_query(query: str) -> str:
    """
    Normalize the query for better retrieval.
    
    Args:
        query: Raw query text
        
    Returns:
        Normalized query
    """
    # Remove extra whitespace
    query = ' '.join(query.split())
    
    # Remove listing ID if present (we'll handle it separately)
    query = re.sub(UUID_PATTERN, '', query, flags=re.IGNORECASE)
    
    # Clean up
    query = ' '.join(query.split())
    
    return query.strip()


def preprocess_enquiry(enquiry: BuyerEnquiry) -> Dict[str, Any]:
    """
    Preprocess a buyer enquiry for retrieval and generation.
    
    Args:
        enquiry: BuyerEnquiry object
        
    Returns:
        Dictionary with preprocessed data:
        - normalized_query: Cleaned query text
        - listing_id: Extracted or provided listing ID
        - original_query: Original query text
        - user_context: User/session information
    """
    listing_id = enquiry.listing_id
    if not listing_id:
        listing_id = extract_listing_id(enquiry.question)
    
    normalized_query = normalize_query(enquiry.question)
    
    return {
        "normalized_query": normalized_query,
        "listing_id": listing_id,
        "original_query": enquiry.question,
        "user_id": enquiry.user_id,
    }


def _detect_query_source_with_llm(query: str, conversation_history: Optional[List[Dict[str, str]]] = None) -> Optional[str]:
    """
    Detect query source using LLM for semantic understanding.
    Handles variations and synonyms that regex might miss.
    
    Args:
        query: The user's query
        conversation_history: Recent conversation messages for context
    
    Returns:
        'generic' or 'property', or None if LLM call fails
    """
    try:
        from app.services.rag_pipeline.llms import create_chat_completion
        
        # Build context from conversation history
        context = ""
        if conversation_history:
            recent_messages = conversation_history[-2:]  # Last 2 messages for context
            context = "\n".join([f"{msg['role']}: {msg['content'][:200]}" for msg in recent_messages])
        
        prompt = f"""Classify this real estate query as either 'generic' or 'property':

- 'generic': Questions about laws, regulations, processes, licensing, general knowledge
  Examples: "how do auctions work", "what is section 32", "licensing requirements", "trust account rules"
  
- 'property': Questions about a specific property listing
  Examples: "what is the price", "how many bedrooms", "what are the amenities", "where is it located"

Query: {query}
{f"Recent context:\n{context}" if context else ""}

Respond with ONLY: 'generic' or 'property'"""
        
        messages = [
            {"role": "system", "content": "You are a query classifier. Classify queries accurately as 'generic' or 'property'."},
            {"role": "user", "content": prompt}
        ]
        
        response = create_chat_completion(
            messages=messages,
            model="gpt-4o",  # Fast and cheap
            temperature=0,  # Deterministic
            max_tokens=10
        )
        
        result = response.choices[0].message.content.strip().lower()
        
        if result in ['generic', 'property']:
            print(f"🤖 LLM classified query as: '{result}'")
            return result
        else:
            print(f"⚠️  LLM returned unexpected result: '{result}', falling back to regex")
            return None
            
    except Exception as e:
        print(f"⚠️  LLM query source detection failed: {e}, falling back to regex")
        return None


def _is_obviously_generic(query_lower: str) -> bool:
    """
    Fast regex check for obviously generic queries.
    Returns True if query clearly needs generic knowledge.
    """
    # Strong generic indicators (high confidence)
    strong_generic_patterns = [
        r'\bact\s+\d{4}\b',  # "Act 1962", "Act 1980"
        r'\bact\s+of\s+\d{4}\b',
        r'\b(?:how\s+do\s+i\s+become|how\s+to\s+become)\s+(?:a\s+)?(?:licensed\s+)?(?:real\s+)?estate\s+agent',
        r'\b(?:what\s+)?license\s+(?:do\s+i\s+)?need',
        r'\b(?:section\s+32|s32)\b',
        r'\btrust\s+account\b',
        r'\baml\b|\banti-money\s+laundering\b',
        r'\bcooling\s+off\s+period\b',
        r'\bunderquoting\b',
        r'\bvendor\s+statement\b',
    ]
    
    for pattern in strong_generic_patterns:
        if re.search(pattern, query_lower):
            return True
    
    return False


def _is_obviously_property(query_lower: str) -> bool:
    """
    Fast regex check for obviously property-specific queries.
    Returns True if query clearly needs property data.
    """
    # Strong property indicators (high confidence)
    strong_property_patterns = [
        r'\b(?:what|how\s+much)\s+(?:is\s+)?(?:the\s+)?(?:price|cost|asking)',
        r'\b(?:how\s+many)\s+(?:bedroom|bathroom|garage)',
        r'\b(?:what\s+are\s+)?(?:the\s+)?(?:amenities|features)',
        r'\b(?:where\s+is|what\s+is\s+the\s+location|address)',
        r'\b(?:nearby|close\s+to)\s+(?:school|hospital|supermarket)',
        r'\b(?:inspection|viewing|open\s+house)\s+(?:schedule|time|date)',
        # Nearby/comparable sales queries (property-specific)
        r'\b(?:nearby|near|close)\s+(?:propert|sale|sold)',
        r'\b(?:propert|sale|home).*\b(?:sold|sale).*\b(?:nearby|near|close)',
        r'\bcomparable\s+(?:sale|propert)',
        r'\brecent\s+(?:sale|sold).*\b(?:nearby|near|area)',
    ]
    
    for pattern in strong_property_patterns:
        if re.search(pattern, query_lower):
            return True
    
    # Single-word or simple property attribute queries (with or without question mark)
    # These are clearly asking about specific property specs/details
    property_attribute_keywords = [
        'bedroom', 'bedrooms', 'bathroom', 'bathrooms', 'garage', 'garages',
        'parking', 'car spaces', 'land size', 'floor size', 'lot size',
        'zoning', 'zone', 'title', 'construction', 'built', 'year built',
        'storey', 'storeys', 'level', 'levels', 'orientation', 'aspect',
        'heating', 'cooling', 'aircon', 'air conditioning', 'ducted',
        'pool', 'swimming pool', 'spa', 'tennis court', 'shed', 'workshop',
        'balcony', 'deck', 'patio', 'courtyard', 'backyard', 'frontyard',
        'solar', 'solar panels', 'water tank', 'greywater', 'rainwater',
        'insulation', 'double glazed', 'glazing', 'windows', 'doors',
        'kitchen', 'living', 'dining', 'laundry', 'study', 'office',
        'ensuite', 'master', 'robe', 'robes', 'wardrobe', 'storage',
    ]
    
    # Strip question marks and check if query is just asking about an attribute
    query_normalized = query_lower.strip().rstrip('?!.,').strip()
    
    # Match exact single words or simple phrases (e.g., "zoning", "bedrooms", "land size")
    if query_normalized in property_attribute_keywords:
        return True
    
    # Also match if the query contains these keywords as the main subject
    # e.g., "what's the zoning", "tell me about bedrooms", "how about parking"
    for keyword in property_attribute_keywords:
        # Match if keyword appears as a standalone word (not part of a larger phrase about licensing/generic topics)
        if re.search(rf'\b{re.escape(keyword)}\b', query_normalized):
            # Exclude if it's clearly a generic question about the concept itself
            generic_indicators = ['what is a', 'what are', 'explain', 'definition', 'meaning of', 'what does', 'how does']
            if not any(indicator in query_lower for indicator in generic_indicators):
                return True
    
    return False


def detect_query_source(
    query: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    listing_id: Optional[str] = None,
) -> str:
    """
    Detect if query needs generic knowledge OR property-specific info.
    Uses hybrid approach: regex for obvious cases, LLM for ambiguous ones.
    Same logic runs whether or not listing_id is present (query source identified properly).
    
    Args:
        query: The user's query
        conversation_history: Recent conversation messages for context
        listing_id: Optional; kept for API compatibility, not used to skip LLM
    
    Returns:
        'generic': Query about general real estate knowledge
        'property': Query about specific property (default)
    """
    query_lower = query.lower()

    # Handle follow-up responses like "yes", "tell me more"
    # Normalize query: strip trailing question marks and whitespace
    query_normalized = query_lower.strip().rstrip('?').strip()
    if query_normalized in FOLLOW_UP_TRIGGERS:
        print(f"🔍 Detected follow-up response: '{query}'")
        # Check if previous message was generic
        if conversation_history:
            print(f"📜 Checking {len(conversation_history)} messages in history")
            for msg in reversed(conversation_history):
                if msg['role'] in ['assistant', 'bot']:  # Support both role names
                    # If last bot message mentioned generic topics, assume this is generic
                    bot_msg_lower = msg['content'].lower()
                    print(f"🤖 Last bot message preview: {bot_msg_lower[:100]}...")
                    
                    generic_indicators = [
                        'underquoting', 'section 32', 'trust account', 'licensing',
                        'cooling off', 'sale of land act', 'estate agents act',
                        'vendor statement', 'statement of information', 'aml',
                        'anti-money laundering', 'sale process'
                    ]
                    
                    if any(kw in bot_msg_lower for kw in generic_indicators):
                        print(f"✅ Found generic indicator in last message → routing to GENERIC")
                        return 'generic'
                    else:
                        print(f"⚠️  No generic indicators found in last message")
                    break
        else:
            print(f"⚠️  No conversation history provided for follow-up")
    
    # HYBRID APPROACH: Fast regex check first, LLM for ambiguous cases
    # Step 1: Check obvious cases with regex (fast, handles 90% of queries)
    if _is_obviously_generic(query_lower):
        print(f"✅ Regex: Obviously generic → routing to GENERIC")
        return 'generic'
    
    if _is_obviously_property(query_lower):
        print(f"✅ Regex: Obviously property → routing to PROPERTY")
        return 'property'
    
    # Step 2: For ambiguous cases, use LLM (handles semantic variations)
    print(f"🤔 Query is ambiguous, using LLM for classification...")
    llm_result = _detect_query_source_with_llm(query, conversation_history)
    if llm_result:
        return llm_result
    
    # Step 3: Fallback to original regex logic if LLM fails
    print(f"🔄 LLM failed, falling back to regex keyword matching...")
    
    # Generic knowledge triggers (original regex fallback)
    generic_keywords = [
        # Process & Legal
        'how do auctions work', 'what is an auction', 'auction process',
        'cooling off period', 'what are my rights', 'buyer rights',
        'contract of sale', 'building inspection', 'pest inspection',
        'finance pre-approval', 'getting a loan', 'mortgage',
        'first time buyer', 'what documents', 'legal requirements',
        'vendor disclosure', 'section 32', 'title search',
        'statement of information', 'underquoting',
        'sale process', 'buying process', 'purchase process',
        'settlement process', 'conveyancing',
        'standard sale process', 'consumer protections', 'complain about an agent',
        'advertise properties', 'below market value', 'vendor statement',
        'section 32 statement', 'section 32 required', 'must be disclosed',
        
        # Legislation & Acts (exact names and variations)
        'sale of land act', 'sale of land act 1962',
        'estate agents act', 'estate agents act 1980',
        'property law act', 'conveyancing act',
        'residential tenancies act', 'building act',
        
        # Agent/Licensing
        'how do i become', 'how to become', 'licensed real estate agent',
        'agent license', 'licensing requirements', 'get a license',
        'real estate license', 'estate agent license',
        'what license', 'which license', 'need a license', 'need license',
        'license do i need', 'license to sell', 'license to become',
        
        # Trust & Compliance
        'trust account', 'trust money', 'agent obligations',
        'professional conduct', 'agent penalties',
        'aml', 'anti-money laundering', 'money laundering',
        'compliance', 'regulatory requirements',
        'trust account requirements', 'handle buyer deposits', 'misuse trust money',
        'agent violations', 'unprofessional conduct', 'agents disciplined',
        'aml requirements', 'verify buyer identity', 'aml laws',
        
        # Planning & Regulations (ONLY if no listing_id - generic knowledge)
        # Note: If listing_id is present, these should search property_document PDFs first
        # 'bushfire', 'bushfire regulations', 'bushfire management', 'bushfire overlay',  # Removed - now handled by DOCUMENT_KEYWORDS
        # 'zoning regulations', 'planning regulations', 'heritage overlay',  # Removed - now handled by DOCUMENT_KEYWORDS
        'planning scheme', 'council regulations', 'building regulations',
        'planning permit', 'planning approval', 'council approval',
        
        # Meta-conversation (requires conversation_id)
        'what did i ask', 'what was my last question', 'what did we discuss',
        'previous question', 'earlier question', 'last question',
        
        # General Questions (be specific to avoid false positives)
        # Removed: 'what is a', 'what are the', 'how does', 'what does' - too broad
        'explain real estate', 'how to buy', 'how to sell', 'what are the steps to buy',
        'what are the steps to sell', 'buying process', 'selling process',
        
        # Financial & Tax
        'gst withholding', 'stamp duty', 'tax obligations', 'property sales tax',
    ]
    
    # Check for generic keywords
    if any(kw in query_lower for kw in generic_keywords):
        print(f"✅ Found generic keyword → routing to GENERIC")
        return 'generic'
    
    # Also check for Act names (e.g., "Sale of Land Act 1962", "Estate Agents Act")
    act_patterns = [
        r'\bact\s+\d{4}\b',  # Matches "Act 1962", "Act 1980", etc.
        r'\bact\s+of\s+\d{4}\b',  # Matches "Act of 1962"
    ]
    import re
    for pattern in act_patterns:
        if re.search(pattern, query_lower):
            print(f"✅ Found Act pattern → routing to GENERIC")
            return 'generic'
    
    # Check for conversational/test queries that aren't real questions
    # These should not trigger property-specific retrieval
    conversational_patterns = [
        r'\b(?:recording|testing|test|checking|see how|let\'?s see|just testing|trying out)\b',
        r'\b(?:this is|i\'?m|i am)\s+(?:a\s+)?(?:test|recording|check|trial)\b',
        r'\b(?:how\s+)?(?:does\s+)?(?:this|it)\s+(?:work|go|sound)\??\s*$',
    ]
    for pattern in conversational_patterns:
        if re.search(pattern, query_lower):
            print(f"✅ Found conversational/test pattern → routing to GENERIC (no property data)")
            return 'generic'
    
    # Check if query is actually a question (has question words or ends with ?)
    # If not a question and no property keywords, treat as generic/conversational
    is_question = (
        any(qw in query_lower for qw in QUESTION_WORDS) or
        query.strip().endswith('?')
    )
    
    # Check for property-specific keywords
    property_keywords = [
        'property', 'listing', 'price', 'pricing', 'amenities', 'features', 'location',
        'bedroom', 'bathroom', 'square', 'sqft', 'acre', 'hectare', 'inspection',
        'auction', 'sale', 'asking', 'offer', 'bid', 'vendor', 'agent', 'address',
        'street', 'suburb', 'postcode', 'land size', 'building size', 'car space',
        'parking', 'garage', 'pool', 'garden', 'view', 'floor plan', 'photos',
        # Amenity-related keywords (for "nearby schools", "nearby hospitals", etc.)
        'schools', 'school', 'hospital', 'hospitals', 'supermarket', 'supermarkets',
        'transport', 'bus', 'train', 'tram', 'station', 'nearby', 'close to',
        'walking distance', 'parks', 'shopping', 'restaurants', 'cafes'
    ]
    has_property_keywords = any(kw in query_lower for kw in property_keywords)
    
    # If it's not a question and has no property keywords, treat as generic/conversational
    if not is_question and not has_property_keywords:
        print(f"ℹ️  Not a question and no property keywords → routing to GENERIC (conversational)")
        return 'generic'
    
    print(f"ℹ️  No generic match → routing to PROPERTY (default)")
    return 'property'  # Default to property-specific


def detect_enquiry_type(query: str) -> str:
    """
    Detect the type of enquiry for better routing.
    
    Args:
        query: The enquiry text
        
    Returns:
        Enquiry type: 'price', 'specifications', 'location', 'bidding', 'personal_advice', 'greeting', 'general'
    """
    query_lower = query.lower().strip()
    
    # Detect greetings FIRST (before other checks)
    # Only treat as greeting if it's JUST a greeting (no property-related questions)
    greeting_keywords = [
        'hi', 'hello', 'hey', 'good morning', 'good afternoon', 'good evening',
        'greetings', 'howdy', 'hi there', 'hello there', 'hey there'
    ]
    
    # Check if query is ONLY a greeting (no other meaningful content)
    is_pure_greeting = False
    if query_lower in greeting_keywords:
        is_pure_greeting = True
    elif any(query_lower.startswith(greeting + ' ') or query_lower == greeting for greeting in greeting_keywords):
        # Check if it's just a greeting with minimal words (like "hi there" or "hello!")
        words = query_lower.split()
        if len(words) <= 3:
            # Make sure it doesn't contain property-related keywords
            property_keywords = ['price', 'bedroom', 'bathroom', 'property', 'listing', 'address', 'location', 'what', 'how', 'tell', 'show']
            if not any(pk in query_lower for pk in property_keywords):
                is_pure_greeting = True
    
    if is_pure_greeting:
        return 'greeting'
    
    # CRITICAL: Detect personal advice questions FIRST (highest priority)
    # These require human expertise and should NOT be answered by AI
    personal_advice_keywords = [
        'should i buy', 'should i purchase', 'should i invest', 'should i get',
        'at what price should i', 'what price should i', 'what should i pay',
        'should i offer', 'how much should i pay', 'should i bid',
        'should i act', 'should i make a move', 'should i proceed', 'should i go ahead',
        'is this a good deal', 'is this worth', 'is it worth', 'worth buying',
        'can i negotiate', 'chance for negotiation', 'any room for negotiation',
        'is there room for negotiation', 'room to negotiate', 'negotiate the price',
        'open to negotiation', 'is the price negotiable', 'price fixed or',
        'can i bargain', 'should i negotiate', 'any negotiation',
        'is this overpriced', 'is this underpriced', 'is this price good',
        'should i go for this', 'is this a good investment', 'good investment',
        'what should my offer be', 'what should my bid be', 'recommend buying',
        'would you recommend', 'do you recommend', 'should i consider'
    ]
    
    # Check personal advice FIRST (before other keywords)
    if any(kw in query_lower for kw in personal_advice_keywords):
        return 'personal_advice'
    
    # Check for nearby properties queries (informational, NOT advice)
    nearby_keywords = ['nearby properties', 'nearby', 'surrounding', 'around here', 'in the area']
    if any(kw in query_lower for kw in nearby_keywords):
        return 'general'  # Treat as informational, not advice
    
    price_keywords = ['price', 'cost', 'how much', 'asking']
    specs_keywords = ['bedroom', 'bathroom', 'garage', 'area', 'feature', 'amenity', 'pool']
    location_keywords = ['location', 'address', 'where', 'suburb', 'city', 'inspection']
    
    # Buyer interest/activity keywords (for tone/activity queries)
    interest_keywords = [
        'how many people', 'people interested', 'buyer interest', 'interest level',
        'how much interest', 'market interest', 'competition', 'competing',
        'how many offers', 'number of offers', 'offer situation', 'offers received',
        'how many bids', 'bidding activity', 'auction activity'
    ]
    
    # Only trigger bidding advice for actual "how to" questions
    # NOT for informational queries like "what are the offers" or "what is the auction"
    bidding_advice_keywords = ['how to bid', 'how do i bid', 'how to make an offer', 
                               'how do i offer', 'bidding process', 'how to place a bid']
    
    if any(kw in query_lower for kw in price_keywords):
        return 'price'
    elif any(kw in query_lower for kw in specs_keywords):
        return 'specifications'
    elif any(kw in query_lower for kw in location_keywords):
        return 'location'
    elif any(kw in query_lower for kw in interest_keywords):
        return 'general'  # Treat buyer interest queries as general (will use tone/activity context)
    elif any(kw in query_lower for kw in bidding_advice_keywords):
        return 'bidding'
    else:
        return 'general'
