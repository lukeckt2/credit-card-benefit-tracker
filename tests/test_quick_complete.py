"""Tests for the quick-complete checkbox feature (POST /benefit-periods/{id}/quick-complete)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.db import get_session
from app.main import app
from app.models import Base, BenefitDefinition, BenefitPeriod, CardMaster, UsageEvent, User


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

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
        user = User(user_id=1, username="test_user", email="test@example.com")
        session.add(user)
        session.flush()

        card = CardMaster(
            user_id=1,
            slug="test-card",
            display_name="Test Card",
            card_name="Test Card Preferred",
            issuer="Test Bank",
            status="active",
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
        # Starts with $5 already used (out of $20 total)
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

        # A second period with amount_total = 0 (unlimited/uncapped)
        unlimited_period = BenefitPeriod(
            benefit_definition=definition,
            period_key="2026-08",
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 31),
            deadline=date(2026, 8, 31),
            amount_total=Decimal("0.00"),
            status="pending",
        )

        session.add_all([card, definition, period, usage, unlimited_period])
        session.commit()
        ids = {
            "card_id": card.card_id,
            "definition_id": definition.benefit_definition_id,
            "period_id": period.benefit_period_id,
            "unlimited_period_id": unlimited_period.benefit_period_id,
        }

    def override_session():
        with TestingSessionLocal() as session:
            yield session

    def override_get_current_user():
        return User(user_id=1, username="test_user", email="test@example.com")

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = override_get_current_user
    with TestClient(app) as test_client:
        yield test_client, ids, TestingSessionLocal
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# Checking (completed=True) — happy path
# ---------------------------------------------------------------------------

def test_quick_complete_check_sets_used_to_total(client):
    """Checking the box should set used to amount_total and mark the period completed."""
    test_client, ids, SessionLocal = client
    period_id = ids["period_id"]

    response = test_client.post(
        f"/api/benefit-periods/{period_id}/quick-complete",
        json={"completed": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["period"]["amount_used"] == 20.0
    assert data["period"]["amount_remaining"] == 0.0
    assert data["period"]["status"] == "completed"


def test_quick_complete_check_creates_adjustment_event(client):
    """Checking the box should create exactly one new adjustment UsageEvent with the correct delta."""
    test_client, ids, SessionLocal = client
    period_id = ids["period_id"]

    response = test_client.post(
        f"/api/benefit-periods/{period_id}/quick-complete",
        json={"completed": True},
    )

    assert response.status_code == 200
    data = response.json()
    # delta = 20.00 - 5.00 = 15.00
    assert data["usage_event"]["amount_delta"] == 15.0
    assert data["usage_event"]["event_type"] == "quick_complete"

    with SessionLocal() as session:
        event_count = session.scalar(
            select(func.count()).select_from(UsageEvent).where(
                UsageEvent.benefit_period_id == period_id
            )
        )
    # 1 import_initial + 1 quick-complete adjustment
    assert event_count == 2


def test_quick_complete_check_uses_default_note_when_none_provided(client):
    """The auto-generated note should mention 'checkbox' when no custom note is given."""
    test_client, ids, _ = client
    period_id = ids["period_id"]

    response = test_client.post(
        f"/api/benefit-periods/{period_id}/quick-complete",
        json={"completed": True},
    )

    assert response.status_code == 200
    note = response.json()["usage_event"]["note"]
    assert note is not None
    assert "checkbox" in note.lower()


def test_quick_complete_check_uses_custom_note_when_provided(client):
    """A caller-supplied note should be stored on the event."""
    test_client, ids, _ = client
    period_id = ids["period_id"]

    response = test_client.post(
        f"/api/benefit-periods/{period_id}/quick-complete",
        json={"completed": True, "note": "Marked done from mobile"},
    )

    assert response.status_code == 200
    assert response.json()["usage_event"]["note"] == "Marked done from mobile"


# ---------------------------------------------------------------------------
# Unchecking (completed=False) — happy path
# ---------------------------------------------------------------------------

def test_quick_complete_uncheck_resets_used_to_zero(client):
    """Unchecking the box should set used to 0 and restore the period to pending."""
    test_client, ids, _ = client
    period_id = ids["period_id"]

    response = test_client.post(
        f"/api/benefit-periods/{period_id}/quick-complete",
        json={"completed": False},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["period"]["amount_used"] == 0.0
    assert data["period"]["amount_remaining"] == 20.0
    assert data["period"]["status"] == "pending"


def test_quick_complete_uncheck_creates_negative_adjustment_event(client):
    """Unchecking should create an event with a negative delta equal to what was used."""
    test_client, ids, _ = client
    period_id = ids["period_id"]

    response = test_client.post(
        f"/api/benefit-periods/{period_id}/quick-complete",
        json={"completed": False},
    )

    assert response.status_code == 200
    # delta = 0 - 5.00 = -5.00
    assert response.json()["usage_event"]["amount_delta"] == -5.0


def test_quick_complete_roundtrip_check_then_uncheck(client):
    """Check then uncheck should return the period to its original used amount."""
    test_client, ids, SessionLocal = client
    period_id = ids["period_id"]

    # Check
    r1 = test_client.post(
        f"/api/benefit-periods/{period_id}/quick-complete",
        json={"completed": True},
    )
    assert r1.status_code == 200
    assert r1.json()["period"]["status"] == "completed"

    # Uncheck
    r2 = test_client.post(
        f"/api/benefit-periods/{period_id}/quick-complete",
        json={"completed": False},
    )
    assert r2.status_code == 200
    data = r2.json()
    assert data["period"]["amount_used"] == 5.0
    assert data["period"]["status"] == "pending"

    with SessionLocal() as session:
        event_count = session.scalar(
            select(func.count()).select_from(UsageEvent).where(
                UsageEvent.benefit_period_id == period_id
            )
        )
    # import_initial + check adjustment + uncheck adjustment
    assert event_count == 3


# ---------------------------------------------------------------------------
# Zero-delta guard (no-op detection)
# ---------------------------------------------------------------------------

def test_quick_complete_check_when_already_fully_used_returns_422(client):
    """Checking a period that is already fully used is a no-op and should return 422."""
    test_client, ids, _ = client
    period_id = ids["period_id"]

    # First, fully complete the period
    test_client.post(
        f"/api/benefit-periods/{period_id}/quick-complete",
        json={"completed": True},
    )

    # Attempt to check again — delta would be 0
    response = test_client.post(
        f"/api/benefit-periods/{period_id}/quick-complete",
        json={"completed": True},
    )

    assert response.status_code == 422
    assert "No change" in response.json()["detail"]


def test_quick_complete_uncheck_when_already_zero_returns_422(client):
    """Unchecking a period that already has 0 used is a no-op and should return 422."""
    test_client, ids, SessionLocal = client
    period_id = ids["period_id"]

    # First, zero out the period
    test_client.post(
        f"/api/benefit-periods/{period_id}/quick-complete",
        json={"completed": False},
    )

    # Attempt to uncheck again — delta would be 0
    response = test_client.post(
        f"/api/benefit-periods/{period_id}/quick-complete",
        json={"completed": False},
    )

    assert response.status_code == 422
    assert "No change" in response.json()["detail"]


def test_quick_complete_no_op_does_not_create_event(client):
    """A no-op request should leave the event count unchanged."""
    test_client, ids, SessionLocal = client
    period_id = ids["period_id"]

    # Zero out first
    test_client.post(
        f"/api/benefit-periods/{period_id}/quick-complete",
        json={"completed": False},
    )

    # No-op: uncheck again
    test_client.post(
        f"/api/benefit-periods/{period_id}/quick-complete",
        json={"completed": False},
    )

    with SessionLocal() as session:
        event_count = session.scalar(
            select(func.count()).select_from(UsageEvent).where(
                UsageEvent.benefit_period_id == period_id
            )
        )
    # import_initial + 1 zero-out adjustment; the no-op should NOT add a third
    assert event_count == 2


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_quick_complete_returns_404_for_unknown_period(client):
    """Requesting quick-complete on a non-existent period ID should return 404."""
    test_client, _, _ = client

    response = test_client.post(
        "/api/benefit-periods/99999/quick-complete",
        json={"completed": True},
    )

    assert response.status_code == 404


def test_quick_complete_rejects_invalid_payload(client):
    """Missing required 'completed' field should return 422."""
    test_client, ids, _ = client
    period_id = ids["period_id"]

    response = test_client.post(
        f"/api/benefit-periods/{period_id}/quick-complete",
        json={"note": "no completed field"},
    )

    assert response.status_code == 422


def test_quick_complete_rejects_extra_fields(client):
    """Extra fields should be rejected by StrictBaseModel (extra='forbid')."""
    test_client, ids, _ = client
    period_id = ids["period_id"]

    response = test_client.post(
        f"/api/benefit-periods/{period_id}/quick-complete",
        json={"completed": True, "unexpected_field": "bad"},
    )

    assert response.status_code == 422
