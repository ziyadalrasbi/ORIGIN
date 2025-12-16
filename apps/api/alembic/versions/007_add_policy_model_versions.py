"""Add model version fields to policy_profiles.

Revision ID: 007
Revises: 006
Create Date: 2024-01-03
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add model version fields to policy_profiles
    op.add_column('policy_profiles', sa.Column('risk_model_version', sa.String(length=100), nullable=True))
    op.add_column('policy_profiles', sa.Column('anomaly_model_version', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('policy_profiles', 'anomaly_model_version')
    op.drop_column('policy_profiles', 'risk_model_version')

