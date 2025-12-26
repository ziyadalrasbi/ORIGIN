"""add decision_mode to policy_profiles

Revision ID: b9d844b89806
Revises: d5526dedf344
Create Date: 2025-01-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b9d844b89806'
down_revision: Union[str, None] = 'd5526dedf344'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add decision_mode column to policy_profiles table
    op.add_column('policy_profiles', 
        sa.Column('decision_mode', sa.String(length=50), nullable=False, server_default='score_first')
    )


def downgrade() -> None:
    # Remove decision_mode column from policy_profiles table
    op.drop_column('policy_profiles', 'decision_mode')

