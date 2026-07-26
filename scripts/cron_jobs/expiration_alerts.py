#!/usr/bin/env python3
"""Check for expiring benefits and send email alerts."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from app.db import SessionLocal  # noqa: E402
from app.services.alert import check_and_send_expiration_alerts  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days-ahead",
        type=int,
        default=15,
        help="Number of days ahead to check for expiration (default: 15)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    with SessionLocal() as session:
        check_and_send_expiration_alerts(session, days_ahead=args.days_ahead)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
