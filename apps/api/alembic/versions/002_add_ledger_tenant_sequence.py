"""Add tenant_sequence and canonical_event_json to ledger.

Revision ID: 002
Revises: 001
Create Date: 2024-01-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create tenant_sequences table
    op.create_table(
        'tenant_sequences',
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('last_sequence', sa.BigInteger(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('tenant_id')
    )
    op.create_index('ix_tenant_sequences_tenant_id', 'tenant_sequences', ['tenant_id'])
    
    # Add columns to ledger_events
    op.add_column('ledger_events', sa.Column('tenant_sequence', sa.BigInteger(), nullable=True))
    op.add_column('ledger_events', sa.Column('event_timestamp', sa.DateTime(), nullable=True))
    op.add_column('ledger_events', sa.Column('canonical_event_json', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    
    # Create indexes and unique constraint
    op.create_index('ix_ledger_events_tenant_sequence', 'ledger_events', ['tenant_sequence'])
    op.create_index('ix_ledger_events_event_timestamp', 'ledger_events', ['event_timestamp'])
    op.create_unique_constraint('uq_ledger_tenant_sequence', 'ledger_events', ['tenant_id', 'tenant_sequence'])
    
    # Backfill: set event_timestamp = created_at for existing records
    op.execute("UPDATE ledger_events SET event_timestamp = created_at WHERE event_timestamp IS NULL")
    
    # Make columns NOT NULL after backfill
    op.alter_column('ledger_events', 'tenant_sequence', nullable=False)
    op.alter_column('ledger_events', 'event_timestamp', nullable=False)
    op.alter_column('ledger_events', 'canonical_event_json', nullable=False)


def downgrade() -> None:
    op.drop_constraint('uq_ledger_tenant_sequence', 'ledger_events', type_='unique')
    op.drop_index('ix_ledger_events_event_timestamp', table_name='ledger_events')
    op.drop_index('ix_ledger_events_tenant_sequence', table_name='ledger_events')
    op.drop_column('ledger_events', 'canonical_event_json')
    op.drop_column('ledger_events', 'event_timestamp')
    op.drop_column('ledger_events', 'tenant_sequence')
    op.drop_index('ix_tenant_sequences_tenant_id', table_name='tenant_sequences')
    op.drop_table('tenant_sequences')

