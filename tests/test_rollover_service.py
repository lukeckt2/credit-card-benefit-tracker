from __future__ import annotations

import argparse
from decimal import Decimal
from datetime import date
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, BenefitDefinition, BenefitPeriod, CardMaster
from app.schemas import RolloverRequest
from app.services.rollover import apply_rollover, generate_candidate_periods, preview_rollover


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    Base.metadata.create_all(engine)

    with TestingSessionLocal() as session:
        yield session

    Base.metadata.drop_all(engine)


def add_definition(
    session,
    *,
    slug: str,
    name: str,
    cycle_type: str,
    open_month: int = 5,
    open_day: int = 10,
) -> BenefitDefinition:
    card = CardMaster(
        slug=slug,
        display_name=name,
        card_name=name,
        issuer="Test Bank",
        status="active",
        open_month=open_month,
        open_day=open_day,
    )
    definition = BenefitDefinition(
        card=card,
        name=name,
        normalized_name=slug,
        cycle_type=cycle_type,
        unit="usd_credit",
        default_amount_total=Decimal("10.00"),
        active=True,
    )
    session.add(card)
    session.add(definition)
    session.flush()
    return definition


def keys(cycle_type: str, start: date, end: date, **kwargs) -> list[str]:
    return [
        period.period_key
        for period in generate_candidate_periods(cycle_type, start, end, **kwargs)
    ]


def test_monthly_period_creation():
    assert keys("monthly", date(2026, 7, 1), date(2026, 8, 1)) == [
        "2026-07",
        "2026-08",
    ]


def test_quarterly_boundary_months():
    assert keys("quarterly", date(2026, 3, 31), date(2026, 4, 1)) == [
        "2026-Q1",
        "2026-Q2",
    ]


def test_semiannual_boundary_months():
    assert keys("semiannual", date(2026, 6, 30), date(2026, 7, 1)) == [
        "2026-H1",
        "2026-H2",
    ]


def test_annual_january_behavior():
    assert keys("annual", date(2026, 1, 1), date(2026, 1, 31)) == ["2026"]


def test_membership_year_window_from_open_month_day():
    assert keys(
        "membership_year",
        date(2026, 7, 1),
        date(2026, 7, 31),
        open_month=5,
        open_day=10,
    ) == ["2026-05-10~2027-05-10"]


def test_membership_year_without_open_month_day_is_skipped():
    assert keys("membership_year", date(2026, 7, 1), date(2026, 7, 31)) == []


def test_start_date_filter_creates_due_cycles_and_tracks_not_due(db_session):
    add_definition(
        db_session, slug="monthly", name="Monthly Credit", cycle_type="monthly"
    )
    add_definition(
        db_session, slug="quarterly", name="Quarterly Credit", cycle_type="quarterly"
    )
    add_definition(db_session, slug="annual", name="Annual Credit", cycle_type="annual")
    add_definition(
        db_session,
        slug="membership-may",
        name="May Membership Credit",
        cycle_type="membership_year",
        open_month=5,
        open_day=10,
    )
    add_definition(
        db_session,
        slug="membership-july",
        name="July Membership Credit",
        cycle_type="membership_year",
        open_month=7,
        open_day=15,
    )

    request = RolloverRequest(
        window_start=date(2026, 7, 1),
        window_end=date(2026, 7, 31),
        only_periods_starting_in_window=True,
    )

    preview = preview_rollover(db_session, request)

    assert {period.period_key for period in preview.periods} == {
        "2026-07",
        "2026-Q3",
        "2026-07-15~2027-07-15",
    }
    assert preview.would_create == 3
    assert preview.not_due == 2
    assert preview.skipped == 0
    assert preview.warnings == []

    applied = apply_rollover(db_session, request)
    db_session.commit()
    assert applied.created == 3

    repeated = apply_rollover(db_session, request)
    assert repeated.created == 0
    assert repeated.existing == 3
    assert repeated.not_due == 2
    assert db_session.scalar(select(func.count()).select_from(BenefitPeriod)) == 3


@pytest.mark.parametrize(
    ("cycle_type", "window_start", "window_end", "expected_keys", "expected_not_due"),
    [
        ("quarterly", date(2026, 8, 1), date(2026, 8, 31), set(), 1),
        ("quarterly", date(2026, 10, 1), date(2026, 10, 31), {"2026-Q4"}, 0),
        ("annual", date(2026, 2, 1), date(2026, 2, 28), set(), 1),
        ("annual", date(2026, 1, 1), date(2026, 1, 31), {"2026"}, 0),
        ("semiannual", date(2026, 7, 1), date(2026, 7, 31), {"2026-H2"}, 0),
    ],
)
def test_start_date_filter_respects_cycle_start_months(
    db_session, cycle_type, window_start, window_end, expected_keys, expected_not_due
):
    add_definition(db_session, slug=cycle_type, name=cycle_type, cycle_type=cycle_type)

    response = preview_rollover(
        db_session,
        RolloverRequest(
            window_start=window_start,
            window_end=window_end,
            only_periods_starting_in_window=True,
        ),
    )

    assert {period.period_key for period in response.periods} == expected_keys
    assert response.not_due == expected_not_due
    assert response.warnings == []


def test_cli_month_window_handles_leap_year():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "cron_jobs" / "rollover.py"
    spec = importlib.util.spec_from_file_location("rollover_cli", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.parse_month_window("2028-02") == (
        date(2028, 2, 1),
        date(2028, 2, 29),
    )
    with pytest.raises(argparse.ArgumentTypeError):
        module.parse_month_window("2028-13")
