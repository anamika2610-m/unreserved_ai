"""
Sync property listings from PostgreSQL database to pgvector embeddings.

This script:
1. Fetches all property listings from the PostgreSQL database
2. Chunks each listing into semantic segments (overview, specs, pricing, location)
3. Generates embeddings using OpenAI embeddings API
4. Stores embeddings in PostgreSQL with pgvector extension

Usage:
    python app/helpers/ingestion_pipeline/property/sync_pgvector.py
    # OR from project root:
    python -m app.helpers.ingestion_pipeline.property.sync_pgvector

Requirements:
    - DATABASE_URL set in .env
    - OPENAI_API_KEY set in .env
    - PostgreSQL with pgvector extension enabled
    - property_embeddings table created (via Alembic migrations)
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
# File location: app/helpers/ingestion_pipeline/property/sync_pgvector.py
# Project root is 5 levels up (property -> ingestion_pipeline -> helpers -> app -> project_root)
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root.resolve()))

from app.helpers.ingestion_pipeline.property.db_loader import fetch_listings_from_db
from app.helpers.ingestion_pipeline.shared.chunker import PropertyListingChunker
from app.helpers.ingestion_pipeline.property.pgvector_store import PgVectorStore


def main():
    print("\n" + "=" * 70)
    print("🔄 Syncing Listings to pgvector (PostgreSQL)")
    print("=" * 70)
    
    print("\n🗄️  Initializing pgvector store...")
    # Use OpenAI embeddings (text-embedding-3-small, 1536 dimensions)
    vector_store = PgVectorStore(embedding_model="text-embedding-3-small")
    
    print("\n📊 Fetching listings from database...")
    listings = fetch_listings_from_db(listing_status=None)  # All statuses
    
    if not listings:
        print("⚠️  No listings found in database.")
        return
    
    print(f"✓ Fetched {len(listings)} listings")
    
    print("\n📋 Listings to sync:")
    for listing in listings:
        print(f"  • {listing['title']} ({listing['listingStatus']})")
    
   
    print("\n🔨 Chunking listings...")
    chunker = PropertyListingChunker()
    all_chunks = chunker.chunk_all_listings(listings)
    print(f"✓ Created {len(all_chunks)} chunks from {len(listings)} listings")
    
    # Use incremental sync (UPSERT) - no clearing needed!
    # add_chunks() already handles updates vs inserts automatically
    # This preserves property_document chunks synced separately
    print(f"\n💾 Syncing chunks to pgvector (incremental upsert)...")
    print("   ℹ️  Existing chunks will be updated, new ones will be inserted")
    print("   ℹ️  property_document chunks are preserved (synced separately)")
    vector_store.add_chunks(all_chunks)
    
    stats = vector_store.get_stats()
    
    print("\n" + "=" * 70)
    print("✅ Sync Complete!")
    print("=" * 70)
    print(f"📊 Storage: PostgreSQL + pgvector")
    print(f"📦 Total chunks: {stats['total_chunks']}")
    print(f"📝 Unique listings: {stats['unique_listings']}")
    print(f"🔧 Embedding model: {stats['embedding_model']}")
    print(f"📐 Vector dimension: {stats['vector_dimension']}")
    
    if stats['chunk_types']:
        print(f"\n📊 Chunks by type:")
        for chunk_type, count in stats['chunk_types'].items():
            print(f"  • {chunk_type}: {count}")
    
    print("\n📋 Synced listings by status:")
    status_counts = {}
    for listing in listings:
        status = listing['listingStatus']
        status_counts[status] = status_counts.get(status, 0) + 1
    
    for status, count in status_counts.items():
        print(f"  • {status}: {count}")
    
    print("=" * 70)
    
    vector_store.close()


if __name__ == "__main__":
    main()

