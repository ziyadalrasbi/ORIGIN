"""Production-grade evidence packs: constraints, audience, error tracking.

Revision ID: e9f0a1b2c5d6
Revises: d8e9f0a1b2c4
Create Date: 2026-01-03 21:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'e9f0a1b2c5d6'
down_revision = 'd8e9f0a1b2c4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add audience column (required for multi-audience support)
    op.add_column('evidence_packs', sa.Column('audience', sa.String(50), nullable=True, server_default='INTERNAL'))
    
    # Add error tracking columns
    op.add_column('evidence_packs', sa.Column('error_code', sa.String(100), nullable=True))
    op.add_column('evidence_packs', sa.Column('error_message', sa.Text(), nullable=True))
    
    # Ensure evidence_version has a default
    op.alter_column('evidence_packs', 'evidence_version',
                    existing_type=sa.String(50),
                    server_default='origin-evidence-v2',
                    nullable=True)
    
    # Add unique constraint: (tenant_id, certificate_id, audience)
    # This ensures idempotency: one evidence pack per tenant/certificate/audience combination
    op.create_unique_constraint(
        'uq_evidence_packs_tenant_certificate_audience',
        'evidence_packs',
        ['tenant_id', 'certificate_id', 'audience']
    )
    
    # Add indexes for performance
    op.create_index(
        'ix_evidence_packs_tenant_certificate',
        'evidence_packs',
        ['tenant_id', 'certificate_id']
    )
    op.create_index(
        'ix_evidence_packs_tenant_status',
        'evidence_packs',
        ['tenant_id', 'status']
    )
    op.create_index(
        'ix_evidence_packs_created_at',
        'evidence_packs',
        ['created_at']
    )
    
    # Make audience NOT NULL after setting defaults
    op.alter_column('evidence_packs', 'audience',
                    existing_type=sa.String(50),
                    nullable=False,
                    server_default='INTERNAL')


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_evidence_packs_created_at', table_name='evidence_packs')
    op.drop_index('ix_evidence_packs_tenant_status', table_name='evidence_packs')
    op.drop_index('ix_evidence_packs_tenant_certificate', table_name='evidence_packs')
    
    # Drop unique constraint
    op.drop_constraint('uq_evidence_packs_tenant_certificate_audience', 'evidence_packs', type_='unique')
    
    # Drop columns
    op.drop_column('evidence_packs', 'error_message')
    op.drop_column('evidence_packs', 'error_code')
    op.drop_column('evidence_packs', 'audience')

