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
import logging
import sys
import traceback
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from dotenv import load_dotenv
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Add project root to path
# File location: app/helpers/ingestion_pipeline/property/sync_property_pdfs.py
# Project root is 5 levels up (property -> ingestion_pipeline -> helpers -> app -> project_root)
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root.resolve()))

from app.db.session import SessionLocal
from app.db.postgres.repositories import SyncListingRepository
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
    repo: SyncListingRepository,
    listing_ids: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Fetch listings from database.
    
    Args:
        repo: SyncListingRepository
        listing_ids: Optional list of specific listing IDs

    Returns:
        List of listing dictionaries
    """
    logger.info("📊 Fetching listings from database via SyncListingRepository...")
    if listing_ids:
        listings = repo.fetch_listings(
            listing_ids=listing_ids,
            listing_status=None,  # Don't filter by status for specific listings
        )
        logger.info("   ✓ Fetched %d specified listings", len(listings))
    else:
        listings = repo.fetch_listings(listing_status="active")
        logger.info("   ✓ Fetched %d active listings", len(listings))

    return listings


def _fetch_property_documents(repo: SyncListingRepository, listing_id: str) -> List[Dict[str, Any]]:
    """
    Fetch PUBLIC PDF documents for a listing using the sync session.

    Mirrors ListingRepository.fetch_property_documents but uses SyncListingRepository.
    """
    query_str = """
        SELECT 
            pm.id,
            pm.display_order as "displayOrder",
            pm.category,
            mm.id as "metadataId",
            mm.file_name as "fileName",
            mm.file_url as "fileUrl",
            mm.file_type as "fileType",
            mm.alt_text as "altText"
        FROM listings l
        LEFT JOIN properties p ON l.property_id = p.id
        LEFT JOIN property_media pm ON p.id = pm.property_id
        LEFT JOIN media_metadata mm ON pm.file_id = mm.id
        WHERE l.id = :listing_id
        AND pm.category IN ('floor_plan', 'other')
        AND pm.is_public = true
        AND mm.file_type = 'pdf'
        ORDER BY pm.display_order
    """

    result = repo.session.execute(text(query_str), {"listing_id": listing_id})
    rows = result.fetchall()

    documents: List[Dict[str, Any]] = []
    for row in rows:
        row_dict = dict(row._mapping)
        documents.append(
            {
                "id": row_dict.get("id"),
                "displayOrder": row_dict.get("displayOrder"),
                "mediaMetadata": {
                    "id": row_dict.get("metadataId"),
                    "fileName": row_dict.get("fileName"),
                    "fileUrl": row_dict.get("fileUrl"),
                    "fileType": row_dict.get("fileType"),
                    "altText": row_dict.get("altText"),
                },
            }
        )

    return documents


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
    logger.info("📍 Listing: %s", listing_id)
    logger.info("   Title: %s", listing.get('title', 'N/A'))
    
    # Show document summary
    summary = pdf_processor.get_document_summary(property_docs)
    logger.info("   Documents: %d total", summary['total'])
    for file_type, count in summary['by_type'].items():
        logger.info("      - %s: %d", file_type, count)
    
    try:
        # Process documents
        chunks = pdf_processor.process_property_documents(listing_id, property_docs)
        
        if not chunks:
            logger.warning("   ⚠️  No chunks generated")
            return 0
        
        db_doc_info = {}
        for chunk in chunks:
            doc_id = chunk.metadata.get("doc_id") if chunk.metadata else None
            if doc_id:
                db_doc_info[str(doc_id)] = {
                    "total_chunks": chunk.metadata.get("total_chunks", 1) if chunk.metadata else 1
                }
        
        # Use efficient sync with list comparison
        logger.info("   💾 Syncing %d chunks to property_embeddings...", len(chunks))
        sync_result = vector_store.sync_property_documents(
            listing_id=str(listing_id),
            chunks=chunks,
            db_doc_info=db_doc_info
        )
        
        logger.info("   ✓ Added %d chunks, deleted %d orphan chunks", sync_result.get('added', 0), sync_result.get('deleted', 0))
        return sync_result.get('added', 0)
    
    except Exception as e:
        logger.error("❌ Failed to process listing %s: %s", listing_id, e)
        logger.error(traceback.format_exc())
        return 0


def _print_statistics(
    listings_with_docs_count: int,
    successful_listings: int,
    total_chunks: int,
    vector_store: PgVectorStore
) -> None:
    """Print sync statistics."""
    logger.info("=" * SEPARATOR_LENGTH)
    logger.info("📊 Sync Statistics")
    logger.info("=" * SEPARATOR_LENGTH)
    logger.info("Listings with documents: %d", listings_with_docs_count)
    logger.info("Listings processed: %d/%d", successful_listings, listings_with_docs_count)
    logger.info("Total chunks added: %d", total_chunks)
    
    # Show vector store stats
    stats = vector_store.get_stats()
    logger.info("Vector Store Stats:")
    logger.info("  Total embeddings: %d", stats.get('total', 0))
    if 'chunk_types' in stats:
        logger.info("  Chunk types:")
        for chunk_type, count in stats['chunk_types'].items():
            logger.info("     - %s: %d", chunk_type, count)


def sync_property_pdfs(listing_ids: Optional[List[str]] = None) -> None:
    """
    Sync property PDFs for specified listings.
    Fetches property documents from database via repository layer.
    
    Args:
        listing_ids: Optional list of listing IDs to sync. If None, sync all active listings.
    """
    logger.info("=" * SEPARATOR_LENGTH)
    logger.info("Property PDF Sync to property_embeddings (via Repository)")
    logger.info("=" * SEPARATOR_LENGTH)
    
    with get_db_session() as db:
        repo = SyncListingRepository(db)

        # Initialize processors
        pdf_processor = PropertyPDFProcessor(chunk_size=DEFAULT_CHUNK_SIZE)

        # Use context manager for vector store to ensure proper cleanup
        with PgVectorStore() as vector_store:
            # Fetch listings from database
            listings = _fetch_listings(repo, listing_ids)
            
            # Process each listing and fetch property documents
            total_chunks = 0
            successful_listings = 0
            listings_with_docs_count = 0
            
            for listing in listings:
                listing_id = listing.get('id')
                
                # Fetch property documents from database
                property_docs = _fetch_property_documents(repo, listing_id)
                
                if not property_docs:
                    continue
                
                listings_with_docs_count += 1
                chunks_added = _process_listing_documents(
                    listing_id, listing, property_docs, pdf_processor, vector_store
                )
                
                if chunks_added > 0:
                    total_chunks += chunks_added
                    successful_listings += 1
            
            logger.info("📄 %d listings have property documents", listings_with_docs_count)
            
            if listings_with_docs_count == 0:
                logger.warning("⚠️  No listings with property documents found in database")
                logger.warning("   Make sure:")
                logger.warning("   1. property_media table has records with category = 'other' or 'floor_plan'")
                logger.warning("   2. media_metadata table has corresponding records with file_type = 'pdf'")
                logger.warning("   3. property_media.is_public = true")
                return
            
            # Show final stats
            _print_statistics(listings_with_docs_count, successful_listings, total_chunks, vector_store)
            logger.info("✓ Property PDF sync complete!")


def test_property_document_search(listing_id: str) -> None:
    """
    Test search for property documents.
    
    Args:
        listing_id: Listing ID to search
    """
    logger.info("=" * SEPARATOR_LENGTH)
    logger.info("Testing Property Document Search for Listing: %s", listing_id)
    logger.info("=" * SEPARATOR_LENGTH)
    
    # Test queries
    test_queries = [
        "floor plan",
        "contract details",
        "property disclosure",
        "building specifications"
    ]
    
    with PgVectorStore() as vector_store:
        for query in test_queries:
            logger.info("🔍 Query: %s", query)
            results = vector_store.search(
                query=query,
                listing_id=listing_id,
                chunk_types=['property_document'],
                n_results=3
            )
            
            if results:
                logger.info("   Found %d property document chunks:", len(results))
                for i, result in enumerate(results, 1):
                    similarity = result.get('similarity', 0.0)
                    metadata = result.get('metadata', {})
                    content = result.get('content', '')
                    
                    logger.info("   %d. Similarity: %.4f", i, similarity)
                    logger.info("      File: %s", metadata.get('file_name', 'N/A'))
                    logger.info("      Content preview: %s...", content[:CONTENT_PREVIEW_LENGTH])
            else:
                logger.info("   No property document chunks found")


if __name__ == "__main__":
    import argparse
    
    # Configure logging when running as script
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
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

