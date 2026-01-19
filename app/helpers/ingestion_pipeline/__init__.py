"""
Ingestion pipeline for processing property listings into vector embeddings.
Now using pgvector (PostgreSQL native vector storage).
"""
from app.helpers.ingestion_pipeline.property.formatters import format_listing_for_chunking
from app.helpers.ingestion_pipeline.shared.chunker import PropertyListingChunker, Chunk
from app.helpers.ingestion_pipeline.property.pgvector_store import PgVectorStore

__all__ = [
    'format_listing_for_chunking',
    'PropertyListingChunker',
    'Chunk',
    'PgVectorStore',
]

