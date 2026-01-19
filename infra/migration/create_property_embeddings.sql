-- Create property_embeddings table for pgvector
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS property_embeddings (
    id VARCHAR PRIMARY KEY,
    listing_id VARCHAR NOT NULL,
    chunk_type VARCHAR NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    metadata JSONB
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_listing_id ON property_embeddings(listing_id);
CREATE INDEX IF NOT EXISTS idx_chunk_type ON property_embeddings(chunk_type);
CREATE INDEX IF NOT EXISTS idx_embedding_cosine ON property_embeddings 
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Verify table creation
SELECT 'property_embeddings table created successfully' AS status;

