from __future__ import annotations

from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BenefitDefinition, BenefitPeriod, CardMaster, CardSourceConfig, BenefitSourceConfig, User, Base
from app.services.catalog import DuplicateCardError
from app.main import app
from app.db import get_session
from app.auth import get_current_user
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
        session.commit()
    
    def override_get_session():
        with TestingSessionLocal() as session:
            yield session

    def override_get_current_user():
        return User(user_id=1, username="test_user", email="test@example.com")

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_current_user] = override_get_current_user

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture()
def session(client):
    generator = app.dependency_overrides[get_session]()
    session = next(generator)
    yield session
    try:
        next(generator)
    except StopIteration:
        pass


@pytest.fixture()
def current_user(session: Session):
    return session.execute(select(User).where(User.user_id == 1)).scalar_one()




def test_list_issuers(client, session: Session):
    # Seed
    card1 = CardSourceConfig(slug="slug1", display_name="Card 1", card_name="C1", issuer="Issuer A")
    card2 = CardSourceConfig(slug="slug2", display_name="Card 2", card_name="C2", issuer="Issuer B")
    card3 = CardSourceConfig(slug="slug3", display_name="Card 3", card_name="C3", issuer="Issuer A")
    session.add_all([card1, card2, card3])
    session.commit()

    response = client.get("/api/catalog/issuers")
    assert response.status_code == 200
    data = response.json()
    assert data["issuers"] == ["Issuer A", "Issuer B"]


def test_list_cards(client, session: Session):
    card1 = CardSourceConfig(slug="slug1", display_name="Card 1", card_name="C1", issuer="Issuer A", annual_fee=Decimal("95.00"))
    card2 = CardSourceConfig(slug="slug2", display_name="Card 2", card_name="C2", issuer="Issuer B", annual_fee=Decimal("0.00"))
    card3 = CardSourceConfig(slug="slug3", display_name="Card 3", card_name="C3", issuer="Issuer A", annual_fee=Decimal("550.00"))
    session.add_all([card1, card2, card3])
    session.commit()

    response = client.get("/api/catalog/cards?issuer=Issuer A")
    assert response.status_code == 200
    data = response.json()
    assert len(data["cards"]) == 2
    slugs = [c["slug"] for c in data["cards"]]
    assert "slug1" in slugs
    assert "slug3" in slugs


def test_card_detail(client, session: Session):
    card1 = CardSourceConfig(slug="slug1", display_name="Card 1", card_name="C1", issuer="Issuer A")
    session.add(card1)
    session.commit()
    
    ben1 = BenefitSourceConfig(
        source_id=card1.source_id,
        name="Ben 1",
        normalized_name="ben_1",
        cycle_type="monthly",
        default_amount_total=Decimal("10.00"),
    )
    session.add(ben1)
    session.commit()

    response = client.get(f"/api/catalog/cards/{card1.source_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["slug"] == "slug1"
    assert len(data["benefit_source_configs"]) == 1
    assert data["benefit_source_configs"][0]["name"] == "Ben 1"


def test_add_card(client, session: Session, current_user):
    card1 = CardSourceConfig(slug="slug1", display_name="Card 1", card_name="C1", issuer="Issuer A")
    session.add(card1)
    session.commit()
    ben1 = BenefitSourceConfig(
        source_id=card1.source_id,
        name="Ben 1",
        normalized_name="ben_1",
        cycle_type="monthly",
        default_amount_total=Decimal("10.00"),
    )
    session.add(ben1)
    session.commit()

    payload = {
        "source_id": card1.source_id,
        "open_date": "2026-08-01",
    }
    response = client.post("/api/catalog/add", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["slug"] == "slug1"
    assert data["display_name"] == "Card 1"

    # Verify db state
    card = session.execute(select(CardMaster).where(CardMaster.card_id == data["card_id"])).scalar_one()
    assert card.slug == "slug1"
    assert card.open_month == 8
    assert card.open_day == 1
    
    defs = session.execute(select(BenefitDefinition).where(BenefitDefinition.card_id == card.card_id)).scalars().all()
    assert len(defs) == 1
    assert defs[0].name == "Ben 1"

    # Because it is monthly, rollover should create periods
    periods = session.execute(select(BenefitPeriod).where(BenefitPeriod.benefit_definition_id == defs[0].benefit_definition_id)).scalars().all()
    assert len(periods) > 0


def test_add_card_duplicate(client, session: Session, current_user):
    card1 = CardSourceConfig(slug="slug1", display_name="Card 1", card_name="C1", issuer="Issuer A")
    session.add(card1)
    session.commit()

    payload = {
        "source_id": card1.source_id,
    }
    client.post("/api/catalog/add", json=payload)

    response2 = client.post("/api/catalog/add", json=payload)
    assert response2.status_code == 409
    
    payload["force"] = True
    response3 = client.post("/api/catalog/add", json=payload)
    assert response3.status_code == 201
    
    data3 = response3.json()
    assert data3["slug"] == "slug1-2"
