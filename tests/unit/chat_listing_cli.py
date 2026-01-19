"""
Interactive CLI to chat with the property bot for a specific listing ID.
Now using pgvector (PostgreSQL native vector storage).

Usage (from repo root):
    python tests/unit/chat_listing_cli.py

You'll be prompted once for the listing ID, then you can ask questions
until you type 'exit' or press Ctrl+C.
"""

import os
import sys
from pathlib import Path

# Disable tokenizer warnings
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


# Ensure project root (repository root) is on sys.path so that `import app` works
# File location: <project_root>/tests/unit/chat_listing_cli.py
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.services.rag_pipeline.generation import ResponseGenerator  # noqa: E402
from app.helpers.ingestion_pipeline.property.pgvector_store import PgVectorStore  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402
from uuid import UUID, uuid5, NAMESPACE_DNS  # noqa: E402


def main():
    print("=" * 70)
    print("Property Chat CLI (listing-scoped) - using pgvector")
    print("=" * 70)

    # Initialize generator with pgvector
    try:
        generator = ResponseGenerator()
        print("✓ Response generator initialized (pgvector)")
    except Exception as e:
        print(f"✗ Error initializing generator: {e}")
        print("Ensure:")
        print("  - OPENAI_API_KEY is set in .env")
        print("  - DATABASE_URL is set in .env")
        print("  - Vector embeddings synced: python tests/unit/sync_pgvector.py")
        return

    listing_id = input("\nEnter listing ID to scope the chat: ").strip()
    if not listing_id:
        print("Listing ID is required. Exiting.")
        return
    
    # Check if embeddings exist for this listing
    print("\n🔍 Checking embeddings...")
    try:
        db = SessionLocal()
        result = db.execute(
            text("SELECT COUNT(*) FROM property_embeddings WHERE listing_id = :id"),
            {"id": listing_id}
        )
        count = result.scalar()
        db.close()
        
        if count == 0:
            print(f"⚠️  WARNING: No embeddings found for listing '{listing_id}'")
            print("   The bot may not be able to answer questions about this property.")
            print("\n   To fix this:")
            print("   1. Run: python tests/unit/sync_pgvector.py")
            print("   2. Or sync specific listing via API: POST /api/v1/sync/trigger")
            print("\n   Continue anyway? (y/n): ", end="")
            response = input().strip().lower()
            if response != 'y':
                print("Exiting.")
                return
        else:
            print(f"✓ Found {count} embeddings for this listing")
    except Exception as e:
        print(f"⚠️  Could not check embeddings: {e}")
        print("   Continuing anyway...")

    print("\nType your questions. Type 'exit' to quit.\n")
    while True:
        try:
            question = input("You: ").strip()
            if question.lower() in {"exit", "quit"}:
                print("Bye!")
                break

            # Convert listing_id and user_id to UUID if they're strings
            listing_id_uuid = listing_id
            if isinstance(listing_id, str):
                try:
                    listing_id_uuid = UUID(listing_id)
                except ValueError:
                    listing_id_uuid = uuid5(NAMESPACE_DNS, listing_id)
            
            user_id_str = "cli_user"
            try:
                user_id_uuid = UUID(user_id_str)
            except ValueError:
                user_id_uuid = uuid5(NAMESPACE_DNS, user_id_str)

            result = generator.generate_response(
                query=question,
                listing_id=str(listing_id_uuid),
                user_id=str(user_id_uuid),
            )
            ai_response = result["ai_response"]

            print("\nBot:")
            print(ai_response.answer)
            
            # Show error details if available (from escalation_reason)
            if ai_response.escalation_reason and "error" in ai_response.escalation_reason.lower():
                print("\n" + "="*70)
                print("⚠️  ERROR DETAILS:")
                print("="*70)
                print(ai_response.escalation_reason)
                print("="*70)
            
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
            print(f"\n❌ Error: {e}")
            import traceback
            print("\n📋 Full traceback:")
            traceback.print_exc()
            print()


if __name__ == "__main__":
    main()
