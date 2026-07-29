#!/usr/bin/env python3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.import_card_csv import make_session
from app.models import CardMaster
from sqlalchemy import select

def main():
    with make_session() as session:
        cards = session.scalars(select(CardMaster).where(CardMaster.slug == 'chase-united-business')).all()
        for c in cards:
            print(f"user_id: {c.user_id}, open_date: {c.open_date}, month: {c.open_month}, day: {c.open_day}")

if __name__ == "__main__":
    main()
