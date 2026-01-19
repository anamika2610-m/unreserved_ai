"""
Sync Property-Specific PDFs to property_embeddings table.
Fetches propertyDocuments from database via repository layer.

Usage:
    # Sync all active listings with documents
    python app/helpers/ingestion_pipeline/property/sync_property_pdfs.py
    # OR from project root:
    python -m app.helpers.ingestion_pipeline.property.sync_property_pdfs
    
    # Sync specific listing
    python app/helpers/ingestion_pipeline/property/sync_property_pdfs.py --listing-id <uuid>
    
    # Sync and test search
    python app/helpers/ingestion_pipeline/property/sync_property_pdfs.py --listing-id <uuid> --test
"""
import sys
import traceback
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to path
# File location: app/helpers/ingestion_pipeline/property/sync_property_pdfs.py
# Project root is 5 levels up (property -> ingestion_pipeline -> helpers -> app -> project_root)
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root.resolve()))

from app.db.session import SessionLocal
from app.db.postgres.repositories import ListingRepository
from app.helpers.ingestion_pipeline.property.property_pdf_processor import PropertyPDFProcessor
from app.helpers.ingestion_pipeline.property.pgvector_store import PgVectorStore


# Constants
DEFAULT_CHUNK_SIZE = 500
SEPARATOR_LENGTH = 70
CONTENT_PREVIEW_LENGTH = 150


@contextmanager
def get_db_session():
    """Context manager for database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _fetch_listings(
    listing_repo: ListingRepository,
    listing_ids: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Fetch listings from database.
    
    Args:
        listing_repo: Listing repository instance
        listing_ids: Optional list of specific listing IDs
        
    Returns:
        List of listing dictionaries
    """
    print("\n📊 Fetching listings from database via repository...")
    if listing_ids:
        listings = listing_repo.fetch_listings(
            listing_ids=listing_ids,
            listing_status=None  # Don't filter by status for specific listings
        )
        print(f"   ✓ Fetched {len(listings)} specified listings")
    else:
        listings = listing_repo.fetch_listings(listing_status="active")
        print(f"   ✓ Fetched {len(listings)} active listings")
    
    return listings


def _process_listing_documents(
    listing_id: str,
    listing: Dict[str, Any],
    property_docs: List[Dict[str, Any]],
    pdf_processor: PropertyPDFProcessor,
    vector_store: PgVectorStore
) -> int:
    """
    Process documents for a single listing.
    
    Args:
        listing_id: Listing ID
        listing: Listing dictionary
        property_docs: List of property documents
        pdf_processor: PDF processor instance
        vector_store: Vector store instance
        
    Returns:
        Number of chunks added, or 0 if failed
    """
    print(f"\n📍 Listing: {listing_id}")
    print(f"   Title: {listing.get('title', 'N/A')}")
    
    # Show document summary
    summary = pdf_processor.get_document_summary(property_docs)
    print(f"   Documents: {summary['total']} total")
    for file_type, count in summary['by_type'].items():
        print(f"      - {file_type}: {count}")
    
    try:
        # Process documents
        chunks = pdf_processor.process_property_documents(listing_id, property_docs)
        
        if not chunks:
            print(f"   ⚠️  No chunks generated")
            return 0
        
        # Add to vector store
        print(f"   💾 Adding {len(chunks)} chunks to property_embeddings...")
        vector_store.add_chunks(chunks)
        
        print(f"   ✓ Successfully synced {len(chunks)} chunks")
        return len(chunks)
    
    except Exception as e:
        print(f"   ❌ Failed to process listing {listing_id}: {e}")
        traceback.print_exc()
        return 0


def _print_statistics(
    listings_with_docs_count: int,
    successful_listings: int,
    total_chunks: int,
    vector_store: PgVectorStore
) -> None:
    """Print sync statistics."""
    print("\n" + "=" * SEPARATOR_LENGTH)
    print("📊 Sync Statistics")
    print("=" * SEPARATOR_LENGTH)
    print(f"\n Listings with documents: {listings_with_docs_count}")
    print(f" Listings processed: {successful_listings}/{listings_with_docs_count}")
    print(f" Total chunks added: {total_chunks}")
    
    # Show vector store stats
    stats = vector_store.get_stats()
    print(f"\n Vector Store Stats:")
    print(f"   Total embeddings: {stats.get('total', 0)}")
    if 'chunk_types' in stats:
        print(f"   Chunk types:")
        for chunk_type, count in stats['chunk_types'].items():
            print(f"      - {chunk_type}: {count}")


def sync_property_pdfs(listing_ids: Optional[List[str]] = None) -> None:
    """
    Sync property PDFs for specified listings.
    Fetches property documents from database via repository layer.
    
    Args:
        listing_ids: Optional list of listing IDs to sync. If None, sync all active listings.
    """
    print("=" * SEPARATOR_LENGTH)
    print("Property PDF Sync to property_embeddings (via Repository)")
    print("=" * SEPARATOR_LENGTH)
    
    with get_db_session() as db:
        listing_repo = ListingRepository(db)
        
        # Initialize processors
        pdf_processor = PropertyPDFProcessor(chunk_size=DEFAULT_CHUNK_SIZE)
        
        # Use context manager for vector store to ensure proper cleanup
        with PgVectorStore() as vector_store:
            # Fetch listings from database
            listings = _fetch_listings(listing_repo, listing_ids)
            
            # Process each listing and fetch property documents
            total_chunks = 0
            successful_listings = 0
            listings_with_docs_count = 0
            
            for listing in listings:
                listing_id = listing.get('id')
                
                # Fetch property documents from database via repository
                property_docs = listing_repo.fetch_property_documents(listing_id)
                
                if not property_docs:
                    continue
                
                listings_with_docs_count += 1
                chunks_added = _process_listing_documents(
                    listing_id, listing, property_docs, pdf_processor, vector_store
                )
                
                if chunks_added > 0:
                    total_chunks += chunks_added
                    successful_listings += 1
            
            print(f"\n   📄 {listings_with_docs_count} listings have property documents")
            
            if listings_with_docs_count == 0:
                print("\n⚠️  No listings with property documents found in database")
                print("   Make sure:")
                print("   1. property_media table has records with category = 'other' or 'floor_plan'")
                print("   2. media_metadata table has corresponding records with file_type = 'pdf'")
                print("   3. property_media.is_public = true")
                return
            
            # Show final stats
            _print_statistics(listings_with_docs_count, successful_listings, total_chunks, vector_store)
            print("\n✓ Property PDF sync complete!")


def test_property_document_search(listing_id: str) -> None:
    """
    Test search for property documents.
    
    Args:
        listing_id: Listing ID to search
    """
    print("\n" + "=" * SEPARATOR_LENGTH)
    print(f"Testing Property Document Search for Listing: {listing_id}")
    print("=" * SEPARATOR_LENGTH)
    
    # Test queries
    test_queries = [
        "floor plan",
        "contract details",
        "property disclosure",
        "building specifications"
    ]
    
    with PgVectorStore() as vector_store:
        for query in test_queries:
            print(f"\n🔍 Query: {query}")
            results = vector_store.search(
                query=query,
                listing_id=listing_id,
                chunk_types=['property_document'],
                n_results=3
            )
            
            if results:
                print(f"   Found {len(results)} property document chunks:")
                for i, result in enumerate(results, 1):
                    similarity = result.get('similarity', 0.0)
                    metadata = result.get('metadata', {})
                    content = result.get('content', '')
                    
                    print(f"\n   {i}. Similarity: {similarity:.4f}")
                    print(f"      File: {metadata.get('file_name', 'N/A')}")
                    print(f"      Content preview: {content[:CONTENT_PREVIEW_LENGTH]}...")
            else:
                print("   No property document chunks found")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Sync property PDFs to vector store")
    parser.add_argument(
        '--listing-id', 
        type=str, 
        help="Sync specific listing ID"
    )
    parser.add_argument(
        '--test', 
        action='store_true', 
        help="Run search tests after sync"
    )
    args = parser.parse_args()
    
    # Run sync
    listing_ids = [args.listing_id] if args.listing_id else None
    sync_property_pdfs(listing_ids)
    
    # Run tests if requested
    if args.test and args.listing_id:
        test_property_document_search(args.listing_id)

