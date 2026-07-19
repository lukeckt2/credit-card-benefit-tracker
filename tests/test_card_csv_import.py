from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, BenefitDefinition, BenefitPeriod, CardMaster, UsageEvent
from app.services.card_csv_import import (
    CSV_COLUMNS,
    apply_plan,
    build_plan,
    plan_output,
    reconcile_plan,
)


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


def card_row(**overrides) -> dict[str, str]:
    row = {column: "" for column in CSV_COLUMNS}
    row.update(
        {
            "card_slug": "test-card",
            "card_display_name": "Test Card",
            "card_card_name": "Test Card Preferred",
            "card_issuer": "Test Bank",
            "card_annual_fee": "95.00",
            "card_status": "active",
            "card_open_date": "2026-07-15",
            "card_open_month": "7",
            "card_open_day": "15",
            "card_source_url": "https://example.com/card",
            "card_notes": "Test card notes",
            "benefit_active": "true",
        }
    )
    row.update(overrides)
    return row


def write_csv(tmp_path, rows: list[dict[str, str]], columns=CSV_COLUMNS):
    path = tmp_path / "card.csv"
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})
    return path


def count_rows(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_preview_plans_definitions_and_current_periods(tmp_path, db_session):
    csv_path = write_csv(
        tmp_path,
        [
            card_row(
                benefit_name="Monthly Dining",
                benefit_normalized_name="monthly dining",
                benefit_cycle_type="monthly",
                benefit_unit="usd_credit",
                benefit_default_amount_total="10.00",
            ),
            card_row(
                benefit_name="Annual Travel",
                benefit_normalized_name="annual travel",
                benefit_cycle_type="annual",
                benefit_unit="usd_credit",
                benefit_default_amount_total="300.00",
            ),
            card_row(
                benefit_name="Anniversary Credit",
                benefit_normalized_name="anniversary credit",
                benefit_cycle_type="anniversary",
                benefit_unit="usd_credit",
                benefit_default_amount_total="100.00",
            ),
            card_row(
                benefit_name="Certificate Benefit",
                benefit_normalized_name="certificate benefit",
                benefit_cycle_type="cert",
                benefit_unit="cert",
                benefit_default_amount_total="1.00",
            ),
        ],
    )

    plan = build_plan(csv_path, as_of=date(2026, 7, 20))
    output = plan_output(plan, db_session, include_details=True)

    assert output["summary"]["blocking_issues"] is False
    assert output["summary"]["planned_cards"] == 1
    assert output["summary"]["planned_benefit_definitions"] == 4
    assert output["actions"]["cards"] == {"create": 1}
    assert output["actions"]["benefit_definitions"] == {"create": 4}
    assert output["actions"]["current_periods"] == {"create": 3}
    assert {
        period["period_key"]
        for period in output["planned_records"]["current_periods"]
    } == {"2026-07", "2026", "2026-07-15~2027-07-15"}


def test_apply_creates_card_definitions_and_current_periods_idempotently(
    tmp_path, db_session
):
    csv_path = write_csv(
        tmp_path,
        [
            card_row(
                benefit_name="Monthly Dining",
                benefit_normalized_name="monthly dining",
                benefit_cycle_type="monthly",
                benefit_unit="usd_credit",
                benefit_default_amount_total="10.00",
            ),
            card_row(
                benefit_name="Annual Travel",
                benefit_normalized_name="annual travel",
                benefit_cycle_type="annual",
                benefit_unit="usd_credit",
                benefit_default_amount_total="300.00",
            ),
            card_row(
                benefit_name="Anniversary Credit",
                benefit_normalized_name="anniversary credit",
                benefit_cycle_type="anniversary",
                benefit_unit="usd_credit",
                benefit_default_amount_total="100.00",
            ),
        ],
    )

    first = apply_plan(build_plan(csv_path, as_of=date(2026, 7, 20)), db_session)

    assert first["applied"] is True
    assert first["created_cards"] == 1
    assert first["created_benefit_definitions"] == 3
    assert first["rollover"]["created"] == 3
    assert count_rows(db_session, CardMaster) == 1
    assert count_rows(db_session, BenefitDefinition) == 3
    assert count_rows(db_session, BenefitPeriod) == 3
    assert count_rows(db_session, UsageEvent) == 0

    second = apply_plan(build_plan(csv_path, as_of=date(2026, 7, 20)), db_session)

    assert second["applied"] is True
    assert second["created_cards"] == 0
    assert second["created_benefit_definitions"] == 0
    assert second["rollover"]["created"] == 0
    assert second["rollover"]["existing"] == 3
    assert count_rows(db_session, CardMaster) == 1
    assert count_rows(db_session, BenefitDefinition) == 3
    assert count_rows(db_session, BenefitPeriod) == 3

    reconciled = reconcile_plan(build_plan(csv_path, as_of=date(2026, 7, 20)), db_session)
    assert reconciled["summary"]["issues"] == 0


def test_apply_blocks_existing_card_conflict(tmp_path, db_session):
    db_session.add(
        CardMaster(
            slug="test-card",
            display_name="Different Card",
            card_name="Different Card",
            issuer="Other Bank",
            status="active",
        )
    )
    db_session.commit()
    csv_path = write_csv(
        tmp_path,
        [
            card_row(
                benefit_name="Monthly Dining",
                benefit_normalized_name="monthly dining",
                benefit_cycle_type="monthly",
                benefit_unit="usd_credit",
                benefit_default_amount_total="10.00",
            )
        ],
    )

    result = apply_plan(build_plan(csv_path, as_of=date(2026, 7, 20)), db_session)

    assert result["applied"] is False
    assert result["blocked"] is True
    assert result["actions"]["cards"] == {"conflict": 1}
    assert {warning["type"] for warning in result["warnings"]} == {"card_conflict"}
    assert count_rows(db_session, CardMaster) == 1
    assert count_rows(db_session, BenefitDefinition) == 0


def test_parser_rejects_period_and_usage_columns(tmp_path, db_session):
    columns = (*CSV_COLUMNS, "period_key", "initial_used_amount")
    csv_path = write_csv(
        tmp_path,
        [
            card_row(
                benefit_name="Monthly Dining",
                benefit_normalized_name="monthly dining",
                benefit_cycle_type="monthly",
                benefit_unit="usd_credit",
                benefit_default_amount_total="10.00",
            )
        ],
        columns=columns,
    )

    plan = build_plan(csv_path, as_of=date(2026, 7, 20))
    output = plan_output(plan, db_session, include_details=False)

    assert output["summary"]["blocking_issues"] is True
    assert output["summary"]["planned_cards"] == 0
    assert output["summary"]["planned_benefit_definitions"] == 0
    assert output["warning_types"]["forbidden_period_or_usage_columns"] == 1
    assert output["skipped_rows"] == [{"row": 1, "reason": "invalid_header"}]


def test_missing_open_month_day_warns_but_imports_definition(tmp_path, db_session):
    csv_path = write_csv(
        tmp_path,
        [
            card_row(
                card_open_date="",
                card_open_month="",
                card_open_day="",
                benefit_name="Anniversary Credit",
                benefit_normalized_name="anniversary credit",
                benefit_cycle_type="anniversary",
                benefit_unit="usd_credit",
                benefit_default_amount_total="100.00",
            )
        ],
    )

    result = apply_plan(build_plan(csv_path, as_of=date(2026, 7, 20)), db_session)

    assert result["applied"] is True
    assert {warning["type"] for warning in result["warnings"]} == {"missing_open_month_day"}
    assert result["rollover"]["created"] == 0
    assert result["rollover"]["skipped"] == 1
    assert result["rollover"]["warnings"][0]["type"] == "missing_open_month_day"
    assert count_rows(db_session, CardMaster) == 1
    assert count_rows(db_session, BenefitDefinition) == 1
    assert count_rows(db_session, BenefitPeriod) == 0
