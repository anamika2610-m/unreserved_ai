"""
Test script for the Chat API endpoint.
Tests the /api/chat/message endpoint with sample queries.
"""

import requests
import json
from typing import Dict, Any


API_URL = "http://localhost:8000"


def test_chat_api(question: str, listing_id: str = "prop-similar-001") -> Dict[str, Any]:
    """
    Test the chat API with a question.
    
    Args:
        question: Question to ask
        listing_id: Property listing ID
        
    Returns:
        API response as dictionary
    """
    endpoint = f"{API_URL}/api/chat/message"
    
    payload = {
        "question": question,
        "listing_id": listing_id,
        "user_id": "test_user",
        "session_id": "test_session_123"
    }
    
    try:
        response = requests.post(endpoint, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return None


def print_response(response: Dict[str, Any]):
    """Pretty print API response."""
    if not response:
        return
    
    print("\n" + "=" * 80)
    print("📝 BOT RESPONSE:")
    print("=" * 80)
    print(response.get("answer", "No answer"))
    
    if response.get("nearby_properties"):
        print("\n" + "=" * 80)
        print("📍 NEARBY PROPERTIES:")
        print("=" * 80)
        print(json.dumps(response["nearby_properties"], indent=2))
    
    print("\n" + "-" * 80)
    print(f"Session ID: {response.get('session_id')}")
    print(f"Needs Vendor Contact: {response.get('needs_vendor_contact')}")
    print(f"Timestamp: {response.get('timestamp')}")
    print("=" * 80 + "\n")


def main():
    """Run test queries."""
    print("🚀 Testing Property Chat API")
    print(f"API URL: {API_URL}\n")
    
    # Test 1: Basic property query
    print("Test 1: Pricing and amenities query")
    response = test_chat_api("What are the pricing and amenities?")
    print_response(response)
    
    # Test 2: Nearby properties
    print("\nTest 2: Nearby properties query")
    response = test_chat_api("Are there any nearby properties for sale?")
    print_response(response)
    
    # Test 3: Location query
    print("\nTest 3: Location query")
    response = test_chat_api("What hospitals are nearby?")
    print_response(response)
    
    # Test 4: Multi-topic
    print("\nTest 4: Multi-topic query")
    response = test_chat_api("What are the pricing, amenities, and nearby properties?")
    print_response(response)


if __name__ == "__main__":
    main()

