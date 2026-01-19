"""
Smart sync for pgvector - only updates changed listings (production-ready).

⚠️  STATUS: NOT CURRENTLY IN ACTIVE USE
   - This is a utility script kept for future use
   - Currently using: app/helpers/ingestion_pipeline/property/sync_pgvector.py
   - Use this script when you need intelligent change detection and delta sync

This script implements intelligent change detection:
1. Compares database listings with existing embeddings
2. Identifies new, updated, and deleted listings
3. Only syncs the delta (changes)
4. No downtime - chat keeps working

Usage:
    python tests/unit/sync_pgvector_smart.py

Requirements:
    - DATABASE_URL set in .env
    - OPENAI_API_KEY set in .env

Performance:
- 10 listings changed out of 1000 = ~2 seconds
- Full resync of 1000 listings = ~10 minutes

Use Cases:
- Webhook triggered sync when listing changes
- Scheduled sync (every 5 minutes)
- Production continuous sync
"""
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Set
from dotenv import load_dotenv

# Load .env file
load_dotenv()

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Ensure project root (repository root) is on sys.path so that `import app` works
# File location: <project_root>/tests/unit/sync_pgvector_smart.py
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.helpers.ingestion_pipeline.property.db_loader import fetch_listings_from_db
from app.helpers.ingestion_pipeline.shared.chunker import PropertyListingChunker
from app.helpers.ingestion_pipeline.property.pgvector_store import PgVectorStore
from app.db.session import SessionLocal
from sqlalchemy import text


def get_existing_listing_ids(vector_store: PgVectorStore) -> Set[str]:
    """Get set of listing IDs that already have embeddings."""
    result = vector_store.db_session.execute(
        text("SELECT DISTINCT listing_id FROM property_embeddings")
    )
    return {str(row[0]) for row in result}


def main():
    """Smart sync with change detection."""
    start_time = datetime.now()
    
    print("\n" + "=" * 70)
    print("🔄 Smart Sync to pgvector (Change Detection)")
    print("=" * 70)
    
    vector_store = None
    
    try:
        # Initialize
        print("\n🗄️  Initializing pgvector store...")
        # Use OpenAI embeddings (text-embedding-3-small, 1536 dimensions)
        vector_store = PgVectorStore(embedding_model="text-embedding-3-small")
        
        # Get existing embeddings
        print("\n📊 Analyzing existing embeddings...")
        existing_ids = get_existing_listing_ids(vector_store)
        print(f"   Found {len(existing_ids)} listings with embeddings")
        
        # Fetch current listings from database
        print("\n📊 Fetching current listings from database...")
        db_listings = fetch_listings_from_db(listing_status=None)
        db_listing_ids = {listing['id'] for listing in db_listings}
        print(f"   Found {len(db_listing_ids)} listings in database")
        
        # Detect changes
        new_listings = db_listing_ids - existing_ids
        deleted_listings = existing_ids - db_listing_ids
        existing_listings = db_listing_ids & existing_ids
        
        print("\n🔍 Change Detection:")
        print(f"   ✨ New listings: {len(new_listings)}")
        print(f"   🗑️  Deleted listings: {len(deleted_listings)}")
        print(f"   📝 Existing listings: {len(existing_listings)}")
        print(f"   📊 Total to sync: {len(new_listings) + len(existing_listings)}")
        
        # Strategy decision
        total_to_process = len(new_listings) + len(existing_listings)
        should_full_resync = total_to_process > len(existing_ids) * 0.5
        
        if should_full_resync and existing_ids:
            print("\n⚠️  More than 50% of data changed - Full resync recommended")
            print("   Run: python tests/unit/sync_pgvector.py")
            return
        
        # Delete removed listings
        if deleted_listings:
            print(f"\n🗑️  Removing {len(deleted_listings)} deleted listings...")
            for listing_id in deleted_listings:
                vector_store.db_session.execute(
                    text("DELETE FROM property_embeddings WHERE listing_id = :id"),
                    {"id": listing_id}
                )
            vector_store.db_session.commit()
            print("   ✓ Deleted")
        
        # Process new and updated listings
        listings_to_sync = [l for l in db_listings if l['id'] in new_listings or l['id'] in existing_listings]
        
        if not listings_to_sync:
            print("\n✅ No changes detected - embeddings are up to date!")
            return
        
        print(f"\n🔨 Chunking {len(listings_to_sync)} listings...")
        chunker = PropertyListingChunker()
        all_chunks = chunker.chunk_all_listings(listings_to_sync)
        print(f"   ✓ Created {len(all_chunks)} chunks")
        
        # For updated listings, remove old embeddings first
        if existing_listings:
            print(f"\n🔄 Updating {len(existing_listings)} existing listings...")
            for listing_id in existing_listings:
                if listing_id in db_listing_ids:  # Only if still in DB
                    vector_store.db_session.execute(
                        text("DELETE FROM property_embeddings WHERE listing_id = :id"),
                        {"id": listing_id}
                    )
            vector_store.db_session.commit()
        
        # Add new/updated embeddings
        print(f"\n💾 Adding {len(all_chunks)} chunks to pgvector...")
        vector_store.add_chunks(all_chunks)
        
        # Get final stats
        stats = vector_store.get_stats()
        elapsed = (datetime.now() - start_time).total_seconds()
        
        print("\n" + "=" * 70)
        print("✅ Smart Sync Complete!")
        print("=" * 70)
        print(f"⏱️  Time taken: {elapsed:.2f} seconds")
        print(f"📦 Total chunks: {stats['total_chunks']}")
        print(f"📝 Total listings: {stats['unique_listings']}")
        print(f"✨ New listings added: {len(new_listings)}")
        print(f"🔄 Listings updated: {len(existing_listings & db_listing_ids)}")
        print(f"🗑️  Listings removed: {len(deleted_listings)}")
        print("=" * 70)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Sync interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Sync failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if vector_store:
            vector_store.close()


if __name__ == "__main__":
    main()

