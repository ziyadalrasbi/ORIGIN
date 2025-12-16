"""Add storage fields to evidence_packs.

Revision ID: 005
Revises: 004
Create Date: 2024-01-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add storage metadata fields
    op.add_column('evidence_packs', sa.Column('storage_keys', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.add_column('evidence_packs', sa.Column('artifact_hashes', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.add_column('evidence_packs', sa.Column('artifact_sizes', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.add_column('evidence_packs', sa.Column('generated_at', sa.DateTime(), nullable=True))
    
    # Add index for status lookups
    op.create_index('ix_evidence_packs_status', 'evidence_packs', ['status'])


def downgrade() -> None:
    op.drop_index('ix_evidence_packs_status', table_name='evidence_packs')
    op.drop_column('evidence_packs', 'generated_at')
    op.drop_column('evidence_packs', 'artifact_sizes')
    op.drop_column('evidence_packs', 'artifact_hashes')
    op.drop_column('evidence_packs', 'storage_keys')

