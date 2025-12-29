"""add regulatory_compliance_json to policy_profiles

Revision ID: c7f8e9a1b2c3
Revises: b9d844b89806
Create Date: 2025-01-20 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7f8e9a1b2c3'
down_revision: Union[str, None] = 'b9d844b89806'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add regulatory_compliance_json column to policy_profiles table
    op.add_column('policy_profiles', 
        sa.Column('regulatory_compliance_json', sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    # Remove regulatory_compliance_json column from policy_profiles table
    op.drop_column('policy_profiles', 'regulatory_compliance_json')

