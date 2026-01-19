"""add conversation tables

Revision ID: 003
Revises: 002
Create Date: 2025-01-06 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    # Create conversation_role enum
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE conversation_role AS ENUM ('user', 'bot');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Create conversations table
    op.create_table(
        'conversations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('listing_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('message_count', sa.Integer(), default=0, nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now(), nullable=False),
    )
    
    # Create indexes for conversations
    op.create_index('idx_conversation_listing_user', 'conversations', ['listing_id', 'user_id'])
    op.create_index('idx_conversation_active', 'conversations', ['is_active'])
    op.create_index('idx_conversation_listing_id', 'conversations', ['listing_id'])
    op.create_index('idx_conversation_user_id', 'conversations', ['user_id'])
    
    # Create unique constraint for conversations
    op.create_unique_constraint(
        'unique_conversation_per_user_and_listing',
        'conversations',
        ['user_id', 'listing_id']
    )
    
    # Create chat_messages table
    op.create_table(
        'chat_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', postgresql.ENUM('user', 'bot', name='conversation_role', create_type=False), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    )
    
    # Create indexes for chat_messages
    op.create_index('idx_message_conversation', 'chat_messages', ['conversation_id', 'created_at'])
    op.create_index('idx_message_role', 'chat_messages', ['role'])
    op.create_index('idx_message_conversation_id', 'chat_messages', ['conversation_id'])


def downgrade():
    # Drop indexes
    op.drop_index('idx_message_conversation_id', table_name='chat_messages')
    op.drop_index('idx_message_role', table_name='chat_messages')
    op.drop_index('idx_message_conversation', table_name='chat_messages')
    
    # Drop tables
    op.drop_table('chat_messages')
    
    # Drop unique constraint
    op.drop_constraint('unique_conversation_per_user_and_listing', 'conversations', type_='unique')
    
    # Drop indexes
    op.drop_index('idx_conversation_user_id', table_name='conversations')
    op.drop_index('idx_conversation_listing_id', table_name='conversations')
    op.drop_index('idx_conversation_active', table_name='conversations')
    op.drop_index('idx_conversation_listing_user', table_name='conversations')
    
    # Drop table
    op.drop_table('conversations')
    
    # Drop enum (only if no other tables use it)
    op.execute('DROP TYPE IF EXISTS conversation_role')

