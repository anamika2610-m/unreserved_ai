"""
Test script for the property listing enquiry system.
Run this from the project root: python scripts/test_enquiry_system.py
"""
import os
import sys
from pathlib import Path

# Disable ChromaDB telemetry to avoid errors
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "1")

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.rag_pipeline.preprocess import preprocess_enquiry
from app.rag_pipeline.generation import ResponseGenerator
from app.rag_pipeline.schemas import BuyerEnquiry
from app.rag_pipeline.postprocess import format_response_for_api, sanitize_response


def main():
    """Test the enquiry system with either canned tests or interactive input.

    Usage:
        python scripts/test_enquiry_system.py            # run canned tests
        python scripts/test_enquiry_system.py --ask      # prompt for your own question + listing id
    """
    print("=" * 70)
    print("Property Listing Enquiry System")
    print("=" * 70)
    
    # Initialize generator
    print("\nInitializing response generator...")
    try:
        generator = ResponseGenerator(
            collection_name="property_listings",
            persist_directory=str(project_root / "chroma_db"),
        )
        print("✓ Response generator initialized")
    except Exception as e:
        print(f"✗ Error initializing generator: {e}")
        print("\nMake sure you have:")
        print("1. Set GROQ_API_KEY in your .env file")
        print("2. Installed all dependencies: pip install -r requirements.txt")
        print("3. Initialized the vector store: python scripts/initialize_vector_store.py")
        return
    
    if len(sys.argv) > 1 and sys.argv[1] == "--ask":
        # Interactive one-off question
        question = input("\nEnter your question: ").strip()
        listing_id = input("Enter listing id (or leave blank): ").strip() or None
        enquiry = BuyerEnquiry(
            question=question,
            listing_id=listing_id,
            user_id="cli_user",
            session_id="cli_session"
        )
        enquiry_data = preprocess_enquiry(enquiry)
        print(f"\nPreprocessed query: {enquiry_data['normalized_query']}")
        if enquiry_data.get('listing_id'):
            print(f"Listing ID: {enquiry_data['listing_id']}")
        
        print("\nGenerating response...")
        result = generator.generate_response_from_enquiry(enquiry_data)
        ai_response = result["ai_response"]
        
        print("\n" + "-" * 70)
        print("AI RESPONSE:")
        print("-" * 70)
        print(ai_response.answer)
        print("\n" + "-" * 70)
        print("DATA SOURCES:")
        print("-" * 70)
        for j, ds in enumerate(ai_response.data_sources[:3], 1):
            print(f"  {j}. {ds.chunk_type} (Listing: {ds.listing_id[:24]}...)")
        print("\n" + "=" * 70)
        print("Done")
        print("=" * 70)
        return
    
    # Canned test queries
    test_queries = [
        {
            "question": "What is the price of properties with 3 bedrooms?",
            "listing_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        },
        {
            "question": "Show me auction properties in Sydney",
            "listing_id": "11111111-aaaa-bbbb-cccc-000000000002"
        },
        {
            "question": "What are the specifications for properties with swimming pools?",
            "listing_id": "11111111-aaaa-bbbb-cccc-000000000002"
        },
    ]
    
    for i, test_query in enumerate(test_queries, 1):
        print(f"\n{'=' * 70}")
        print(f"Test Query {i}: {test_query['question']}")
        print('=' * 70)
        
        try:
            # Create enquiry
            enquiry = BuyerEnquiry(
                question=test_query["question"],
                listing_id=test_query.get("listing_id"),
                user_id="test_user",
                session_id="test_session"
            )
            
            # Preprocess
            enquiry_data = preprocess_enquiry(enquiry)
            print(f"\nPreprocessed query: {enquiry_data['normalized_query']}")
            if enquiry_data.get('listing_id'):
                print(f"Listing ID: {enquiry_data['listing_id']}")
            
            # Generate response
            print("\nGenerating response...")
            result = generator.generate_response_from_enquiry(enquiry_data)
            
            # Get response
            ai_response = result["ai_response"]
            log_entry = result["log_entry"]
            
            # Format for display
            print("\n" + "-" * 70)
            print("AI RESPONSE:")
            print("-" * 70)
            print(ai_response.answer)
            print("\n" + "-" * 70)
            print("METADATA:")
            print("-" * 70)
            print(f"Needs Vendor Contact: {ai_response.needs_vendor_contact}")
            if ai_response.escalation_reason:
                print(f"Escalation Reason: {ai_response.escalation_reason}")
            print(f"Data Sources Used: {len(ai_response.data_sources)}")
            for j, ds in enumerate(ai_response.data_sources[:3], 1):
                print(f"  {j}. {ds.chunk_type} (Listing: {ds.listing_id[:20]}...)")
            
        except Exception as e:
            print(f"\n✗ Error processing query: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 70)
    print("Test Complete")
    print("=" * 70)


if __name__ == "__main__":
    main()

