"""
Interactive CLI to chat with the property bot for a specific listing ID.

Usage (from repo root):
    python scripts/chat_listing_cli.py

You'll be prompted once for the listing ID, then you can ask questions
until you type 'exit' or press Ctrl+C.
"""

import os
import sys
from pathlib import Path

# Disable ChromaDB telemetry to avoid noisy warnings
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.rag_pipeline.schemas import BuyerEnquiry  # noqa: E402
from app.rag_pipeline.preprocess import preprocess_enquiry  # noqa: E402
from app.rag_pipeline.generation import ResponseGenerator  # noqa: E402


def main():
    print("=" * 70)
    print("Property Chat CLI (listing-scoped)")
    print("=" * 70)

    # Initialize generator with the project chroma directory
    try:
        generator = ResponseGenerator(
            collection_name="property_listings",
            persist_directory=str(project_root / "chroma_db"),
        )
        print("✓ Response generator initialized")
    except Exception as e:
        print(f"✗ Error initializing generator: {e}")
        print("Ensure:")
        print("  - GROQ_API_KEY is set in .env")
        print("  - Vector store is built: python scripts/initialize_vector_store.py")
        return

    listing_id = input("\nEnter listing ID to scope the chat: ").strip()
    if not listing_id:
        print("Listing ID is required. Exiting.")
        return

    print("\nType your questions. Type 'exit' to quit.\n")
    while True:
        try:
            question = input("You: ").strip()
            if question.lower() in {"exit", "quit"}:
                print("Bye!")
                break

            enquiry = BuyerEnquiry(
                question=question,
                listing_id=listing_id,
                user_id="cli_user",
                session_id="cli_session",
            )

            enquiry_data = preprocess_enquiry(enquiry)
            result = generator.generate_response_from_enquiry(enquiry_data)
            ai_response = result["ai_response"]

            print("\nBot:")
            print(ai_response.answer)
            
            # Show nearby properties JSON if available
            if result.get("nearby_properties"):
                import json
                print("\n" + "="*70)
                print("📍 NEARBY PROPERTIES JSON:")
                print("="*70)
                print(json.dumps(result["nearby_properties"], indent=2))
            
            # Show amenity links if available
            if result.get("amenity_links"):
                import json
                print("\n" + "="*70)
                print("🗺️  AMENITY LINKS (Google Maps):")
                print("="*70)
                for link in result["amenity_links"]:
                    print(f"{link['icon']} {link['label']}")
                    print(f"   {link['url']}")
                    print()
            
            print("\n---\n")
        except KeyboardInterrupt:
            print("\nInterrupted. Exiting.")
            break
        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == "__main__":
    main()
