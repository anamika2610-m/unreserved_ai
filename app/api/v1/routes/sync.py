"""
API endpoints for syncing vector embeddings with database listings.
These endpoints can be called via webhook when listings are added/updated.
"""
import os
from typing import List, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks, Header
from pydantic import BaseModel, Field

from app.helpers.ingestion_pipeline.property.db_loader import fetch_listings_from_db
from app.helpers.ingestion_pipeline.shared.chunker import PropertyListingChunker
from app.helpers.ingestion_pipeline.property.pgvector_store import PgVectorStore


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


# Webhook secret for security
WEBHOOK_SECRET = os.getenv("VECTOR_SYNC_WEBHOOK_SECRET", "change-me-in-production")


def verify_webhook_secret(x_webhook_secret: Optional[str] = Header(None)):
    """Verify webhook secret for security."""
    if WEBHOOK_SECRET != "change-me-in-production" and x_webhook_secret != WEBHOOK_SECRET:
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


@router.post("/trigger", response_model=SyncResponse)
async def trigger_sync(
    request: SyncRequest,
    background_tasks: BackgroundTasks,
    x_webhook_secret: Optional[str] = Header(None)
):
    """
    Trigger a sync of vector embeddings from database listings.
    
    This endpoint can be called via webhook when listings are added or updated.
    The sync runs in the background to avoid blocking the webhook response.
    
    **Security**: Requires X-Webhook-Secret header matching VECTOR_SYNC_WEBHOOK_SECRET env var.
    
    **Usage**:
    ```bash
    curl -X POST "http://localhost:8000/api/v1/sync/trigger" \\
         -H "Content-Type: application/json" \\
         -H "X-Webhook-Secret: your-secret-here" \\
         -d '{"listing_ids": ["uuid-1", "uuid-2"], "clear_existing": false}'
    ```
    """
    # Verify webhook secret
    verify_webhook_secret(x_webhook_secret)
    
    try:
        # Perform sync in background
        result = perform_sync(
            listing_ids=request.listing_ids,
            clear_existing=request.clear_existing
        )
        
        return SyncResponse(**result)
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Sync failed: {str(e)}"
        )


@router.post("/trigger-async", response_model=dict)
async def trigger_sync_async(
    request: SyncRequest,
    background_tasks: BackgroundTasks,
    x_webhook_secret: Optional[str] = Header(None)
):
    """
    Trigger a sync in the background and return immediately.
    
    Useful for webhooks that have timeout constraints.
    The sync will continue in the background after the response is sent.
    
    **Security**: Requires X-Webhook-Secret header matching VECTOR_SYNC_WEBHOOK_SECRET env var.
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



