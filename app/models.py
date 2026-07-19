"""SQLAlchemy models for the initial core runtime schema."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


CARD_STATUSES = ("active", "inactive", "closed")
CYCLE_TYPES = (
    "monthly",
    "quarterly",
    "semiannual",
    "annual",
    "membership_year",
    "anniversary",
    "cert",
    "multi_year",
)
UNITS = ("usd_credit", "miles", "cert", "spend_to_goal_usd")
PERIOD_STATUSES = ("pending", "completed", "skipped", "expired")
USAGE_EVENT_TYPES = ("import_initial", "usage", "adjustment", "correction")

MYSQL_TABLE_OPTIONS = {
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_uca1400_ai_ci",
}


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class CardMaster(TimestampMixin, Base):
    __tablename__ = "card_master"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_card_master_slug"),
        CheckConstraint(
            f"status in ({_sql_values(CARD_STATUSES)})",
            name="status",
        ),
        CheckConstraint(
            "open_month is null or open_month between 1 and 12",
            name="open_month_range",
        ),
        CheckConstraint(
            "open_day is null or open_day between 1 and 31",
            name="open_day_range",
        ),
        MYSQL_TABLE_OPTIONS,
    )

    card_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    card_name: Mapped[str] = mapped_column(String(255), nullable=False)
    issuer: Mapped[str] = mapped_column(String(128), nullable=False)
    annual_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="active", server_default="active", nullable=False
    )
    open_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    open_month: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    open_day: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    benefit_definitions: Mapped[List["BenefitDefinition"]] = relationship(
        back_populates="card"
    )


class BenefitDefinition(TimestampMixin, Base):
    __tablename__ = "benefit_definitions"
    __table_args__ = (
        UniqueConstraint(
            "card_id", "normalized_name", name="uq_benefit_definitions_card_name"
        ),
        CheckConstraint(
            f"cycle_type in ({_sql_values(CYCLE_TYPES)})",
            name="cycle_type",
        ),
        CheckConstraint(
            f"unit is null or unit in ({_sql_values(UNITS)})",
            name="unit",
        ),
        CheckConstraint(
            "default_amount_total >= 0",
            name="default_amount_total_nonnegative",
        ),
        Index("ix_benefit_definitions_card_id", "card_id"),
        MYSQL_TABLE_OPTIONS,
    )

    benefit_definition_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    card_id: Mapped[int] = mapped_column(
        ForeignKey("card_master.card_id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    cycle_type: Mapped[str] = mapped_column(String(32), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    default_amount_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    default_deadline_rule: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    default_period_rule: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("1"), nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    card: Mapped["CardMaster"] = relationship(back_populates="benefit_definitions")
    benefit_periods: Mapped[List["BenefitPeriod"]] = relationship(
        back_populates="benefit_definition"
    )


class BenefitPeriod(TimestampMixin, Base):
    __tablename__ = "benefit_periods"
    __table_args__ = (
        UniqueConstraint(
            "benefit_definition_id",
            "period_key",
            name="uq_benefit_periods_definition_period",
        ),
        CheckConstraint(
            f"status in ({_sql_values(PERIOD_STATUSES)})",
            name="status",
        ),
        CheckConstraint("amount_total >= 0", name="amount_total_nonnegative"),
        CheckConstraint("period_start <= period_end", name="date_order"),
        Index("ix_benefit_periods_benefit_definition_id", "benefit_definition_id"),
        Index("ix_benefit_periods_deadline", "deadline"),
        Index("ix_benefit_periods_status", "status"),
        MYSQL_TABLE_OPTIONS,
    )

    benefit_period_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    benefit_definition_id: Mapped[int] = mapped_column(
        ForeignKey("benefit_definitions.benefit_definition_id", ondelete="RESTRICT"),
        nullable=False,
    )
    period_key: Mapped[str] = mapped_column(String(64), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    deadline: Mapped[date] = mapped_column(Date, nullable=False)
    amount_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    benefit_definition: Mapped["BenefitDefinition"] = relationship(
        back_populates="benefit_periods"
    )
    usage_events: Mapped[List["UsageEvent"]] = relationship(back_populates="benefit_period")


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        UniqueConstraint(
            "event_type", "source_key", name="uq_usage_events_event_type_source_key"
        ),
        CheckConstraint(
            f"event_type in ({_sql_values(USAGE_EVENT_TYPES)})",
            name="event_type",
        ),
        CheckConstraint(
            "event_type <> 'import_initial' or source_key is not null",
            name="import_source_key_required",
        ),
        Index("ix_usage_events_benefit_period_id", "benefit_period_id"),
        MYSQL_TABLE_OPTIONS,
    )

    usage_event_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    benefit_period_id: Mapped[int] = mapped_column(
        ForeignKey("benefit_periods.benefit_period_id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_delta: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    source_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    benefit_period: Mapped["BenefitPeriod"] = relationship(back_populates="usage_events")
