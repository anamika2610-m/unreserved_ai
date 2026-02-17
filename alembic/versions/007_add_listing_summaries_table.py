"""add listing_summaries table for chat summary cron

Revision ID: 007
Revises: 006
Create Date: 2026-02-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    # Create table only if it does not exist (idempotent for existing DBs)
    op.execute("""
        CREATE TABLE IF NOT EXISTS listing_summaries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            lisitng_id UUID NOT NULL UNIQUE,
            summary TEXT,
            last_summarised_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    # Unique on lisitng_id is already in CREATE TABLE; add extra indexes for queries
    op.execute("CREATE INDEX IF NOT EXISTS idx_listing_summary_last_summarised_at ON listing_summaries (last_summarised_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_listing_summary_updated_at ON listing_summaries (updated_at)")


def downgrade():
    op.drop_table('listing_summaries')
