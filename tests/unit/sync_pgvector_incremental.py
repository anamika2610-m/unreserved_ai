"""
Incremental sync for pgvector - updates existing listings without clearing all data.

⚠️  STATUS: NOT CURRENTLY IN ACTIVE USE
   - This is a utility script kept for future use
   - Currently using: app/helpers/ingestion_pipeline/property/sync_pgvector.py
   - Use this script when you need incremental updates without full resync

This script:
1. Fetches listings from the database
2. For each listing, checks if embeddings exist
3. Updates existing embeddings or adds new ones
4. Does NOT delete existing embeddings (safer for production)

Usage:
    python tests/unit/sync_pgvector_incremental.py

Requirements:
    - DATABASE_URL set in .env
    - OPENAI_API_KEY set in .env

Use this when:
- You want to add new listings without affecting existing ones
- You're updating specific listings
- You want to preserve existing embeddings

Use sync_pgvector.py (full resync) when:
- You're changing the chunking logic
- You're upgrading the embedding model
- You want a clean slate
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Ensure project root (repository root) is on sys.path so that `import app` works
# File location: <project_root>/tests/unit/sync_pgvector_incremental.py
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.helpers.ingestion_pipeline.property.db_loader import fetch_listings_from_db
from app.helpers.ingestion_pipeline.shared.chunker import PropertyListingChunker
from app.helpers.ingestion_pipeline.property.pgvector_store import PgVectorStore


def main():
    """Main incremental sync function."""
    print("\n" + "=" * 70)
    print("🔄 Incremental Sync to pgvector (PostgreSQL)")
    print("=" * 70)
    print("⚠️  This will UPDATE/ADD embeddings without deleting existing ones")
    
    vector_store = None
    
    try:
        print("\n🗄️  Initializing pgvector store...")
        # Use OpenAI embeddings (text-embedding-3-small, 1536 dimensions)
        vector_store = PgVectorStore(embedding_model="text-embedding-3-small")
        
        before_stats = vector_store.get_stats()
        print(f"📊 Current embeddings: {before_stats['total_chunks']} chunks for {before_stats['unique_listings']} listings")
        
        print("\n📊 Fetching listings from database...")
        listings = fetch_listings_from_db(listing_status=None) 
        
        if not listings:
            print("⚠️  No listings found in database.")
            return
        
        print(f"✓ Fetched {len(listings)} listings from database")
        
        print("\n🔨 Chunking listings...")
        chunker = PropertyListingChunker()
        all_chunks = chunker.chunk_all_listings(listings)
        print(f"✓ Created {len(all_chunks)} chunks from {len(listings)} listings")
        
        print(f"\n💾 Updating embeddings in pgvector...")
        print("   This may take a while for large datasets...")
        vector_store.add_chunks(all_chunks)
        
        after_stats = vector_store.get_stats()
        
        print("\n" + "=" * 70)
        print("✅ Incremental Sync Complete!")
        print("=" * 70)
        print(f"📊 Storage: PostgreSQL + pgvector")
        print(f"📦 Total chunks: {before_stats['total_chunks']} → {after_stats['total_chunks']}")
        print(f"📝 Unique listings: {before_stats['unique_listings']} → {after_stats['unique_listings']}")
        print(f"🔧 Embedding model: {after_stats['embedding_model']}")
        
        chunks_delta = after_stats['total_chunks'] - before_stats['total_chunks']
        listings_delta = after_stats['unique_listings'] - before_stats['unique_listings']
        
        if chunks_delta > 0:
            print(f"\n✨ Added {chunks_delta} new chunks")
        if listings_delta > 0:
            print(f"✨ Added {listings_delta} new listings")
        
        if after_stats['chunk_types']:
            print(f"\n📊 Chunks by type:")
            for chunk_type, count in after_stats['chunk_types'].items():
                print(f"  • {chunk_type}: {count}")
        
        print("=" * 70)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Sync interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Sync failed with error: {e}")
        import traceback
        print("\n📋 Full error details:")
        traceback.print_exc()
        sys.exit(1)
    finally:
        
        if vector_store:
            vector_store.close()


if __name__ == "__main__":
    main()

