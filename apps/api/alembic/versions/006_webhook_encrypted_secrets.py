"""Add encrypted webhook secret fields.

Revision ID: 006
Revises: 005
Create Date: 2024-01-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new encrypted secret fields
    op.add_column('webhooks', sa.Column('secret_ciphertext', sa.Text(), nullable=True))
    op.add_column('webhooks', sa.Column('secret_key_id', sa.String(length=255), nullable=True))
    op.add_column('webhooks', sa.Column('secret_version', sa.String(length=100), nullable=True))
    op.add_column('webhooks', sa.Column('encryption_context', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.add_column('webhooks', sa.Column('rotated_at', sa.DateTime(), nullable=True))
    
    # Migrate existing secret_hash to encrypted format (if any exist)
    # For existing webhooks, we'll need to re-encrypt - this is a data migration
    # that should be handled separately if there are existing webhooks
    
    # Make new fields required after migration
    op.alter_column('webhooks', 'secret_ciphertext', nullable=False)
    op.alter_column('webhooks', 'secret_key_id', nullable=False)
    
    # Keep secret_hash for backward compatibility during migration
    # It will be removed in a future migration after all webhooks are migrated


def downgrade() -> None:
    op.drop_column('webhooks', 'rotated_at')
    op.drop_column('webhooks', 'encryption_context')
    op.drop_column('webhooks', 'secret_version')
    op.drop_column('webhooks', 'secret_key_id')
    op.drop_column('webhooks', 'secret_ciphertext')

