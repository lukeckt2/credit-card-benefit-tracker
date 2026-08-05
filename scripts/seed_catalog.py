"""Idempotent seed script for card catalog templates.

Usage:
    APP_ENV=dev python scripts/seed_catalog.py
"""

from __future__ import annotations

import csv
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import build_database_url, load_dotenv
from app.models import Base, BenefitSourceConfig, CardSourceConfig
from app.utils.text import normalize_name

CSV_PATH = PROJECT_ROOT / "card_db" / "master_card_config.csv"


def parse_decimal(raw: str | None) -> Decimal | None:
    if not raw or not raw.strip():
        return None
    try:
        return Decimal(raw.strip().replace(",", "").replace("$", ""))
    except InvalidOperation:
        return None


def parse_overrides(raw: str | None) -> dict[str, float] | None:
    if not raw or not raw.strip():
        return None
    import json
    try:
        parsed = json.loads(raw.strip())
        if isinstance(parsed, dict):
            return {str(k): float(v) for k, v in parsed.items()}
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def seed(session: Session) -> None:
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Group rows by card_slug
    cards_data: dict[str, list[dict]] = {}
    for row in rows:
        slug = (row.get("card_slug") or "").strip()
        if not slug:
            continue
        cards_data.setdefault(slug, []).append(row)

    created_cards = 0
    updated_cards = 0
    created_benefits = 0
    updated_benefits = 0

    for slug, card_rows in cards_data.items():
        first = card_rows[0]

        # Upsert CardSourceConfig
        existing_card = session.execute(
            select(CardSourceConfig).where(CardSourceConfig.slug == slug)
        ).scalar_one_or_none()

        card_values = dict(
            display_name=(first.get("card_display_name") or "").strip(),
            card_name=(first.get("card_card_name") or "").strip(),
            issuer=(first.get("card_issuer") or "").strip(),
            annual_fee=parse_decimal(first.get("card_annual_fee")),
            source_url=(first.get("card_source_url") or "").strip() or None,
            image_url=(first.get("card_image_url") or "").strip() or None,
        )

        if existing_card:
            for key, value in card_values.items():
                setattr(existing_card, key, value)
            card_source = existing_card
            updated_cards += 1
        else:
            card_source = CardSourceConfig(slug=slug, **card_values)
            session.add(card_source)
            session.flush()
            created_cards += 1

        # Upsert BenefitSourceConfig rows
        for row in card_rows:
            benefit_name = (row.get("benefit_name") or "").strip()
            if not benefit_name:
                continue

            normalized = normalize_name(
                (row.get("benefit_normalized_name") or "").strip() or benefit_name
            )
            normalized = normalize_name(normalized)

            existing_benefit = session.execute(
                select(BenefitSourceConfig).where(
                    BenefitSourceConfig.source_id == card_source.source_id,
                    BenefitSourceConfig.normalized_name == normalized,
                )
            ).scalar_one_or_none()

            cycle_type = (row.get("benefit_cycle_type") or "").strip().lower().replace("-", "_")
            unit = (row.get("benefit_unit") or "").strip().lower().replace("-", "_") or None
            amount = parse_decimal(row.get("benefit_default_amount_total")) or Decimal("0")

            benefit_values = dict(
                name=benefit_name,
                cycle_type=cycle_type,
                unit=unit,
                default_amount_total=amount,
                amount_overrides=parse_overrides(row.get("benefit_amount_overrides")),
                notes=(row.get("benefit_notes") or "").strip() or None,
            )

            if existing_benefit:
                for key, value in benefit_values.items():
                    setattr(existing_benefit, key, value)
                updated_benefits += 1
            else:
                benefit = BenefitSourceConfig(
                    source_id=card_source.source_id,
                    normalized_name=normalized,
                    **benefit_values,
                )
                session.add(benefit)
                created_benefits += 1

    session.commit()
    print(f"Cards:    {created_cards} created, {updated_cards} updated")
    print(f"Benefits: {created_benefits} created, {updated_benefits} updated")


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    url = build_database_url("DATABASE")
    engine = create_engine(url, future=True)
    SessionLocal = sessionmaker(bind=engine, future=True)
    with SessionLocal() as session:
        seed(session)


if __name__ == "__main__":
    main()
