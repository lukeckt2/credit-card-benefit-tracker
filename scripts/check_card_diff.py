#!/usr/bin/env python3
import sys
from pathlib import Path
from decimal import Decimal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.card_csv_import import build_plan, decimal_equal, normalize_optional
from scripts.import_card_csv import make_session, parse_date
from app.models import CardMaster
from sqlalchemy import select
from datetime import date

def main():
    plan = build_plan(Path("new_card/users_card/Chase United Business copy.csv"), as_of=date.today())
    if not plan.card:
        print("No valid card in CSV")
        return

    with make_session() as session:
        card = session.scalar(select(CardMaster).where(CardMaster.slug == plan.card.slug, CardMaster.user_id == 1))
        if not card:
            print("Card not found in DB")
            return

        fields = [
            "display_name", "card_name", "issuer", "annual_fee", "status",
            "open_date", "open_month", "open_day", "source_url", "notes"
        ]
        print(f"Comparing card {card.slug}:")
        for field in fields:
            db_val = getattr(card, field)
            csv_val = getattr(plan.card, field)
            if field == "annual_fee":
                if not decimal_equal(db_val, csv_val):
                    print(f"{field}: DB={db_val} CSV={csv_val}")
            else:
                if db_val != csv_val:
                    print(f"{field}: DB={db_val} CSV={csv_val}")

if __name__ == "__main__":
    main()
