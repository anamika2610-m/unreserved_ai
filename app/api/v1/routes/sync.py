"""
API endpoints for syncing vector embeddings with database listings.
These endpoints can be called via webhook when listings are added/updated.
"""
import os
from typing import List, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks, Header
from pydantic import BaseModel, Field
from contextlib import contextmanager

from app.helpers.ingestion_pipeline.property.db_loader import fetch_listings_from_db
from app.helpers.ingestion_pipeline.shared.chunker import PropertyListingChunker
from app.helpers.ingestion_pipeline.property.pgvector_store import PgVectorStore
from app.db.session import SessionLocal
from app.db.postgres.repositories import ListingRepository
from app.helpers.ingestion_pipeline.property.property_pdf_processor import PropertyPDFProcessor
from app.helpers.ingestion_pipeline.shared.pdf_processor import PDFProcessor
from app.helpers.ingestion_pipeline.generic.generic_knowledge_store import GenericKnowledgeStore
from pathlib import Path


router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


# Request/Response models
class SyncRequest(BaseModel):
    listing_ids: Optional[List[str]] = Field(
        None,
        description="Optional list of specific listing IDs to sync. If not provided, syncs all active listings."
    )
    clear_existing: bool = Field(
        False,
        description="If true, clears all existing embeddings before syncing."
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "listing_ids": ["uuid-1", "uuid-2"],
                "clear_existing": False
            }
        }


class SyncResponse(BaseModel):
    status: str = Field(..., description="Status of the sync operation")
    message: str = Field(..., description="Human-readable message")
    listings_synced: int = Field(..., description="Number of listings synced")
    chunks_created: int = Field(..., description="Number of chunks created")
    total_embeddings: int = Field(..., description="Total embeddings in vector store")


class SyncStatusResponse(BaseModel):
    collection_name: str
    total_embeddings: int
    embedding_model: str
    metadata: dict


class PropertyPDFSyncRequest(BaseModel):
    listing_ids: Optional[List[str]] = Field(
        None,
        description="Optional list of specific listing IDs to sync. If not provided, syncs all active listings with property documents."
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "listing_ids": ["uuid-1", "uuid-2"]
            }
        }


class PropertyPDFSyncResponse(BaseModel):
    status: str
    message: str
    listings_processed: int
    listings_with_docs: int
    chunks_created: int


class GenericPDFSyncRequest(BaseModel):
    re_index: bool = Field(
        False,
        description="If true, clears existing chunks and re-indexes all documents. If false, only adds new/updated documents."
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "re_index": False
            }
        }


class GenericPDFSyncResponse(BaseModel):
    status: str
    message: str
    documents_processed: int
    documents_skipped: int
    chunks_created: int


# Webhook secret for security
WEBHOOK_SECRET = os.getenv("VECTOR_SYNC_WEBHOOK_SECRET", "change-me-in-production")
REQUIRE_WEBHOOK_SECRET = os.getenv("REQUIRE_WEBHOOK_SECRET", "true").lower() == "true"


def verify_webhook_secret(x_webhook_secret: Optional[str] = Header(None)):
    """
    Verify webhook secret for security.
    
    In development (REQUIRE_WEBHOOK_SECRET=false), secret is optional.
    In production (REQUIRE_WEBHOOK_SECRET=true), secret is required.
    """
    if not REQUIRE_WEBHOOK_SECRET:
        # Development mode - secret is optional
        return
    
    if WEBHOOK_SECRET == "change-me-in-production":
        # Default secret in production is a security risk
        raise HTTPException(
            status_code=500,
            detail="Webhook secret not configured. Set VECTOR_SYNC_WEBHOOK_SECRET environment variable."
        )
    
    if x_webhook_secret != WEBHOOK_SECRET:
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook secret"
        )


def perform_sync(
    listing_ids: Optional[List[str]] = None,
    clear_existing: bool = False
) -> dict:
    """
    Perform the actual sync operation.
    
    Args:
        listing_ids: Optional list of listing IDs to sync
        clear_existing: Whether to clear existing embeddings
        
    Returns:
        Dictionary with sync results
    """
    # Fetch listings from database
    listings = fetch_listings_from_db(
        listing_ids=listing_ids,
        listing_status="active" if not listing_ids else None
    )
    
    if not listings:
        return {
            "status": "success",
            "message": "No listings found to sync",
            "listings_synced": 0,
            "chunks_created": 0,
            "total_embeddings": 0
        }
    
    # Chunk the listings
    chunker = PropertyListingChunker()
    all_chunks = chunker.chunk_all_listings(listings)
    
    # Initialize pgvector store
    vector_store = PgVectorStore(
        embedding_model="all-MiniLM-L6-v2"
    )
    
    # Clear if explicitly requested (WARNING: deletes ALL embeddings including property_document chunks!)
    if clear_existing:
        print("⚠️  WARNING: Clearing all embeddings (including property_document chunks)")
        vector_store.clear_all()
    
    # Add chunks
    vector_store.add_chunks(all_chunks)
    
    # Get final stats
    stats = vector_store.get_stats()
    
    return {
        "status": "success",
        "message": f"Successfully synced {len(listings)} listings",
        "listings_synced": len(listings),
        "chunks_created": len(all_chunks),
        "total_embeddings": stats["total_chunks"]
    }


async def _sync_listings_handler(
    request: SyncRequest,
    x_webhook_secret: Optional[str],
) -> SyncResponse:
    # Verify webhook secret
    verify_webhook_secret(x_webhook_secret)
    try:
        result = perform_sync(
            listing_ids=request.listing_ids,
            clear_existing=request.clear_existing,
        )
        return SyncResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


@router.post("/listings", response_model=SyncResponse)
async def sync_listings(
    request: SyncRequest,
    background_tasks: BackgroundTasks,
    x_webhook_secret: Optional[str] = Header(None)
):
    """
    Sync vector embeddings for **property listing details** (structured listing JSON → chunks → `property_embeddings`).
    
    This endpoint can be called via webhook when listings are added or updated.
    The sync runs in the background to avoid blocking the webhook response.
    
    **Security**: Requires `X-Webhook-Secret` header (unless `REQUIRE_WEBHOOK_SECRET=false` in development).
    
    **Usage**:
    ```bash
    curl -X POST "http://localhost:8000/api/v1/sync/listings" \\
         -H "Content-Type: application/json" \\
         -H "X-Webhook-Secret: your-secret-here" \\
         -d '{"listing_ids": ["uuid-1", "uuid-2"], "clear_existing": false}'
    ```
    """
    return await _sync_listings_handler(request=request, x_webhook_secret=x_webhook_secret)


# Backward-compatible alias (old name)
@router.post("/trigger", response_model=SyncResponse, include_in_schema=False)
async def trigger_sync(
    request: SyncRequest,
    background_tasks: BackgroundTasks,
    x_webhook_secret: Optional[str] = Header(None),
):
    """Deprecated alias of `POST /api/v1/sync/listings`."""
    return await _sync_listings_handler(request=request, x_webhook_secret=x_webhook_secret)


@router.post("/listings-async", response_model=dict)
async def sync_listings_async(
    request: SyncRequest,
    background_tasks: BackgroundTasks,
    x_webhook_secret: Optional[str] = Header(None)
):
    """
    Trigger a sync in the background and return immediately.
    
    Useful for webhooks that have timeout constraints.
    The sync will continue in the background after the response is sent.
    
    **Security**: Requires `X-Webhook-Secret` header (unless `REQUIRE_WEBHOOK_SECRET=false` in development).
    """
    # Verify webhook secret
    verify_webhook_secret(x_webhook_secret)
    
    # Schedule sync to run in background
    background_tasks.add_task(
        perform_sync,
        listing_ids=request.listing_ids,
        clear_existing=request.clear_existing
    )
    
    return {
        "status": "accepted",
        "message": "Sync job queued and will run in background",
        "listing_ids": request.listing_ids,
        "clear_existing": request.clear_existing
    }


# Backward-compatible alias (old name)
@router.post("/trigger-async", response_model=dict, include_in_schema=False)
async def trigger_sync_async(
    request: SyncRequest,
    background_tasks: BackgroundTasks,
    x_webhook_secret: Optional[str] = Header(None),
):
    """Deprecated alias of `POST /api/v1/sync/listings-async`."""
    return await sync_listings_async(
        request=request,
        background_tasks=background_tasks,
        x_webhook_secret=x_webhook_secret,
    )


@router.get("/status", response_model=SyncStatusResponse)
async def get_sync_status():
    """
    Get current status of the vector store.
    
    Returns information about the collection including total embeddings count.
    """
    try:
        vector_store = PgVectorStore(
            embedding_model="all-MiniLM-L6-v2"
        )
        
        stats = vector_store.get_stats()
        
        return SyncStatusResponse(
            collection_name="property_embeddings",  # pgvector table name
            total_embeddings=stats["total_chunks"],
            embedding_model=stats["embedding_model"],
            metadata={
                "unique_listings": stats["unique_listings"],
                "chunk_types": stats["chunk_types"],
                "vector_dimension": stats["vector_dimension"]
            }
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get status: {str(e)}"
        )


@contextmanager
def get_db_session():
    """Context manager for database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def perform_property_pdf_sync(listing_ids: Optional[List[str]] = None) -> dict:
    """
    Perform property PDF sync operation.
    
    Args:
        listing_ids: Optional list of listing IDs to sync
        
    Returns:
        Dictionary with sync results
    """
    DEFAULT_CHUNK_SIZE = 500
    
    with get_db_session() as db:
        listing_repo = ListingRepository(db)
        pdf_processor = PropertyPDFProcessor(chunk_size=DEFAULT_CHUNK_SIZE)
        
        with PgVectorStore() as vector_store:
            # Fetch listings
            if listing_ids:
                listings = listing_repo.fetch_listings(
                    listing_ids=listing_ids,
                    listing_status=None
                )
            else:
                listings = listing_repo.fetch_listings(
                    listing_ids=None,
                    listing_status="active"
                )
            
            if not listings:
                return {
                    "status": "success",
                    "message": "No listings found to sync",
                    "listings_processed": 0,
                    "listings_with_docs": 0,
                    "chunks_created": 0
                }
            
            total_chunks = 0
            successful_listings = 0
            listings_with_docs_count = 0
            
            for listing in listings:
                listing_id = listing.get('id')
                property_docs = listing_repo.fetch_property_documents(listing_id)
                
                if not property_docs:
                    continue
                
                listings_with_docs_count += 1
                
                # Process documents for this listing
                chunks = pdf_processor.process_property_documents(
                    listing_id=listing_id,
                    property_documents=property_docs
                )
                
                if chunks:
                    vector_store.add_chunks(chunks)
                    total_chunks += len(chunks)
                    successful_listings += 1
            
            return {
                "status": "success",
                "message": f"Successfully synced property PDFs for {successful_listings} listings",
                "listings_processed": len(listings),
                "listings_with_docs": listings_with_docs_count,
                "chunks_created": total_chunks
            }


def perform_generic_pdf_sync(re_index: bool = False) -> dict:
    """
    Perform generic PDF sync operation.
    
    Args:
        re_index: If True, clear and re-index all documents
        
    Returns:
        Dictionary with sync results
    """
    from app.helpers.ingestion_pipeline.generic.sync_generic_pdfs import (
        discover_pdfs, infer_metadata_from_path, compute_content_hash
    )
    from app.helpers.ingestion_pipeline.generic.generic_knowledge_store import GenericChunk
    from sqlalchemy import text as sql_text
    
    DEFAULT_CHUNK_SIZE = 500
    DEFAULT_CHUNK_OVERLAP = 50
    project_root = Path(__file__).parent.parent.parent.parent.parent
    KNOWLEDGE_BASE_DIR = project_root / "app" / "knowledge_base"
    
    pdf_processor = PDFProcessor(chunk_size=DEFAULT_CHUNK_SIZE)
    knowledge_store = GenericKnowledgeStore()
    
    try:
        knowledge_store.initialize_table()
        
        # Auto-discover PDFs
        pdf_files = discover_pdfs(KNOWLEDGE_BASE_DIR)
        
        if not pdf_files:
            return {
                "status": "success",
                "message": "No PDF files found in knowledge base directory",
                "documents_processed": 0,
                "documents_skipped": 0,
                "chunks_created": 0
            }
        
        total_chunks = 0
        processed_docs = 0
        skipped_docs = 0
        
        for pdf_path in pdf_files:
            try:
                metadata = infer_metadata_from_path(pdf_path)
                category = metadata["category"]
                file_path = metadata["file_path"]
                
                text = pdf_processor.extract_from_file(str(pdf_path))
                
                if not text:
                    skipped_docs += 1
                    continue
                
                content_hash = compute_content_hash(text)
                metadata["content_hash"] = content_hash
                
                # Check if document exists (append mode)
                if not re_index:
                    check_query = sql_text("""
                        SELECT COUNT(*) FROM generic_knowledge
                        WHERE metadata->>'file_path' = :file_path
                        AND metadata->>'content_hash' = :content_hash
                    """)
                    result = knowledge_store.db_session.execute(
                        check_query,
                        {"file_path": file_path, "content_hash": content_hash}
                    )
                    existing_count = result.scalar() or 0
                    
                    if existing_count > 0:
                        skipped_docs += 1
                        continue
                    else:
                        # Document changed or new - remove old chunks if they exist
                        delete_query = sql_text("""
                            DELETE FROM generic_knowledge
                            WHERE metadata->>'file_path' = :file_path
                        """)
                        knowledge_store.db_session.execute(delete_query, {"file_path": file_path})
                        knowledge_store.db_session.commit()
                
                # Remove existing chunks for this document if re-indexing
                if re_index:
                    delete_query = sql_text("""
                        DELETE FROM generic_knowledge
                        WHERE metadata->>'file_path' = :file_path
                    """)
                    knowledge_store.db_session.execute(delete_query, {"file_path": file_path})
                    knowledge_store.db_session.commit()
                
                # Clean and chunk text
                text = pdf_processor.clean_text(text)
                text_chunks = pdf_processor.chunk_text(text, overlap=DEFAULT_CHUNK_OVERLAP)
                
                # Create GenericChunk objects
                chunks = []
                for idx, chunk_text in enumerate(text_chunks):
                    chunk_metadata = {
                        **metadata,
                        "chunk_index": idx,
                        "total_chunks": len(text_chunks)
                    }
                    
                    chunks.append(GenericChunk(
                        content=chunk_text,
                        doc_category=category,
                        chunk_index=idx,
                        metadata=chunk_metadata
                    ))
                
                # Add chunks to store
                added_count = knowledge_store.add_chunks(chunks)
                total_chunks += added_count
                processed_docs += 1
                
            except Exception as e:
                print(f"Error processing {pdf_path}: {e}")
                skipped_docs += 1
                continue
        
        return {
            "status": "success",
            "message": f"Successfully synced {processed_docs} generic PDF documents",
            "documents_processed": processed_docs,
            "documents_skipped": skipped_docs,
            "chunks_created": total_chunks
        }
        
    except Exception as e:
        raise Exception(f"Generic PDF sync failed: {str(e)}")
    finally:
        knowledge_store.close()


@router.post("/property-pdfs", response_model=PropertyPDFSyncResponse)
async def sync_property_pdfs(
    request: PropertyPDFSyncRequest,
    background_tasks: BackgroundTasks,
    x_webhook_secret: Optional[str] = Header(None)
):
    """
    Sync property-specific PDFs to vector store.
    
    Fetches property documents from database and processes them into embeddings.
    
    **Security**: Requires X-Webhook-Secret header (unless REQUIRE_WEBHOOK_SECRET=false in development).
    
    **Usage**:
    ```bash
    curl -X POST "http://localhost:8000/api/v1/sync/property-pdfs" \\
         -H "Content-Type: application/json" \\
         -H "X-Webhook-Secret: your-secret-here" \\
         -d '{"listing_ids": ["uuid-1", "uuid-2"]}'
    ```
    """
    verify_webhook_secret(x_webhook_secret)
    
    try:
        result = perform_property_pdf_sync(listing_ids=request.listing_ids)
        return PropertyPDFSyncResponse(**result)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Property PDF sync failed: {str(e)}"
        )


@router.post("/property-pdfs-async", response_model=dict)
async def sync_property_pdfs_async(
    request: PropertyPDFSyncRequest,
    background_tasks: BackgroundTasks,
    x_webhook_secret: Optional[str] = Header(None)
):
    """
    Sync property PDFs in the background and return immediately.
    
    **Security**: Requires X-Webhook-Secret header (unless REQUIRE_WEBHOOK_SECRET=false in development).
    """
    verify_webhook_secret(x_webhook_secret)
    
    background_tasks.add_task(
        perform_property_pdf_sync,
        listing_ids=request.listing_ids
    )
    
    return {
        "status": "accepted",
        "message": "Property PDF sync job queued and will run in background",
        "listing_ids": request.listing_ids
    }


@router.post("/generic-pdfs", response_model=GenericPDFSyncResponse)
async def sync_generic_pdfs(
    request: GenericPDFSyncRequest,
    background_tasks: BackgroundTasks,
    x_webhook_secret: Optional[str] = Header(None)
):
    """
    Sync generic knowledge PDFs to vector store.
    
    Auto-discovers PDFs from app/knowledge_base/**/*.pdf and processes them.
    
    **Security**: Requires X-Webhook-Secret header (unless REQUIRE_WEBHOOK_SECRET=false in development).
    
    **Usage**:
    ```bash
    curl -X POST "http://localhost:8000/api/v1/sync/generic-pdfs" \\
         -H "Content-Type: application/json" \\
         -H "X-Webhook-Secret: your-secret-here" \\
         -d '{"re_index": false}'
    ```
    """
    verify_webhook_secret(x_webhook_secret)
    
    try:
        result = perform_generic_pdf_sync(re_index=request.re_index)
        return GenericPDFSyncResponse(**result)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Generic PDF sync failed: {str(e)}"
        )


@router.post("/generic-pdfs-async", response_model=dict)
async def sync_generic_pdfs_async(
    request: GenericPDFSyncRequest,
    background_tasks: BackgroundTasks,
    x_webhook_secret: Optional[str] = Header(None)
):
    """
    Sync generic PDFs in the background and return immediately.
    
    **Security**: Requires X-Webhook-Secret header (unless REQUIRE_WEBHOOK_SECRET=false in development).
    """
    verify_webhook_secret(x_webhook_secret)
    
    background_tasks.add_task(
        perform_generic_pdf_sync,
        re_index=request.re_index
    )
    
    return {
        "status": "accepted",
        "message": "Generic PDF sync job queued and will run in background",
        "re_index": request.re_index
    }



