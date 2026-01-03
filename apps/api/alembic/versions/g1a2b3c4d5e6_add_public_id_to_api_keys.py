"""Add public_id to API keys for O(1) lookup.

Revision ID: g1a2b3c4d5e6
Revises: f0a1b2c3d4e5
Create Date: 2026-01-04 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'g1a2b3c4d5e6'
down_revision = 'f0a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add public_id column (nullable initially for existing keys)
    op.add_column('api_keys', sa.Column('public_id', sa.String(64), nullable=True))
    
    # Create unique index on public_id (idempotent)
    try:
        op.create_index('ix_api_keys_public_id', 'api_keys', ['public_id'], unique=True)
    except Exception:
        # Index may already exist
        pass


def downgrade() -> None:
    # Drop index
    try:
        op.drop_index('ix_api_keys_public_id', table_name='api_keys')
    except Exception:
        pass
    
    # Drop column
    try:
        op.drop_column('api_keys', 'public_id')
    except Exception:
        pass

