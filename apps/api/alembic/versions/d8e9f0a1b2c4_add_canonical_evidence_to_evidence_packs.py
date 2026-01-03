"""Add canonical evidence snapshot to evidence packs.

Revision ID: d8e9f0a1b2c4
Revises: c7f8e9a1b2c3
Create Date: 2024-01-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'd8e9f0a1b2c4'
down_revision = 'c7f8e9a1b2c3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add canonical JSON snapshot and evidence hash
    op.add_column('evidence_packs', sa.Column('canonical_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('evidence_packs', sa.Column('evidence_hash', sa.String(length=64), nullable=True))
    op.add_column('evidence_packs', sa.Column('evidence_version', sa.String(length=50), nullable=True, server_default='origin-evidence-v2'))
    op.add_column('evidence_packs', sa.Column('canonical_created_at', sa.DateTime(), nullable=True))
    
    # Add index on evidence_hash for lookups
    op.create_index('ix_evidence_packs_evidence_hash', 'evidence_packs', ['evidence_hash'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_evidence_packs_evidence_hash', table_name='evidence_packs')
    op.drop_column('evidence_packs', 'canonical_created_at')
    op.drop_column('evidence_packs', 'evidence_version')
    op.drop_column('evidence_packs', 'evidence_hash')
    op.drop_column('evidence_packs', 'canonical_json')

