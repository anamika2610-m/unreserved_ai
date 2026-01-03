"""
Ingestion pipeline for processing property listings into vector embeddings.
Now using pgvector (PostgreSQL native vector storage).
"""
from app.ingestion_pipeline.loader import load_property_listings, format_listing_for_chunking
from app.ingestion_pipeline.chunker import PropertyListingChunker, Chunk
from app.ingestion_pipeline.pgvector_store import PgVectorStore

__all__ = [
    'load_property_listings',
    'format_listing_for_chunking',
    'PropertyListingChunker',
    'Chunk',
    'PgVectorStore',
]

