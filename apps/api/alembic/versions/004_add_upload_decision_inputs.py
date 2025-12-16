"""Add decision_inputs_json to uploads and unique constraint.

Revision ID: 004
Revises: 003
Create Date: 2024-01-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add decision_inputs_json
    op.add_column('uploads', sa.Column('decision_inputs_json', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    
    # Add unique constraint on (tenant_id, external_id)
    op.create_unique_constraint('uq_uploads_tenant_external', 'uploads', ['tenant_id', 'external_id'])
    
    # Add additional indexes for performance
    op.create_index('ix_uploads_pvid', 'uploads', ['pvid'], unique=False, postgresql_where=sa.text('pvid IS NOT NULL'))
    op.create_index('ix_uploads_account_received', 'uploads', ['account_id', 'received_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_uploads_account_received', table_name='uploads')
    op.drop_index('ix_uploads_pvid', table_name='uploads')
    op.drop_constraint('uq_uploads_tenant_external', 'uploads', type_='unique')
    op.drop_column('uploads', 'decision_inputs_json')

