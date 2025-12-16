"""Add prefix and digest to api_keys for scalable auth.

Revision ID: 001
Revises: 
Create Date: 2024-01-01
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns to api_keys
    op.add_column('api_keys', sa.Column('prefix', sa.String(length=8), nullable=True))
    op.add_column('api_keys', sa.Column('digest', sa.String(length=64), nullable=True))
    op.add_column('api_keys', sa.Column('last_used_at', sa.DateTime(), nullable=True))
    
    # Create indexes
    op.create_index('ix_api_keys_prefix', 'api_keys', ['prefix'])
    op.create_index('ix_api_keys_digest', 'api_keys', ['digest'])
    
    # Make hash nullable (legacy)
    op.alter_column('api_keys', 'hash', nullable=True)
    
    # Add ip_allowlist to tenants
    op.add_column('tenants', sa.Column('ip_allowlist', sa.Text(), nullable=True))
    op.alter_column('tenants', 'api_key_hash', nullable=True)


def downgrade() -> None:
    op.drop_index('ix_api_keys_digest', table_name='api_keys')
    op.drop_index('ix_api_keys_prefix', table_name='api_keys')
    op.drop_column('api_keys', 'last_used_at')
    op.drop_column('api_keys', 'digest')
    op.drop_column('api_keys', 'prefix')
    op.alter_column('api_keys', 'hash', nullable=False)
    op.drop_column('tenants', 'ip_allowlist')
    op.alter_column('tenants', 'api_key_hash', nullable=False)

