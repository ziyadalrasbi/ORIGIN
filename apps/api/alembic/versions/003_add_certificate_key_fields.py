"""Add key_id, alg, signature_encoding to certificates.

Revision ID: 003
Revises: 002
Create Date: 2024-01-01
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('decision_certificates', sa.Column('key_id', sa.String(length=100), nullable=True))
    op.add_column('decision_certificates', sa.Column('alg', sa.String(length=20), server_default='RS256', nullable=False))
    op.add_column('decision_certificates', sa.Column('signature_encoding', sa.String(length=20), server_default='base64', nullable=False))


def downgrade() -> None:
    op.drop_column('decision_certificates', 'signature_encoding')
    op.drop_column('decision_certificates', 'alg')
    op.drop_column('decision_certificates', 'key_id')

