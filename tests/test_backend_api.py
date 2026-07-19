from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.main import app
from app.models import Base, BenefitDefinition, BenefitPeriod, CardMaster, UsageEvent


@pytest.fixture()
def client():
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
        card = CardMaster(
            slug="test-card",
            display_name="Test Card",
            card_name="Test Card Preferred",
            issuer="Test Bank",
            status="active",
            open_month=5,
            open_day=10,
        )
        definition = BenefitDefinition(
            card=card,
            name="Monthly Dining",
            normalized_name="monthly dining",
            cycle_type="monthly",
            unit="usd_credit",
            default_amount_total=Decimal("20.00"),
            active=True,
        )
        period = BenefitPeriod(
            benefit_definition=definition,
            period_key="2026-07",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            deadline=date(2026, 7, 31),
            amount_total=Decimal("20.00"),
            status="pending",
        )
        usage = UsageEvent(
            benefit_period=period,
            event_type="import_initial",
            amount_delta=Decimal("5.00"),
            source_key="seed:test-card:monthly-dining:2026-07",
        )
        session.add_all([card, definition, period, usage])
        session.commit()
        ids = {
            "card_id": card.card_id,
            "definition_id": definition.benefit_definition_id,
            "period_id": period.benefit_period_id,
        }

    def override_session():
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client, ids, TestingSessionLocal
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def section_rows(data: dict, key: str) -> list[dict]:
    for section in data["sections"]:
        if section["key"] == key:
            return section["rows"]
    raise AssertionError(f"Dashboard section {key} was not returned.")


def visible_period_ids(data: dict) -> set[int]:
    return {
        row["period_id"]
        for section in data["sections"]
        for row in section["rows"]
    }


def test_dashboard_derives_usage_totals(client):
    test_client, ids, _ = client

    health = test_client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "database": "not_checked"}

    frontend = test_client.get("/")
    assert frontend.status_code == 200
    assert "Benefit Dashboard" in frontend.text

    response = test_client.get("/api/dashboard", params={"as_of": "2026-07-19"})

    assert response.status_code == 200
    data = response.json()
    assert data["as_of"] == "2026-07-19"
    assert [section["key"] for section in data["sections"]] == [
        "active_current",
        "due_within_45_days",
    ]

    rows = section_rows(data, "active_current")
    assert len(rows) == 1
    row = rows[0]
    assert row["period_id"] == ids["period_id"]
    assert row["benefit_definition_id"] == ids["definition_id"]
    assert row["card_name"] == "Test Card Preferred"
    assert row["amount_total"] == 20.0
    assert row["amount_used"] == 5.0
    assert row["amount_remaining"] == 15.0
    assert row["unit"] == "usd_credit"
    assert row["period_start"] == "2026-07-01"
    assert row["period_end"] == "2026-07-31"
    assert row["priority"] == "due_soon"
    assert row["is_current"] is True
    assert row["is_pending"] is True
    assert row["is_completed"] is False

    assert [row["period_id"] for row in section_rows(data, "due_within_45_days")] == [
        ids["period_id"]
    ]


def test_dashboard_defaults_to_current_periods_only(client):
    test_client, ids, SessionLocal = client

    with SessionLocal() as session:
        definition = session.get(BenefitDefinition, ids["definition_id"])
        session.add_all(
            [
                BenefitPeriod(
                    benefit_definition=definition,
                    period_key="2026-06",
                    period_start=date(2026, 6, 1),
                    period_end=date(2026, 6, 30),
                    deadline=date(2026, 6, 30),
                    amount_total=Decimal("20.00"),
                    status="pending",
                ),
                BenefitPeriod(
                    benefit_definition=definition,
                    period_key="2026-08",
                    period_start=date(2026, 8, 1),
                    period_end=date(2026, 8, 31),
                    deadline=date(2026, 8, 31),
                    amount_total=Decimal("20.00"),
                    status="pending",
                ),
            ]
        )
        session.commit()

    response = test_client.get("/api/dashboard", params={"as_of": "2026-07-19"})

    assert response.status_code == 200
    assert visible_period_ids(response.json()) == {ids["period_id"]}


def test_dashboard_sections_for_active_due_and_completed_rows(client):
    test_client, ids, SessionLocal = client

    with SessionLocal() as session:
        card = session.get(CardMaster, ids["card_id"])
        cert_definition = BenefitDefinition(
            card=card,
            name="Free Night Certificate",
            normalized_name="free night certificate",
            cycle_type="cert",
            unit="cert",
            default_amount_total=Decimal("1.00"),
            active=True,
        )
        cert_period = BenefitPeriod(
            benefit_definition=cert_definition,
            period_key="2026-cert",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            deadline=date(2026, 7, 10),
            amount_total=Decimal("1.00"),
            status="pending",
        )
        annual_definition = BenefitDefinition(
            card=card,
            name="Annual Travel Credit",
            normalized_name="annual travel credit",
            cycle_type="annual",
            unit="usd_credit",
            default_amount_total=Decimal("100.00"),
            active=True,
        )
        completed_period = BenefitPeriod(
            benefit_definition=annual_definition,
            period_key="2026",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
            deadline=date(2026, 12, 31),
            amount_total=Decimal("100.00"),
            status="completed",
        )
        zero_remaining_period = BenefitPeriod(
            benefit_definition=annual_definition,
            period_key="2026-zero-pending",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
            deadline=date(2026, 12, 31),
            amount_total=Decimal("100.00"),
            status="pending",
        )
        zero_remaining_usage = UsageEvent(
            benefit_period=zero_remaining_period,
            event_type="usage",
            amount_delta=Decimal("100.00"),
        )
        session.add_all(
            [
                cert_definition,
                cert_period,
                annual_definition,
                completed_period,
                zero_remaining_period,
                zero_remaining_usage,
            ]
        )
        session.commit()
        cert_period_id = cert_period.benefit_period_id
        completed_period_id = completed_period.benefit_period_id
        zero_remaining_period_id = zero_remaining_period.benefit_period_id

    response = test_client.get("/api/dashboard", params={"as_of": "2026-07-19"})

    assert response.status_code == 200
    data = response.json()
    assert cert_period_id in {
        row["period_id"] for row in section_rows(data, "active_current")
    }
    assert cert_period_id not in {
        row["period_id"] for row in section_rows(data, "due_within_45_days")
    }
    assert completed_period_id not in {
        row["period_id"] for row in section_rows(data, "active_current")
    }
    assert completed_period_id not in {
        row["period_id"]
        for section in data["sections"]
        for row in section["rows"]
    }
    assert zero_remaining_period_id not in {
        row["period_id"]
        for section in data["sections"]
        for row in section["rows"]
    }


def test_usage_events_and_adjustments_are_append_only(client):
    test_client, ids, SessionLocal = client
    period_id = ids["period_id"]

    response = test_client.post(
        f"/api/benefit-periods/{period_id}/usage-events",
        json={"amount_delta": "3.50", "note": "Lunch credit"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["usage_event"]["event_type"] == "usage"
    assert data["usage_event"]["amount_delta"] == 3.5
    assert data["period"]["amount_used"] == 8.5

    response = test_client.post(
        f"/api/benefit-periods/{period_id}/usage-adjustment",
        json={"current_used_amount": "10.00", "event_type": "correction"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["usage_event"]["event_type"] == "correction"
    assert data["usage_event"]["amount_delta"] == 1.5
    assert data["period"]["amount_used"] == 10.0

    response = test_client.post(
        f"/api/benefit-periods/{period_id}/usage-events",
        json={"amount_delta": "1.00", "event_type": "correction"},
    )
    assert response.status_code == 422

    response = test_client.patch(
        f"/api/benefit-periods/{period_id}", json={"amount_used": "0.00"}
    )
    assert response.status_code == 422

    with SessionLocal() as session:
        event_count = session.scalar(
            select(func.count()).select_from(UsageEvent).where(
                UsageEvent.benefit_period_id == period_id
            )
        )
    assert event_count == 3


def test_usage_adjustment_syncs_completion_status_and_dashboard(client):
    test_client, ids, SessionLocal = client
    period_id = ids["period_id"]

    response = test_client.post(
        f"/api/benefit-periods/{period_id}/usage-adjustment",
        json={"current_used_amount": "20.00", "event_type": "correction"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["period"]["status"] == "completed"
    assert data["period"]["amount_remaining"] == 0.0

    dashboard = test_client.get("/api/dashboard", params={"as_of": "2026-07-19"})
    assert dashboard.status_code == 200
    assert period_id not in visible_period_ids(dashboard.json())

    response = test_client.post(
        f"/api/benefit-periods/{period_id}/usage-adjustment",
        json={"current_used_amount": "10.00", "event_type": "correction"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["period"]["status"] == "pending"
    assert data["period"]["amount_remaining"] == 10.0

    dashboard = test_client.get("/api/dashboard", params={"as_of": "2026-07-19"})
    assert dashboard.status_code == 200
    assert period_id in visible_period_ids(dashboard.json())

    with SessionLocal() as session:
        event_count = session.scalar(
            select(func.count()).select_from(UsageEvent).where(
                UsageEvent.benefit_period_id == period_id
            )
        )
    assert event_count == 3


def test_complete_requires_no_remaining_and_reopen_preserves_usage(client):
    test_client, ids, SessionLocal = client
    period_id = ids["period_id"]

    response = test_client.post(f"/api/benefit-periods/{period_id}/complete")

    assert response.status_code == 422
    assert "remaining" in response.json()["detail"]

    response = test_client.patch(
        f"/api/benefit-periods/{period_id}", json={"status": "completed"}
    )
    assert response.status_code == 422

    response = test_client.post(
        f"/api/benefit-periods/{period_id}/usage-adjustment",
        json={"current_used_amount": "20.00", "event_type": "correction"},
    )
    assert response.status_code == 200
    assert response.json()["period"]["status"] == "completed"
    assert response.json()["period"]["amount_remaining"] == 0.0

    response = test_client.post(f"/api/benefit-periods/{period_id}/complete")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["amount_used"] == 20.0

    response = test_client.post(f"/api/benefit-periods/{period_id}/reopen")

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["amount_used"] == 20.0

    with SessionLocal() as session:
        event_count = session.scalar(
            select(func.count()).select_from(UsageEvent).where(
                UsageEvent.benefit_period_id == period_id
            )
        )
    assert event_count == 2


def test_delete_benefit_definition_removes_periods_and_usage(client):
    test_client, ids, SessionLocal = client

    with SessionLocal() as session:
        card = session.get(CardMaster, ids["card_id"])
        sibling_definition = BenefitDefinition(
            card=card,
            name="Annual Travel Credit",
            normalized_name="annual travel credit",
            cycle_type="annual",
            unit="usd_credit",
            default_amount_total=Decimal("100.00"),
            active=True,
        )
        sibling_period = BenefitPeriod(
            benefit_definition=sibling_definition,
            period_key="2026",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
            deadline=date(2026, 12, 31),
            amount_total=Decimal("100.00"),
            status="pending",
        )
        sibling_usage = UsageEvent(
            benefit_period=sibling_period,
            event_type="usage",
            amount_delta=Decimal("10.00"),
        )
        session.add_all([sibling_definition, sibling_period, sibling_usage])
        session.commit()

    response = test_client.delete(f"/api/benefit-definitions/{ids['definition_id']}")

    assert response.status_code == 204
    assert response.content == b""

    response = test_client.get(f"/api/benefit-definitions/{ids['definition_id']}")
    assert response.status_code == 404

    response = test_client.delete(f"/api/benefit-definitions/{ids['definition_id']}")
    assert response.status_code == 404

    with SessionLocal() as session:
        assert session.get(CardMaster, ids["card_id"]) is not None
        assert session.scalar(select(func.count()).select_from(BenefitDefinition)) == 1
        assert session.scalar(select(func.count()).select_from(BenefitPeriod)) == 1
        assert session.scalar(select(func.count()).select_from(UsageEvent)) == 1


def test_delete_card_removes_definitions_periods_and_usage(client):
    test_client, ids, SessionLocal = client

    with SessionLocal() as session:
        other_card = CardMaster(
            slug="other-card",
            display_name="Other Card",
            card_name="Other Card Preferred",
            issuer="Other Bank",
            status="active",
        )
        other_definition = BenefitDefinition(
            card=other_card,
            name="Other Dining",
            normalized_name="other dining",
            cycle_type="monthly",
            unit="usd_credit",
            default_amount_total=Decimal("15.00"),
            active=True,
        )
        other_period = BenefitPeriod(
            benefit_definition=other_definition,
            period_key="2026-07",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            deadline=date(2026, 7, 31),
            amount_total=Decimal("15.00"),
            status="pending",
        )
        other_usage = UsageEvent(
            benefit_period=other_period,
            event_type="usage",
            amount_delta=Decimal("7.50"),
        )
        session.add_all([other_card, other_definition, other_period, other_usage])
        session.commit()
        other_card_id = other_card.card_id

    response = test_client.delete(f"/api/cards/{ids['card_id']}")

    assert response.status_code == 204
    assert response.content == b""

    response = test_client.get(f"/api/cards/{ids['card_id']}")
    assert response.status_code == 404

    response = test_client.delete(f"/api/cards/{ids['card_id']}")
    assert response.status_code == 404

    with SessionLocal() as session:
        assert session.get(CardMaster, other_card_id) is not None
        assert session.scalar(select(func.count()).select_from(CardMaster)) == 1
        assert session.scalar(select(func.count()).select_from(BenefitDefinition)) == 1
        assert session.scalar(select(func.count()).select_from(BenefitPeriod)) == 1
        assert session.scalar(select(func.count()).select_from(UsageEvent)) == 1


def test_rollover_preview_apply_and_rerun_are_idempotent(client, monkeypatch):
    test_client, ids, _ = client
    payload = {
        "window_start": "2026-08-01",
        "window_end": "2026-08-31",
        "definition_ids": [ids["definition_id"]],
    }

    preview = test_client.post("/api/admin/rollover/preview", json=payload)

    assert preview.status_code == 200
    assert preview.json()["dry_run"] is True
    assert preview.json()["would_create"] == 1
    assert preview.json()["periods"][0]["amount_total"] == 20.0

    periods_before_apply = test_client.get("/api/benefit-periods").json()["benefit_periods"]
    assert [period["period_key"] for period in periods_before_apply] == ["2026-07"]

    monkeypatch.setenv("ADMIN_LOCAL_ONLY", "false")
    applied = test_client.post("/api/admin/rollover/apply", json=payload)

    assert applied.status_code == 200
    assert applied.json()["created"] == 1

    repeated = test_client.post("/api/admin/rollover/apply", json=payload)
    assert repeated.status_code == 200
    assert repeated.json()["created"] == 0
    assert repeated.json()["existing"] == 1

    periods = test_client.get("/api/benefit-periods").json()["benefit_periods"]
    assert [period["period_key"] for period in periods] == ["2026-07", "2026-08"]

    original_period = test_client.get(f"/api/benefit-periods/{ids['period_id']}").json()
    assert original_period["amount_used"] == 5.0


def test_rollover_apply_is_local_only_by_default(client, monkeypatch):
    test_client, ids, _ = client
    monkeypatch.setenv("ADMIN_LOCAL_ONLY", "true")

    response = test_client.post(
        "/api/admin/rollover/apply",
        json={
            "window_start": "2026-09-01",
            "window_end": "2026-09-30",
            "definition_ids": [ids["definition_id"]],
        },
    )

    assert response.status_code == 403
