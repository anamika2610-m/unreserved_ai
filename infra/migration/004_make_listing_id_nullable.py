"""
Make listing_id nullable in conversations table for generic queries

Revision ID: 004
Revises: 003
Create Date: 2026-01-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade():
    """
    Make listing_id nullable to support generic conversations.
    Also drop and recreate the unique constraint to handle NULL values.
    """
    
    # Drop the existing unique constraint (it doesn't handle NULLs properly)
    op.execute("""
        ALTER TABLE conversations 
        DROP CONSTRAINT IF EXISTS unique_conversation_per_user_and_listing
    """)
    
    # Make listing_id nullable
    op.alter_column(
        'conversations',
        'listing_id',
        existing_type=postgresql.UUID(),
        nullable=True
    )
    
    # PostgreSQL unique constraints treat NULL as distinct values
    # So multiple rows with (user_id=X, listing_id=NULL) are allowed
    # This is CORRECT behavior - each user can have multiple generic conversations
    # But we want ONE conversation per (user_id, listing_id) when listing_id IS NOT NULL
    
    # Create partial unique index for non-NULL listing_id
    op.execute("""
        CREATE UNIQUE INDEX unique_conversation_per_user_and_listing 
        ON conversations (user_id, listing_id) 
        WHERE listing_id IS NOT NULL
    """)
    
    # For generic conversations (listing_id IS NULL), we'll allow multiple
    # conversations per user to support different conversation topics


def downgrade():
    """
    Revert listing_id to non-nullable.
    """
    
    # Drop the partial unique index
    op.execute("DROP INDEX IF EXISTS unique_conversation_per_user_and_listing")
    
    # Make listing_id non-nullable again
    op.alter_column(
        'conversations',
        'listing_id',
        existing_type=postgresql.UUID(),
        nullable=False
    )
    
    # Restore the original unique constraint
    op.execute("""
        ALTER TABLE conversations 
        ADD CONSTRAINT unique_conversation_per_user_and_listing 
        UNIQUE (user_id, listing_id)
    """)

