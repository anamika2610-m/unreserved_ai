"""
Postprocessing module for AI responses.
Handles response formatting, validation, content safety filtering, and final output preparation.
"""
import re
from typing import Dict, Any, Tuple, List
from app.schemas import AIResponse, PropertyListingResponse


def format_response_for_api(
    ai_response: AIResponse,
    property_listing: Any = None,
    log_entry: Any = None
) -> Dict[str, Any]:
    """
    Format the response for API output.
    Automatically sanitizes content for safety.
    
    Args:
        ai_response: AIResponse object (will be sanitized)
        property_listing: Optional PropertyListing object
        log_entry: Optional EnquiryLog object
        
    Returns:
        Dictionary formatted for API response
    """
    # Ensure response is sanitized before formatting
    ai_response = sanitize_response(ai_response)
    
    response = {
        "answer": ai_response.answer,
        "needs_vendor_contact": ai_response.needs_vendor_contact,
        "escalation_reason": ai_response.escalation_reason,
        "data_sources": [
            {
                "chunk_type": ds.chunk_type,
                "listing_id": ds.listing_id,
                "content_preview": ds.content_preview,
                "similarity_score": ds.similarity_score
            }
            for ds in ai_response.data_sources
        ],
        "disclaimer": ai_response.disclaimer
    }
    
    if property_listing:
        response["property_listing"] = {
            "id": property_listing.id,
            "title": property_listing.title,
            "location": property_listing.location,
            "property_type": property_listing.property_type
        }
    
    if log_entry:
        response["log_id"] = log_entry.id
        response["timestamp"] = log_entry.timestamp.isoformat()
    
    return response


def validate_response(ai_response: AIResponse) -> Tuple[bool, str]:
    """
    Validate that the AI response meets requirements.
    Also checks content safety.
    
    Args:
        ai_response: AIResponse object to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check that answer is not empty
    if not ai_response.answer or not ai_response.answer.strip():
        return False, "Response answer is empty"
    
    # Check content safety
    is_safe, detected_issues = check_content_safety(ai_response.answer)
    if not is_safe:
        return False, f"Response contains harmful content: {', '.join(detected_issues)}"
    
    # Check that disclaimer is included (only if disclaimer is set)
    if ai_response.disclaimer:
        disclaimer_lower = ai_response.disclaimer.lower()
        answer_lower = ai_response.answer.lower()
        if disclaimer_lower not in answer_lower:
            return False, "Disclaimer not found in response"
        
    # Check that data sources are logged
    if not ai_response.data_sources:
        # This is a warning, not an error - some queries might not need sources
        pass
    
    return True, ""


# Content safety patterns - comprehensive list of harmful content indicators
HARMFUL_CONTENT_PATTERNS = {
    'suicidal': [
        r'\b(kill\s+myself|end\s+my\s+life|commit\s+suicide|take\s+my\s+life|self\s+harm|harm\s+myself)\b',
        r'\b(suicide|suicidal|ending\s+it\s+all|no\s+point\s+living)\b',
    ],
    'self_harm': [
        r'\b(cut\s+myself|self\s+injury|self\s+harm|hurt\s+myself|harm\s+myself)\b',
        r'\b(burn\s+myself|self\s+destruct)\b',
    ],
    'abusive': [
        r'\b(you\s+are\s+stupid|you\s+are\s+idiot|you\s+are\s+dumb|fuck\s+you|go\s+to\s+hell)\b',
        r'\b(hate\s+you|despise\s+you|worthless|useless)\b',
    ],
    'racist': [
        r'\b(racial\s+slur|n[-\s]?word|chink|spic|kike|towel\s+head)\b',
        r'\b(race\s+superior|inferior\s+race|racial\s+supremacy)\b',
    ],
    'sexist': [
        r'\b(women\s+are\s+inferior|men\s+are\s+superior|sexist\s+slur)\b',
        r'\b(gender\s+discrimination|misogynist|misandrist)\b',
    ],
    'violent': [
        r'\b(kill\s+you|hurt\s+you|attack\s+you|violence\s+against)\b',
        r'\b(threat|threaten|harm\s+you|assault)\b',
    ],
    'inappropriate': [
        r'\b(explicit\s+sexual|pornographic|obscene\s+content)\b',
        r'\b(illegal\s+activities|drug\s+dealing|weapons\s+trade)\b',
    ]
}


def check_content_safety(content: str) -> Tuple[bool, List[str]]:
    """
    Check if content contains harmful, inappropriate, or unsafe material.
    
    Args:
        content: The text content to check
        
    Returns:
        Tuple of (is_safe, detected_issues)
        - is_safe: True if content is safe, False if harmful content detected
        - detected_issues: List of issue categories found
    """
    content_lower = content.lower()
    detected_issues = []
    
    for category, patterns in HARMFUL_CONTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, content_lower, re.IGNORECASE):
                if category not in detected_issues:
                    detected_issues.append(category)
                break  # Found one pattern in this category, move to next
    
    is_safe = len(detected_issues) == 0
    return is_safe, detected_issues


def filter_harmful_content(content: str) -> str:
    """
    Filter out harmful content and replace with safe message.
    
    Args:
        content: The text content to filter
        
    Returns:
        Safe content (original if safe, or replacement message if harmful)
    """
    is_safe, detected_issues = check_content_safety(content)
    
    if is_safe:
        return content
    
    # Generate safe replacement message (natural, conversational format)
    safe_message = (
        "I apologize, but I cannot provide a response to this query as it may contain "
        "inappropriate or harmful content.\n\n"
        "For property-related questions, please contact the vendor or listing agent directly. "
        "They will be able to assist you with legitimate property enquiries.\n\n"
        "Based on available listing details, this is general information only and does not "
        "constitute financial or legal advice. For specific questions or confirmation, please "
        "contact the listing agent or vendor."
    )
    
    return safe_message


def sanitize_response(ai_response: AIResponse) -> AIResponse:
    """
    Sanitize AI response by filtering harmful content.
    
    Args:
        ai_response: AIResponse object to sanitize
        
    Returns:
        Sanitized AIResponse object
    """
    # Check and filter the answer content
    safe_answer = filter_harmful_content(ai_response.answer)
    
    # If content was filtered, update the response
    if safe_answer != ai_response.answer:
        # Create new response with filtered content
        disclaimer = "Based on available listing details, this is general information only and does not constitute financial or legal advice. For specific questions or confirmation, please contact the listing agent or vendor."
        return AIResponse(
            answer=safe_answer,
            needs_vendor_contact=True,  # Flag for vendor contact when content is filtered
            escalation_reason="Response contained inappropriate content and was filtered for safety.",
            data_sources=ai_response.data_sources,
            disclaimer=disclaimer  # Include disclaimer when content is filtered
        )
    
    return ai_response


def clean_text_for_tts(text: str) -> str:
    """
    Clean text for Text-to-Speech output.
    Removes HTML, converts markdown links to readable text, and removes 
    raw URLs to ensure natural-sounding TTS output.
    
    Args:
        text: The raw text from AI response
        
    Returns:
        Cleaned text suitable for TTS
    """
    if not text:
        return text
    
    cleaned = text
    
    # 1. Remove HTML tags
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    
    # 2. Convert markdown links [text](url) to "text link"
    # Pattern matches [anchor text](URL)
    cleaned = re.sub(
        r'\[([^\]]+)\]\([^)]+\)',
        r'\1 link',
        cleaned
    )
    
    # 3. Remove raw URLs (http, https, www patterns)
    # Matches http://, https://, www. followed by domain
    url_pattern = r'(?:https?://|www\.)[^\s\)>\]\'"]+'
    cleaned = re.sub(url_pattern, 'link', cleaned)
    
    # 4. Remove markdown formatting while keeping content
    # Bold: **text** or __text__ → text
    cleaned = re.sub(r'\*\*([^\*]+)\*\*', r'\1', cleaned)
    cleaned = re.sub(r'__([^_]+)__', r'\1', cleaned)
    
    # Italic: *text* or _text_ → text (but not already bold)
    cleaned = re.sub(r'(?<!\*)\*([^\*]+)\*(?!\*)', r'\1', cleaned)
    cleaned = re.sub(r'(?<!_)_([^_]+)_(?!_)', r'\1', cleaned)
    
    # 5. Remove markdown headers (# Header → Header)
    cleaned = re.sub(r'^#+\s*', '', cleaned, flags=re.MULTILINE)
    
    # 6. Remove markdown list markers (- item → item)
    cleaned = re.sub(r'^[\-\*]\s+', '', cleaned, flags=re.MULTILINE)
    
    # 7. Remove markdown blockquotes (> quote → quote)
    cleaned = re.sub(r'^>\s*', '', cleaned, flags=re.MULTILINE)
    
    # 8. Clean up extra whitespace
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = re.sub(r' {2,}', ' ', cleaned)
    
    # 9. Remove any remaining markdown link remnants (in case of edge cases)
    cleaned = re.sub(r'\[([^\]]*)\](?!\()', r'\1', cleaned)
    
    return cleaned.strip()

