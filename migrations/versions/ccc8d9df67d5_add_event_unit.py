"""Add event unit

Revision ID: ccc8d9df67d5
Revises: 84d360170547
Create Date: 2026-08-03 20:28:34.928626
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ccc8d9df67d5'
down_revision: Union[str, None] = '84d360170547'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('unit', 'benefit_definitions', type_='check')
    op.create_check_constraint(
        'unit', 
        'benefit_definitions', 
        "unit is null or unit in ('usd_credit', 'miles', 'cert', 'spend_to_goal_usd', 'event')"
    )
    op.drop_constraint('unit', 'benefit_source_config', type_='check')
    op.create_check_constraint(
        'unit', 
        'benefit_source_config', 
        "unit is null or unit in ('usd_credit', 'miles', 'cert', 'spend_to_goal_usd', 'event')"
    )


def downgrade() -> None:
    op.drop_constraint('unit', 'benefit_definitions', type_='check')
    op.create_check_constraint(
        'unit', 
        'benefit_definitions', 
        "unit is null or unit in ('usd_credit', 'miles', 'cert', 'spend_to_goal_usd')"
    )
    op.drop_constraint('unit', 'benefit_source_config', type_='check')
    op.create_check_constraint(
        'unit', 
        'benefit_source_config', 
        "unit is null or unit in ('usd_credit', 'miles', 'cert', 'spend_to_goal_usd')"
    )
