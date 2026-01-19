"""
Quick script to sync ALL listings from database (all statuses) to pgvector.
This includes active, under_offer, sold, etc.

Requirements:
    - DATABASE_URL set in .env
    - OPENAI_API_KEY set in .env
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Disable tokenizers parallelism warnings
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Ensure project root (repository root) is on sys.path so that `import app` works
# File location: <project_root>/tests/unit/sync_all_listings.py
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.helpers.ingestion_pipeline.property.db_loader import fetch_listings_from_db
from app.helpers.ingestion_pipeline.shared.chunker import PropertyListingChunker
from app.helpers.ingestion_pipeline.property.pgvector_store import PgVectorStore


def main():
    print("\n" + "=" * 70)
    print("🔄 Syncing ALL Listings from Database (All Statuses)")
    print("=" * 70)
    
    # Fetch ALL listings (no status filter)
    print("\n📊 Fetching ALL listings from database...")
    listings = fetch_listings_from_db(listing_status=None)  # None = all statuses
    
    print(f"✓ Fetched {len(listings)} listings from database")
    
    # Show what we're syncing
    print("\n📋 Listings to sync:")
    for listing in listings:
        print(f"  • {listing['title']} ({listing['listingStatus']})")
    
    if not listings:
        print("\n⚠️  No listings found in database.")
        return
    
    # Chunk listings
    print("\n🔨 Chunking listings...")
    chunker = PropertyListingChunker()
    all_chunks = chunker.chunk_all_listings(listings)
    print(f"✓ Created {len(all_chunks)} chunks from {len(listings)} listings")
    
    # Initialize pgvector store
    print("\n🗄️  Initializing pgvector store...")
    # Use OpenAI embeddings (text-embedding-3-small, 1536 dimensions)
    vector_store = PgVectorStore(embedding_model="text-embedding-3-small")
    
    # Clear existing data
    print("\n🗑️  Clearing existing embeddings...")
    vector_store.clear_collection()
    print("✓ Existing embeddings cleared")
    
    # Add new chunks
    print(f"\n💾 Adding {len(all_chunks)} chunks to vector store...")
    vector_store.add_chunks(all_chunks)
    print("✓ Chunks added successfully")
    
    # Print summary
    stats = vector_store.get_stats()
    print("\n" + "=" * 70)
    print("✅ Sync Complete!")
    print("=" * 70)
    print(f"📊 Vector Store: pgvector (PostgreSQL)")
    print(f"📦 Total chunks: {stats.get('total_chunks', 0)}")
    print(f"📝 Total listings: {stats.get('unique_listings', len(listings))}")
    print(f"🔧 Embedding model: {stats.get('embedding_model', 'unknown')}")
    print("\n📋 Synced listings by status:")
    
    # Count by status
    status_counts = {}
    for listing in listings:
        status = listing['listingStatus']
        status_counts[status] = status_counts.get(status, 0) + 1
    
    for status, count in status_counts.items():
        print(f"  • {status}: {count}")
    
    print("=" * 70)


if __name__ == "__main__":
    main()

