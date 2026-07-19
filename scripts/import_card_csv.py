#!/usr/bin/env python3
"""Import one new card and benefit definitions from a CSV file.

Use cases:

- Preview a draft CSV without writing:
  `.venv/bin/python scripts/import_card_csv.py preview --csv "new_card/Chase UA Business.csv" --pretty --details`
- Apply after reviewing preview output:
  `.venv/bin/python scripts/import_card_csv.py apply --csv "new_card/Chase UA Business.csv" --yes --pretty`
- Reconcile database state after apply:
  `.venv/bin/python scripts/import_card_csv.py reconcile --csv "new_card/Chase UA Business.csv" --pretty`
- Generate current periods for a specific date:
  add `--as-of YYYY-MM-DD` to preview/apply/reconcile.

Behavior:

- Reads the simplified add-card CSV template: card fields plus benefit-definition fields only.
- Creates or verifies `card_master` and `benefit_definitions` rows.
- After apply, creates missing current benefit periods through the rollover service.
- Does not import used amounts; users update usage later from the UI.
- Uses `MIGRATION_DATABASE_*` credentials from `.env`, falling back to `DATABASE_*`.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import build_database_url, load_dotenv  # noqa: E402
from app.services.card_csv_import import (  # noqa: E402
    apply_plan,
    build_plan,
    plan_output,
    reconcile_plan,
)


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected YYYY-MM-DD") from error


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
    parser.add_argument(
        "mode",
        choices=("preview", "apply", "reconcile"),
        help="CSV import mode to run.",
    )
    parser.add_argument("--csv", required=True, type=Path, help="Add-card CSV path.")
    parser.add_argument(
        "--as-of",
        type=parse_date,
        default=date.today(),
        help="Date used for current-period generation. Defaults to today.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    parser.add_argument(
        "--details",
        action="store_true",
        help="Include planned card, definition, and current-period records in preview output.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required for apply mode after preview review and explicit approval.",
    )
    return parser.parse_args()


def print_json(data: dict, pretty: bool) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2 if pretty else None, sort_keys=True))


def main() -> int:
    args = parse_args()
    plan = build_plan(args.csv, as_of=args.as_of)

    with make_session() as session:
        if args.mode == "preview":
            print_json(plan_output(plan, session, include_details=args.details), args.pretty)
            return 0

        if args.mode == "apply":
            if not args.yes:
                raise SystemExit("apply mode requires --yes after preview review and explicit approval")
            result = apply_plan(plan, session)
            print_json(result, args.pretty)
            return 0 if result.get("applied") else 1

        result = reconcile_plan(plan, session)
        print_json(result, args.pretty)
        return 1 if result["summary"]["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
