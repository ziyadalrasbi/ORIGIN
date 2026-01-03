"""Production evidence pack tracking: task tracking and stuck detection.

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c5d6
Create Date: 2026-01-03 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f0a1b2c3d4e5'
down_revision = 'e9f0a1b2c5d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add task tracking fields for idempotency and stuck detection
    op.add_column('evidence_packs', sa.Column('task_id', sa.String(255), nullable=True, index=True))
    op.add_column('evidence_packs', sa.Column('last_enqueued_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('evidence_packs', sa.Column('last_polled_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('evidence_packs', sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))
    
    # Add updated_at if it doesn't exist (for state transition tracking)
    try:
        op.add_column('evidence_packs', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True, onupdate=sa.func.now()))
    except Exception:
        # Column may already exist
        pass
    
    # Add index for stuck detection queries
    op.create_index(
        'ix_evidence_packs_status_enqueued',
        'evidence_packs',
        ['status', 'last_enqueued_at']
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_evidence_packs_status_enqueued', table_name='evidence_packs')
    
    # Drop columns
    op.drop_column('evidence_packs', 'updated_at')
    op.drop_column('evidence_packs', 'started_at')
    op.drop_column('evidence_packs', 'last_polled_at')
    op.drop_column('evidence_packs', 'last_enqueued_at')
    op.drop_column('evidence_packs', 'task_id')

