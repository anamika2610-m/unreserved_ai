"""add conversation history tables

Revision ID: 001
Revises: 
Create Date: 2024-12-19

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create conversation_sessions table
    op.create_table(
        'conversation_sessions',
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('listing_id', sa.String(), nullable=False),
        sa.Column('message_count', sa.Integer(), nullable=True, default=0),
        sa.Column('first_message_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('last_message_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, default=True),
        sa.PrimaryKeyConstraint('session_id')
    )
    
    # Create indexes for conversation_sessions
    op.create_index(op.f('ix_conversation_sessions_session_id'), 'conversation_sessions', ['session_id'], unique=False)
    op.create_index(op.f('ix_conversation_sessions_user_id'), 'conversation_sessions', ['user_id'], unique=False)
    op.create_index(op.f('ix_conversation_sessions_listing_id'), 'conversation_sessions', ['listing_id'], unique=False)
    
    # Create conversation_messages table
    op.create_table(
        'conversation_messages',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('listing_id', sa.String(), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('needs_vendor_contact', sa.Boolean(), nullable=True, default=False),
        sa.Column('nearby_properties', sa.JSON(), nullable=True),
        sa.Column('nearby_amenities', sa.JSON(), nullable=True),
        sa.Column('model_version', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for conversation_messages
    op.create_index(op.f('ix_conversation_messages_id'), 'conversation_messages', ['id'], unique=False)
    op.create_index(op.f('ix_conversation_messages_session_id'), 'conversation_messages', ['session_id'], unique=False)
    op.create_index(op.f('ix_conversation_messages_user_id'), 'conversation_messages', ['user_id'], unique=False)
    op.create_index(op.f('ix_conversation_messages_listing_id'), 'conversation_messages', ['listing_id'], unique=False)


def downgrade():
    # Drop conversation_messages table and indexes
    op.drop_index(op.f('ix_conversation_messages_listing_id'), table_name='conversation_messages')
    op.drop_index(op.f('ix_conversation_messages_user_id'), table_name='conversation_messages')
    op.drop_index(op.f('ix_conversation_messages_session_id'), table_name='conversation_messages')
    op.drop_index(op.f('ix_conversation_messages_id'), table_name='conversation_messages')
    op.drop_table('conversation_messages')
    
    # Drop conversation_sessions table and indexes
    op.drop_index(op.f('ix_conversation_sessions_listing_id'), table_name='conversation_sessions')
    op.drop_index(op.f('ix_conversation_sessions_user_id'), table_name='conversation_sessions')
    op.drop_index(op.f('ix_conversation_sessions_session_id'), table_name='conversation_sessions')
    op.drop_table('conversation_sessions')

