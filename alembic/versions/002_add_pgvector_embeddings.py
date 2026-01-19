"""add pgvector embeddings table

Revision ID: 002
Revises: 001
Create Date: 2025-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '002'
down_revision = None  # This is the base migration
branch_labels = None
depends_on = None


def upgrade():
    # Enable pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    
    # Create property_embeddings table
    op.create_table(
        'property_embeddings',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('listing_id', sa.String(), nullable=False),
        sa.Column('chunk_type', sa.String(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', postgresql.ARRAY(sa.Float()), nullable=False),  # Will be converted to vector type
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    op.create_index('idx_listing_id', 'property_embeddings', ['listing_id'])
    op.create_index('idx_chunk_type', 'property_embeddings', ['chunk_type'])
    
    # Convert embedding column to vector type and create vector index
    op.execute('ALTER TABLE property_embeddings ALTER COLUMN embedding TYPE vector(384) USING embedding::vector(384)')
    op.execute('CREATE INDEX idx_embedding_cosine ON property_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)')


def downgrade():
    op.drop_index('idx_embedding_cosine', table_name='property_embeddings')
    op.drop_index('idx_chunk_type', table_name='property_embeddings')
    op.drop_index('idx_listing_id', table_name='property_embeddings')
    op.drop_table('property_embeddings')
    op.execute('DROP EXTENSION IF EXISTS vector')

