"""Push updates from the global catalog templates down to existing user cards.

This script ensures that users' existing cards (in the `card_master` table) and their 
benefits (in `benefit_definition`) are aligned with the latest templates in the catalog 
(`card_source_config` and `benefit_source_config`).

Usage:
    # Dry run (default):
    # Will print out what WOULD change, but will not modify existing values. 
    # It WILL, however, add missing newly-discovered benefits automatically.
    APP_ENV=dev python scripts/push_catalog_updates.py

    # Force run:
    # Will aggressively overwrite existing card and benefit fields (annual fee, URLs, 
    # benefit amounts, cycle types, etc.) with the latest values from the catalog.
    # WARNING: This will overwrite any custom data the user may have manually entered!
    APP_ENV=dev python scripts/push_catalog_updates.py --force
"""

from __future__ import annotations

import argparse
import calendar
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import build_database_url, load_dotenv
from app.models import BenefitDefinition, BenefitSourceConfig, CardMaster, CardSourceConfig
from app.schemas import RolloverRequest
from app.services.rollover import apply_rollover


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Push catalog updates to existing user cards.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Aggressively overwrite existing card and benefit properties with catalog values.",
    )
    return parser.parse_args()


def push_updates(session: Session, force: bool = False) -> None:
    # 1. Pre-fetch catalog templates for efficiency
    templates = session.execute(select(CardSourceConfig)).scalars().all()
    template_map_by_id = {t.source_id: t for t in templates}
    template_map_by_slug = {t.slug: t for t in templates}

    def get_template_by_slug(slug: str) -> CardSourceConfig | None:
        if slug in template_map_by_slug:
            return template_map_by_slug[slug]
        import re
        match = re.match(r"^(.*?)(?:-\d+)?$", slug)
        if match:
            base = match.group(1)
            if base in template_map_by_slug:
                return template_map_by_slug[base]
        return None

    # 2. Get all cards (linked and unlinked)
    cards = session.execute(select(CardMaster)).scalars().all()
    
    if not cards:
        print("No cards were found.")
        return

    cards_updated = 0
    benefits_updated = 0
    benefits_added = 0

    for card in cards:
        # Determine the template either by existing source_id or by slug matching
        template = None
        if card.source_id:
            template = template_map_by_id.get(card.source_id)
        else:
            template = get_template_by_slug(card.slug)

        if not template:
            # We don't print a warning for unlinked custom cards to avoid spam
            continue

        needs_commit = False

        # 3. Link card if it wasn't linked
        if card.source_id != template.source_id:
            if force:
                card.source_id = template.source_id
                needs_commit = True
                print(f"Linked card {card.card_id} ({card.slug}) to catalog source_id {template.source_id}")
            else:
                print(f"Dry-run: Would link card {card.card_id} ({card.slug}) to catalog source_id {template.source_id}")
                needs_commit = True

        # 4. Update Card Metadata
        card_fields_to_sync = ["annual_fee", "source_url"]
        for field in card_fields_to_sync:
            current_val = getattr(card, field)
            template_val = getattr(template, field)
            
            if current_val != template_val:
                if force:
                    setattr(card, field, template_val)
                    print(f"Updated card {card.card_id} ({card.slug}) field '{field}': {current_val} -> {template_val}")
                else:
                    print(f"Dry-run: Would update card {card.card_id} ({card.slug}) field '{field}': {current_val} -> {template_val}")
                needs_commit = True

        if needs_commit:
            cards_updated += 1

        # 2. Update existing benefits and add missing ones
        template_benefits = session.execute(
            select(BenefitSourceConfig).where(BenefitSourceConfig.source_id == template.source_id)
        ).scalars().all()
        
        existing_benefits = session.execute(
            select(BenefitDefinition).where(BenefitDefinition.card_id == card.card_id)
        ).scalars().all()
        
        existing_benefit_map = {b.normalized_name: b for b in existing_benefits}
        new_definition_ids = []

        for tb in template_benefits:
            existing_benefit = existing_benefit_map.get(tb.normalized_name)
            
            if existing_benefit:
                # Update existing benefit
                benefit_needs_commit = False
                benefit_fields = ["name", "category", "cycle_type", "unit", "default_amount_total", "amount_overrides", "notes"]
                
                for field in benefit_fields:
                    current_val = getattr(existing_benefit, field)
                    template_val = getattr(tb, field)
                    
                    if current_val != template_val:
                        if force:
                            setattr(existing_benefit, field, template_val)
                            print(f"Updated benefit '{tb.name}' (ID: {existing_benefit.benefit_definition_id}) field '{field}': {current_val} -> {template_val}")
                        else:
                            print(f"Dry-run: Would update benefit '{tb.name}' (ID: {existing_benefit.benefit_definition_id}) field '{field}': {current_val} -> {template_val}")
                        benefit_needs_commit = True
                            
                if benefit_needs_commit:
                    benefits_updated += 1
            else:
                # Add missing benefit
                print(f"Adding missing benefit '{tb.name}' to card {card.card_id} ({card.slug})")
                new_benefit = BenefitDefinition(
                    card_id=card.card_id,
                    name=tb.name,
                    normalized_name=tb.normalized_name,
                    category=tb.category,
                    cycle_type=tb.cycle_type,
                    unit=tb.unit,
                    default_amount_total=tb.default_amount_total,
                    amount_overrides=tb.amount_overrides,
                    notes=tb.notes,
                    active=True,
                )
                session.add(new_benefit)
                session.flush()
                new_definition_ids.append(new_benefit.benefit_definition_id)
                benefits_added += 1

        # 3. Trigger rollover for newly added benefits
        if new_definition_ids:
            today = date.today()
            _, last_day = calendar.monthrange(today.year, today.month)
            rollover_request = RolloverRequest(
                window_start=date(today.year, today.month, 1),
                window_end=date(today.year, today.month, last_day),
                definition_ids=new_definition_ids,
            )
            apply_rollover(session, rollover_request, user_id=card.user_id)

    session.commit()
    print("---")
    if force:
        print(f"Update Complete. Modified {cards_updated} cards, modified {benefits_updated} existing benefits, and added {benefits_added} new benefits.")
    else:
        print(f"Dry-run Complete. {cards_updated} cards would be modified, {benefits_updated} existing benefits would be modified.")
        print(f"Added {benefits_added} new benefits (this happens regardless of --force).")


def main() -> None:
    args = parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    url = build_database_url("DATABASE")
    engine = create_engine(url, future=True)
    SessionLocal = sessionmaker(bind=engine, future=True)
    with SessionLocal() as session:
        push_updates(session, force=args.force)


if __name__ == "__main__":
    main()
