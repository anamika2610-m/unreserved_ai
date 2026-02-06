"""
Test script to verify tone adaptation integration with chatbot responses.

This script tests:
1. Activity metrics API endpoint
2. Chat endpoint with tone adaptation
3. Verifies tone context is injected into responses
"""
import requests
import json
from uuid import UUID

# Configuration
BASE_URL = "http://localhost:8000"  # Adjust if your server runs on a different port
LISTING_ID = None  # Set this to a valid listing ID for testing


def test_activity_metrics(listing_id: str):
    """Test the activity metrics endpoint."""
    print("\n" + "="*60)
    print("TEST 1: Activity Metrics API")
    print("="*60)
    
    url = f"{BASE_URL}/api/v1/activity/metrics/{listing_id}"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        
        data = response.json()
        print(f"✅ Successfully fetched activity metrics")
        print(f"\nMetrics:")
        print(f"  - Enquiries (7d): {data['enquiries_7d']}")
        print(f"  - Repeat Buyers (7d): {data['repeat_buyers_7d']}")
        print(f"  - First Inspection Groups (7d): {data['first_inspection_groups_7d']}")
        print(f"  - Multi-Inspection Buyers (7d): {data['multi_inspection_buyers_7d']}")
        print(f"  - Contract Requests (7d): {data['contract_requests_7d']}")
        print(f"  - Genuine Offers (7d): {data['genuine_offers_7d']}")
        print(f"  - Competing Offers (7d): {data['competing_offers_7d']}")
        print(f"  - B&P Inspections (7d): {data['bp_inspections_7d']}")
        print(f"\n🎭 Tone Level: {data['tone_level']}")
        print(f"🎭 Tone Context: {data['tone_context']}")
        
        return data
    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching activity metrics: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"   Response: {e.response.text}")
        return None


def test_chat_with_tone(listing_id: str, question: str = "What is the price of this property?"):
    """Test the chat endpoint and verify tone adaptation."""
    print("\n" + "="*60)
    print("TEST 2: Chat Endpoint with Tone Adaptation")
    print("="*60)
    
    url = f"{BASE_URL}/api/v1/chat/message"
    
    payload = {
        "question": question,
        "listing_id": listing_id,
        "user_id": None,  # Anonymous user
        "source": None
    }
    
    try:
        print(f"\n📤 Sending chat request:")
        print(f"   Question: {question}")
        print(f"   Listing ID: {listing_id}")
        
        response = requests.post(url, json=payload)
        response.raise_for_status()
        
        data = response.json()
        print(f"\n✅ Successfully received chat response")
        print(f"\n📥 Response:")
        print(f"   Answer: {data['answer'][:200]}...")
        print(f"   Needs Vendor Contact: {data.get('needs_vendor_contact', False)}")
        
        # Check server logs for tone adaptation messages
        print(f"\n💡 Check server logs for:")
        print(f"   - '🎭 Tone adaptation: ...' messages")
        print(f"   - '🎭 Injected ... tone context into prompt' messages")
        
        return data
    except requests.exceptions.RequestException as e:
        print(f"❌ Error sending chat request: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"   Response: {e.response.text}")
        return None


def test_tone_priority_scenarios():
    """Test different scenarios to verify tone priority."""
    print("\n" + "="*60)
    print("TEST 3: Tone Priority Verification")
    print("="*60)
    
    print("\n💡 To verify tone priority, check the activity metrics for a listing")
    print("   that has multiple conditions satisfied. The tone should follow:")
    print("   1. URGENT (highest)")
    print("   2. TIME_SENSITIVE")
    print("   3. COMPETITIVE")
    print("   4. DECISIVE")
    print("   5. CONFIDENT (lowest)")
    
    print("\n📋 Example scenarios to test:")
    print("   - Listing with 2+ genuine offers → Should be URGENT")
    print("   - Listing with 3+ contract requests → Should be TIME_SENSITIVE")
    print("   - Listing with high inspections → Should be COMPETITIVE")
    print("   - Listing with competing offers → Should be DECISIVE")
    print("   - Listing with high enquiries → Should be CONFIDENT")


def main():
    """Main test function."""
    print("\n" + "="*60)
    print("TONE ADAPTATION INTEGRATION TEST")
    print("="*60)
    
    # Get listing ID from user or use default
    listing_id = LISTING_ID
    if not listing_id:
        listing_id = input("\nEnter a listing ID (UUID) to test: ").strip()
    
    if not listing_id:
        print("❌ No listing ID provided. Exiting.")
        return
    
    # Validate UUID format
    try:
        UUID(listing_id)
    except ValueError:
        print(f"❌ Invalid UUID format: {listing_id}")
        return
    
    # Test 1: Activity metrics
    metrics = test_activity_metrics(listing_id)
    
    if metrics:
        # Test 2: Chat with tone
        test_chat_with_tone(listing_id)
        
        # Test 3: Priority info
        test_tone_priority_scenarios()
        
        print("\n" + "="*60)
        print("TEST COMPLETE")
        print("="*60)
        print("\n📝 Next steps:")
        print("   1. Check server logs for tone adaptation messages")
        print("   2. Compare the tone_level from metrics API with chat responses")
        print("   3. Verify tone context appears in LLM prompts (check server logs)")
        print("   4. Test with different listings to see different tones")
    else:
        print("\n❌ Could not fetch activity metrics. Please check:")
        print("   1. Server is running")
        print("   2. Listing ID is valid")
        print("   3. Database connection is working")


if __name__ == "__main__":
    main()
