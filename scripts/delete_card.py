#!/usr/bin/env python3
"""Delete a card and all its cascading dependencies.

Use cases:

- Delete a card by ID:
  `MIGRATION_DATABASE=192.168.0.xxx APP_ENV=dev .venv/bin/python scripts/delete_card.py --card-id 123 --user-id 1 --yes`

Behavior:

- Removes UsageEvents, BenefitPeriods, BenefitDefinitions, and CardMaster for the given card_id.
- Uses `MIGRATION_DATABASE_*` credentials from `.env`, falling back to `DATABASE_*`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import build_database_url, load_dotenv
from app.services.deletion import delete_card
from app.services.errors import NotFoundError

def make_session() -> Session:
    load_dotenv(PROJECT_ROOT / ".env")
    engine = create_engine(
        build_database_url("MIGRATION_DATABASE"), pool_pre_ping=True, future=True
    )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)()

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--card-id", required=True, type=int, help="ID of the card to delete.")
    parser.add_argument("--user-id", required=True, type=int, help="ID of the user who owns the card.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt and delete immediately.",
    )
    return parser.parse_args()

def main() -> int:
    args = parse_args()
    
    if not args.yes:
        confirm = input(f"Are you sure you want to delete card_id={args.card_id} and ALL its associated benefits, periods, and usage data? [y/N]: ")
        if confirm.lower() not in ("y", "yes"):
            print("Aborted.")
            return 1
            
    from sqlalchemy.exc import OperationalError

    try:
        with make_session() as session:
            try:
                delete_card(session, args.card_id, user_id=args.user_id)
                session.commit()
                print(f"Successfully deleted card_id={args.card_id} and all related data.")
                return 0
            except NotFoundError as error:
                session.rollback()
                print(f"[ERROR] {error}", file=sys.stderr)
                return 1
            except Exception as e:
                session.rollback()
                print(f"[ERROR] An unexpected error occurred: {e}", file=sys.stderr)
                return 1
                
    except OperationalError as e:
        err_str = str(e)
        if "host.docker.internal" in err_str:
            print(
                "\n[ERROR] Database connection failed.\n"
                "You are running the script natively on the host machine, but the database host is configured as 'host.docker.internal'.\n"
                "Please run this command through docker-compose, or override the host by prepending `MIGRATION_DATABASE_HOST=127.0.0.1` (and `DATABASE_HOST=127.0.0.1`) to your command.\n",
                file=sys.stderr,
            )
        else:
            print(f"\n[ERROR] Database connection failed: {err_str}\n", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
