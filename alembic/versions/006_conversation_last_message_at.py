"""add last_message_at to conversations for 10-day retention

Revision ID: 006
Revises: 005
Create Date: 2026-02-11

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'conversations',
        sa.Column('last_message_at', sa.DateTime(), nullable=True),
    )
    # Backfill: set last_message_at = created_at for existing rows
    op.execute("""
        UPDATE conversations
        SET last_message_at = created_at
        WHERE last_message_at IS NULL
    """)


def downgrade():
    op.drop_column('conversations', 'last_message_at')
