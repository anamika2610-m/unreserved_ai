"""update vector dimension to OpenAI embeddings

Revision ID: 005
Revises: 004
Create Date: 2025-01-12 00:00:00.000000

This migration updates vector dimensions from 384 (SentenceTransformers) 
to 1536 (OpenAI text-embedding-3-small).

IMPORTANT: After running this migration, you MUST regenerate all embeddings
using the new OpenAI embedding model. Existing embeddings will be incompatible.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade():
    """
    Upgrade vector dimensions from 384 to 1536 for OpenAI embeddings.
    
    WARNING: This will drop all existing embeddings. You must regenerate them
    after running this migration.
    """
    print("⚠️  WARNING: This migration will change vector dimensions from 384 to 1536.")
    print("⚠️  All existing embeddings will be incompatible and must be regenerated.")
    print("⚠️  Proceeding with migration...")
    
    # ========================================================================
    # Update property_embeddings table
    # ========================================================================
    print("1. Updating property_embeddings table...")
    
    # Drop the existing vector index
    try:
        op.execute('DROP INDEX IF EXISTS idx_embedding_cosine')
        print("   ✓ Dropped existing vector index")
    except Exception as e:
        print(f"   ⚠️  Could not drop index (may not exist): {e}")
    
    # Clear existing embeddings (they're incompatible with new dimension)
    # Option 1: Delete all embeddings (recommended - they need to be regenerated anyway)
    op.execute('DELETE FROM property_embeddings')
    print("   ✓ Cleared existing embeddings (must be regenerated with OpenAI)")
    
    # Option 2: If you want to keep the data structure but change dimension:
    # This would require converting embeddings, which is not possible without regenerating
    # So we delete them instead
    
    # Alter the embedding column to vector(1536)
    op.execute('ALTER TABLE property_embeddings ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)')
    print("   ✓ Updated embedding column to vector(1536)")
    
    # Recreate the vector index with new dimension
    op.execute('''
        CREATE INDEX idx_embedding_cosine 
        ON property_embeddings 
        USING ivfflat (embedding vector_cosine_ops) 
        WITH (lists = 100)
    ''')
    print("   ✓ Recreated vector index for 1536 dimensions")
    
    # ========================================================================
    # Update generic_knowledge table (if it exists)
    # ========================================================================
    print("2. Checking for generic_knowledge table...")
    
    # Check if table exists
    connection = op.get_bind()
    result = connection.execute(sa.text("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'generic_knowledge'
        )
    """))
    table_exists = result.scalar()
    
    if table_exists:
        print("   ✓ generic_knowledge table found, updating...")
        
        # Drop existing index
        try:
            op.execute('DROP INDEX IF EXISTS idx_generic_embedding_cosine')
            print("   ✓ Dropped existing generic vector index")
        except Exception as e:
            print(f"   ⚠️  Could not drop generic index: {e}")
        
        # Clear existing embeddings
        op.execute('DELETE FROM generic_knowledge')
        print("   ✓ Cleared existing generic embeddings")
        
        # Alter embedding column
        op.execute('ALTER TABLE generic_knowledge ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)')
        print("   ✓ Updated generic embedding column to vector(1536)")
        
        # Recreate index
        op.execute('''
            CREATE INDEX idx_generic_embedding_cosine 
            ON generic_knowledge 
            USING ivfflat (embedding vector_cosine_ops) 
            WITH (lists = 10)
        ''')
        print("   ✓ Recreated generic vector index")
    else:
        print("   ℹ️  generic_knowledge table does not exist (will be created with correct dimension on first use)")
    
    print("\n✅ Migration completed successfully!")
    print("\n📋 NEXT STEPS:")
    print("   1. Regenerate all property embeddings using OpenAI:")
    print("      python tests/unit/sync_pgvector.py")
    print("   2. Regenerate generic knowledge embeddings if applicable:")
    print("      (Use your generic PDF ingestion script)")


def downgrade():
    """
    Downgrade vector dimensions from 1536 back to 384.
    
    WARNING: This will drop all existing embeddings. You must regenerate them
    after running this downgrade.
    """
    print("⚠️  WARNING: Downgrading vector dimensions from 1536 to 384.")
    print("⚠️  All existing embeddings will be incompatible and must be regenerated.")
    
    # ========================================================================
    # Downgrade property_embeddings table
    # ========================================================================
    print("1. Downgrading property_embeddings table...")
    
    # Drop vector index
    try:
        op.execute('DROP INDEX IF EXISTS idx_embedding_cosine')
    except Exception as e:
        print(f"   ⚠️  Could not drop index: {e}")
    
    # Clear embeddings
    op.execute('DELETE FROM property_embeddings')
    
    # Alter back to vector(384)
    op.execute('ALTER TABLE property_embeddings ALTER COLUMN embedding TYPE vector(384) USING embedding::vector(384)')
    
    # Recreate index
    op.execute('''
        CREATE INDEX idx_embedding_cosine 
        ON property_embeddings 
        USING ivfflat (embedding vector_cosine_ops) 
        WITH (lists = 100)
    ''')
    
    # ========================================================================
    # Downgrade generic_knowledge table (if exists)
    # ========================================================================
    connection = op.get_bind()
    result = connection.execute(sa.text("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'generic_knowledge'
        )
    """))
    table_exists = result.scalar()
    
    if table_exists:
        print("2. Downgrading generic_knowledge table...")
        
        try:
            op.execute('DROP INDEX IF EXISTS idx_generic_embedding_cosine')
        except Exception as e:
            print(f"   ⚠️  Could not drop index: {e}")
        
        op.execute('DELETE FROM generic_knowledge')
        op.execute('ALTER TABLE generic_knowledge ALTER COLUMN embedding TYPE vector(384) USING embedding::vector(384)')
        
        op.execute('''
            CREATE INDEX idx_generic_embedding_cosine 
            ON generic_knowledge 
            USING ivfflat (embedding vector_cosine_ops) 
            WITH (lists = 10)
        ''')
    
    print("✅ Downgrade completed. Regenerate embeddings with SentenceTransformers.")

