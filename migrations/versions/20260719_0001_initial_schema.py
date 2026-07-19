"""Create initial core database schema.

Revision ID: 20260719_0001
Revises:
Create Date: 2026-07-19
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260719_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_OPTIONS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_uca1400_ai_ci"}


def upgrade() -> None:
    op.create_table(
        "card_master",
        sa.Column("card_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("card_name", sa.String(length=255), nullable=False),
        sa.Column("issuer", sa.String(length=128), nullable=False),
        sa.Column("annual_fee", sa.Numeric(12, 2), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("open_date", sa.Date(), nullable=True),
        sa.Column("open_month", sa.SmallInteger(), nullable=True),
        sa.Column("open_day", sa.SmallInteger(), nullable=True),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status in ('active', 'inactive', 'closed')", name=op.f("ck_card_master_status")
        ),
        sa.CheckConstraint(
            "open_month is null or open_month between 1 and 12",
            name=op.f("ck_card_master_open_month_range"),
        ),
        sa.CheckConstraint(
            "open_day is null or open_day between 1 and 31",
            name=op.f("ck_card_master_open_day_range"),
        ),
        sa.PrimaryKeyConstraint("card_id", name="pk_card_master"),
        sa.UniqueConstraint("slug", name="uq_card_master_slug"),
        **TABLE_OPTIONS,
    )

    op.create_table(
        "benefit_definitions",
        sa.Column(
            "benefit_definition_id", sa.Integer(), autoincrement=True, nullable=False
        ),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("cycle_type", sa.String(length=32), nullable=False),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("default_amount_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("default_deadline_rule", sa.String(length=255), nullable=True),
        sa.Column("default_period_rule", sa.String(length=255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "cycle_type in ('monthly', 'quarterly', 'semiannual', 'annual', "
            "'membership_year', 'anniversary', 'cert', 'multi_year')",
            name=op.f("ck_benefit_definitions_cycle_type"),
        ),
        sa.CheckConstraint(
            "unit is null or unit in ('usd_credit', 'miles', 'cert', "
            "'spend_to_goal_usd')",
            name=op.f("ck_benefit_definitions_unit"),
        ),
        sa.CheckConstraint(
            "default_amount_total >= 0",
            name=op.f("ck_benefit_definitions_default_amount_total_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["card_master.card_id"],
            name="fk_benefit_definitions_card_id_card_master",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "benefit_definition_id", name="pk_benefit_definitions"
        ),
        sa.UniqueConstraint(
            "card_id", "normalized_name", name="uq_benefit_definitions_card_name"
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_benefit_definitions_card_id", "benefit_definitions", ["card_id"]
    )

    op.create_table(
        "benefit_periods",
        sa.Column("benefit_period_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("benefit_definition_id", sa.Integer(), nullable=False),
        sa.Column("period_key", sa.String(length=64), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("deadline", sa.Date(), nullable=False),
        sa.Column("amount_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status in ('pending', 'completed', 'skipped', 'expired')",
            name=op.f("ck_benefit_periods_status"),
        ),
        sa.CheckConstraint(
            "amount_total >= 0", name=op.f("ck_benefit_periods_amount_total_nonnegative")
        ),
        sa.CheckConstraint(
            "period_start <= period_end", name=op.f("ck_benefit_periods_date_order")
        ),
        sa.ForeignKeyConstraint(
            ["benefit_definition_id"],
            ["benefit_definitions.benefit_definition_id"],
            name="fk_benefit_periods_benefit_definition_id_benefit_definitions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("benefit_period_id", name="pk_benefit_periods"),
        sa.UniqueConstraint(
            "benefit_definition_id",
            "period_key",
            name="uq_benefit_periods_definition_period",
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_benefit_periods_benefit_definition_id",
        "benefit_periods",
        ["benefit_definition_id"],
    )
    op.create_index("ix_benefit_periods_deadline", "benefit_periods", ["deadline"])
    op.create_index("ix_benefit_periods_status", "benefit_periods", ["status"])

    op.create_table(
        "usage_events",
        sa.Column("usage_event_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("benefit_period_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("amount_delta", sa.Numeric(12, 2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "used_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("source_key", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "event_type in ('import_initial', 'usage', 'adjustment', 'correction')",
            name=op.f("ck_usage_events_event_type"),
        ),
        sa.CheckConstraint(
            "event_type <> 'import_initial' or source_key is not null",
            name=op.f("ck_usage_events_import_source_key_required"),
        ),
        sa.ForeignKeyConstraint(
            ["benefit_period_id"],
            ["benefit_periods.benefit_period_id"],
            name="fk_usage_events_benefit_period_id_benefit_periods",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("usage_event_id", name="pk_usage_events"),
        sa.UniqueConstraint(
            "event_type", "source_key", name="uq_usage_events_event_type_source_key"
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_usage_events_benefit_period_id", "usage_events", ["benefit_period_id"]
    )

def downgrade() -> None:
    op.drop_index("ix_usage_events_benefit_period_id", table_name="usage_events")
    op.drop_table("usage_events")
    op.drop_index("ix_benefit_periods_status", table_name="benefit_periods")
    op.drop_index("ix_benefit_periods_deadline", table_name="benefit_periods")
    op.drop_index(
        "ix_benefit_periods_benefit_definition_id", table_name="benefit_periods"
    )
    op.drop_table("benefit_periods")
    op.drop_index("ix_benefit_definitions_card_id", table_name="benefit_definitions")
    op.drop_table("benefit_definitions")
    op.drop_table("card_master")
