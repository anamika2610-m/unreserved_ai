"""
API endpoints for syncing vector embeddings with database listings.
These endpoints can be called via webhook when listings are added/updated.
"""
import os
import shutil
import tempfile
from typing import List, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks, Header, UploadFile, File, Form

from app.core.exceptions import (
    BadRequestError,
    InternalServerError,
    UnauthorizedError,
)
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


class GenericPDFUploadResponse(BaseModel):
    status: str
    message: str
    files_received: int
    files_rejected: int
    documents_processed: int
    documents_skipped: int
    chunks_created: int


# Webhook secret for security
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET") or os.getenv("REQUIRE_WEBHOOK_SECRET")
REQUIRE_WEBHOOK_SECRET = os.getenv("REQUIRE_WEBHOOK_SECRET", "true").lower() == "true"


def verify_webhook_secret(x_webhook_secret: Optional[str] = Header(None)):
    """
    Verify webhook secret for security.
    
    In development (REQUIRE_WEBHOOK_SECRET=false), secret is optional.
    In production (REQUIRE_WEBHOOK_SECRET=true), secret is required and must match WEBHOOK_SECRET.
    
    Environment variables:
    - REQUIRE_WEBHOOK_SECRET: "true" or "false" (default: "true")
    - WEBHOOK_SECRET: The actual secret value (can also be set via REQUIRE_WEBHOOK_SECRET for backwards compatibility)
    """
    # If explicitly disabled, allow all requests
    if not REQUIRE_WEBHOOK_SECRET:
        # Development mode - secret is optional
        return
    
    # Check if webhook secret is configured
    if not WEBHOOK_SECRET or WEBHOOK_SECRET == "true":
        # Secret not properly configured - either missing or set to "true" (boolean flag instead of actual secret)
        raise InternalServerError(
            detail="Webhook secret not configured. Set WEBHOOK_SECRET environment variable."
        )
    
    # Verify the provided secret matches
    if x_webhook_secret != WEBHOOK_SECRET:
        raise UnauthorizedError(detail="Invalid webhook secret")


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
        embedding_model="text-embedding-3-small"
    )
    
    # IMPORTANT: We no longer clear all embeddings from this endpoint.
    # `clear_existing` is accepted for backwards compatibility, but ignored
    # to ensure vector embeddings persist across syncs.
    if clear_existing:
        print(
            "ℹ️  clear_existing was requested, but full reset of embeddings is "
            "disabled to preserve existing vectors. Run a manual maintenance "
            "job if you truly need to wipe the vector store."
        )
    
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
        raise InternalServerError(detail=f"Sync failed: {str(e)}")


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
# @router.post("/trigger", response_model=SyncResponse, include_in_schema=False)
# async def trigger_sync(
#     request: SyncRequest,
#     background_tasks: BackgroundTasks,
#     x_webhook_secret: Optional[str] = Header(None),
# ):
#     """Deprecated alias of `POST /api/v1/sync/listings`."""
#     return await _sync_listings_handler(request=request, x_webhook_secret=x_webhook_secret)


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


# # Backward-compatible alias (old name)
# @router.post("/trigger-async", response_model=dict, include_in_schema=False)
# async def trigger_sync_async(
#     request: SyncRequest,
#     background_tasks: BackgroundTasks,
#     x_webhook_secret: Optional[str] = Header(None),
# ):
#     """Deprecated alias of `POST /api/v1/sync/listings-async`."""
#     return await sync_listings_async(
#         request=request,
#         background_tasks=background_tasks,
#         x_webhook_secret=x_webhook_secret,
#     )


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
        raise InternalServerError(detail=f"Failed to get status: {str(e)}")


@contextmanager
def get_db_session():
    """Sync context manager for database session (used by non-repo sync functions)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def perform_property_pdf_sync(listing_ids: Optional[List[str]] = None) -> dict:
    """
    Perform property PDF sync operation.
    
    Args:
        listing_ids: Optional list of listing IDs to sync
        
    Returns:
        Dictionary with sync results
    """
    from app.db.connection import get_session_maker
    
    DEFAULT_CHUNK_SIZE = 500
    
    session_maker = get_session_maker()
    async with session_maker() as db:
        listing_repo = ListingRepository(db)
        pdf_processor = PropertyPDFProcessor(chunk_size=DEFAULT_CHUNK_SIZE)
        
        with PgVectorStore() as vector_store:
            # Fetch listings
            if listing_ids:
                listings = await listing_repo.fetch_listings(
                    listing_ids=listing_ids,
                    listing_status=None
                )
            else:
                listings = await listing_repo.fetch_listings(
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
                property_docs = await listing_repo.fetch_property_documents(listing_id)
                
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
        raise InternalServerError(detail=f"Generic PDF sync failed: {str(e)}")
    finally:
        knowledge_store.close()


@router.post("/generic-pdfs/upload", response_model=GenericPDFUploadResponse)
async def sync_generic_pdfs_upload(
    background_tasks: BackgroundTasks,
    x_webhook_secret: Optional[str] = Header(None),
    files: List[UploadFile] = File(..., description="One or more text-based PDF files (no scanned/image-only PDFs)."),
    re_index: bool = Form(False, description="If true, re-index documents (replace existing chunks for these files)."),
    category: Optional[str] = Form(None, description="Optional category label for uploaded documents (default: uploads)."),
):
    """
    Upload one or more **text** PDFs and sync them into `generic_knowledge`.

    - Rejects scanned/image-only PDFs (must have extractable text).
    - Enforces file size and max file count limits via env vars:
      - GENERIC_PDF_MAX_MB (default: 20)
      - GENERIC_PDF_MAX_FILES (default: 10)
    """
    verify_webhook_secret(x_webhook_secret)

    # CRITICAL: Validate BEFORE any file processing
    max_mb, max_files = _get_generic_upload_limits()
    
    # Check 1: Max file count limit
    if len(files) > max_files:
        error_msg = f"Too many files. Max allowed: {max_files}, received: {len(files)}"
        print(f"❌ File upload rejected: {error_msg}")
        raise BadRequestError(detail=error_msg)

    # Check 2: File extension validation - reject if ANY non-PDF is found
    rejected_files = []
    for f in files:
        name = (f.filename or "").strip()
        if not name:
            rejected_files.append("(no filename)")
        elif not name.lower().endswith(".pdf"):
            rejected_files.append(name)
    
    if rejected_files:
        error_msg = f"Only PDF files are allowed. Rejected files: {', '.join(rejected_files)}"
        print(f"❌ File upload rejected: {error_msg}")
        raise BadRequestError(detail=error_msg)

    # Only proceed if ALL validations pass
    # Stage uploads to a temp directory we can clean up after processing
    tmp_dir = Path(tempfile.mkdtemp(prefix="generic_pdfs_"))
    max_bytes = max_mb * 1024 * 1024

    accepted_paths: List[Path] = []
    rejected = 0

    try:
        for f in files:
            name = (f.filename or "").strip()
            
            # Double-check validation (safety net)
            if not name or not name.lower().endswith(".pdf"):
                print(f"⚠️  WARNING: Invalid file detected during processing: {name}")
                rejected += 1
                continue

            dest = tmp_dir / name
            try:
                _save_upload_to_disk(f, dest, max_bytes=max_bytes)
                accepted_paths.append(dest)
            except ValueError as e:
                print(f"⚠️  File rejected (size limit): {name}")
                rejected += 1
            except Exception as e:
                print(f"⚠️  File rejected (error): {name} - {str(e)}")
                rejected += 1

        if not accepted_paths:
            # Clean temp dir immediately
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                pass
            raise BadRequestError(detail="No valid PDF files received (check file type/size).")

        result = perform_generic_pdf_sync_from_files(
            pdf_paths=accepted_paths,
            re_index=re_index,
            category=category,
            cleanup_dir=tmp_dir,
        )
        return GenericPDFUploadResponse(
            status=result["status"],
            message=result["message"],
            files_received=len(files),
            files_rejected=rejected,
            documents_processed=result["documents_processed"],
            documents_skipped=result["documents_skipped"],
            chunks_created=result["chunks_created"],
        )
    except HTTPException:
        raise
    except Exception as e:
        # Best-effort cleanup
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass
        raise InternalServerError(detail=f"Generic PDF upload sync failed: {str(e)}")


@router.post("/generic-pdfs/upload-async", response_model=dict)
async def sync_generic_pdfs_upload_async(
    background_tasks: BackgroundTasks,
    x_webhook_secret: Optional[str] = Header(None),
    files: List[UploadFile] = File(..., description="One or more text-based PDF files (no scanned/image-only PDFs)."),
    re_index: bool = Form(False, description="If true, re-index documents (replace existing chunks for these files)."),
    category: Optional[str] = Form(None, description="Optional category label for uploaded documents (default: uploads)."),
):
    """
    Async version of `/generic-pdfs/upload`.
    Immediately returns and processes the PDFs in a background task.
    """
    verify_webhook_secret(x_webhook_secret)

    # CRITICAL: Validate BEFORE any file processing
    max_mb, max_files = _get_generic_upload_limits()
    
    # Check 1: Max file count limit
    if len(files) > max_files:
        error_msg = f"Too many files. Max allowed: {max_files}, received: {len(files)}"
        print(f"❌ File upload rejected: {error_msg}")
        raise BadRequestError(detail=error_msg)

    # Check 2: File extension validation - reject if ANY non-PDF is found
    rejected_files = []
    for f in files:
        name = (f.filename or "").strip()
        if not name:
            rejected_files.append("(no filename)")
        elif not name.lower().endswith(".pdf"):
            rejected_files.append(name)
    
    if rejected_files:
        error_msg = f"Only PDF files are allowed. Rejected files: {', '.join(rejected_files)}"
        print(f"❌ File upload rejected: {error_msg}")
        raise BadRequestError(detail=error_msg)

    # Only proceed if ALL validations pass
    tmp_dir = Path(tempfile.mkdtemp(prefix="generic_pdfs_"))
    max_bytes = max_mb * 1024 * 1024

    accepted_paths: List[Path] = []
    rejected = 0

    for f in files:
        name = (f.filename or "").strip()
        
        # Double-check validation (safety net)
        if not name or not name.lower().endswith(".pdf"):
            print(f"⚠️  WARNING: Invalid file detected during processing: {name}")
            rejected += 1
            continue
            
        dest = tmp_dir / name
        try:
            _save_upload_to_disk(f, dest, max_bytes=max_bytes)
            accepted_paths.append(dest)
        except ValueError as e:
            print(f"⚠️  File rejected (size limit): {name}")
            rejected += 1
        except Exception as e:
            print(f"⚠️  File rejected (error): {name} - {str(e)}")
            rejected += 1

    if not accepted_paths:
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass
        raise BadRequestError(detail="No valid PDF files received (check file type/size).")

    # Run in background; cleanup_dir deletes temp files at the end.
    background_tasks.add_task(
        perform_generic_pdf_sync_from_files,
        accepted_paths,
        re_index,
        category,
        tmp_dir,
    )

    return {
        "status": "accepted",
        "message": "Generic PDF upload sync started in background",
        "files_received": len(files),
        "files_rejected": rejected,
        "max_mb_per_file": max_mb,
        "max_files": max_files,
    }


def _get_generic_upload_limits() -> tuple[int, int]:
    """
    Return (max_mb_per_file, max_files) limits for generic PDF upload.
    """
    max_mb = int(os.getenv("GENERIC_PDF_MAX_MB", "20"))
    max_files = int(os.getenv("GENERIC_PDF_MAX_FILES", "10"))
    return max_mb, max_files


def _save_upload_to_disk(file: UploadFile, dest_path: Path, max_bytes: int) -> int:
    """
    Save UploadFile to disk enforcing a hard max_bytes limit.
    Returns bytes written.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(dest_path, "wb") as out:
        while True:
            chunk = file.file.read(1024 * 1024)  # 1MB
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                raise ValueError("File too large")
            out.write(chunk)
    return written


def perform_generic_pdf_sync_from_files(
    pdf_paths: List[Path],
    re_index: bool = False,
    category: Optional[str] = None,
    cleanup_dir: Optional[Path] = None,
) -> dict:
    """
    Perform generic PDF sync operation for a provided list of PDF files.
    Validates that each PDF has extractable text (rejects scanned/image-only PDFs).
    """
    from app.helpers.ingestion_pipeline.generic.sync_generic_pdfs import compute_content_hash
    from app.helpers.ingestion_pipeline.generic.generic_knowledge_store import GenericChunk
    from sqlalchemy import text as sql_text

    DEFAULT_CHUNK_SIZE = 500
    DEFAULT_CHUNK_OVERLAP = 50

    pdf_processor = PDFProcessor(chunk_size=DEFAULT_CHUNK_SIZE)
    knowledge_store = GenericKnowledgeStore()

    try:
        knowledge_store.initialize_table()

        total_chunks = 0
        processed_docs = 0
        skipped_docs = 0

        for pdf_path in pdf_paths:
            try:
                # Use a stable "file_path" identifier for de-dupe and auditing
                safe_name = pdf_path.name
                doc_category = (category or "uploads").lower().strip() or "uploads"
                metadata = {
                    "title": Path(safe_name).stem,
                    "file_name": safe_name,
                    "file_path": f"uploads/{safe_name}",
                    "category": doc_category,
                    "type": "generic_knowledge",
                }

                text = pdf_processor.extract_from_file(str(pdf_path))
                if not text:
                    # No extracted text => scanned/image-only (or corrupted)
                    skipped_docs += 1
                    continue

                content_hash = compute_content_hash(text)
                metadata["content_hash"] = content_hash

                # If not re-indexing, skip unchanged docs, else replace
                check_query = sql_text("""
                    SELECT COUNT(*) FROM generic_knowledge
                    WHERE metadata->>'file_path' = :file_path
                    AND metadata->>'content_hash' = :content_hash
                """)
                result = knowledge_store.db_session.execute(
                    check_query,
                    {"file_path": metadata["file_path"], "content_hash": content_hash},
                )
                existing_count = result.scalar() or 0

                if not re_index and existing_count > 0:
                    skipped_docs += 1
                    continue

                # Remove old chunks for this file_path (changed/new or re_index)
                delete_query = sql_text("""
                    DELETE FROM generic_knowledge
                    WHERE metadata->>'file_path' = :file_path
                """)
                knowledge_store.db_session.execute(delete_query, {"file_path": metadata["file_path"]})
                knowledge_store.db_session.commit()

                text = pdf_processor.clean_text(text)
                text_chunks = pdf_processor.chunk_text(text, overlap=DEFAULT_CHUNK_OVERLAP)

                chunks: List[GenericChunk] = []
                for idx, chunk_text in enumerate(text_chunks):
                    chunk_metadata = {
                        **metadata,
                        "chunk_index": idx,
                        "total_chunks": len(text_chunks),
                    }
                    chunks.append(
                        GenericChunk(
                            content=chunk_text,
                            doc_category=doc_category,
                            chunk_index=idx,
                            metadata=chunk_metadata,
                        )
                    )

                added_count = knowledge_store.add_chunks(chunks)
                total_chunks += added_count
                processed_docs += 1

            except Exception as e:
                print(f"Error processing uploaded PDF {pdf_path}: {e}")
                skipped_docs += 1
                continue

        return {
            "status": "success",
            "message": f"Successfully synced {processed_docs} uploaded generic PDF document(s)",
            "documents_processed": processed_docs,
            "documents_skipped": skipped_docs,
            "chunks_created": total_chunks,
        }
    finally:
        knowledge_store.close()
        if cleanup_dir and cleanup_dir.exists():
            try:
                shutil.rmtree(cleanup_dir)
            except Exception:
                pass


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
        result = await perform_property_pdf_sync(listing_ids=request.listing_ids)
        return PropertyPDFSyncResponse(**result)
    except Exception as e:
        raise InternalServerError(detail=f"Property PDF sync failed: {str(e)}")


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
        raise InternalServerError(detail=f"Generic PDF sync failed: {str(e)}")


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



