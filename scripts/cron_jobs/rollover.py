#!/usr/bin/env python3
"""Preview or apply recurring benefit-period rollover from cron.

Manual commands, run from the project root:

Preview a month without writing:
    ROLLOVER_MODE=preview ROLLOVER_MONTH=2026-08 ROLLOVER_PRETTY=1 scripts/cron_jobs/month_start_rollover.sh

Apply a month through the cron wrapper:
    ROLLOVER_MONTH=2026-08 scripts/cron_jobs/month_start_rollover.sh

Apply an explicit window through this Python entry point:
    scripts/cron_jobs/rollover.py apply --window-start 2026-08-01 --window-end 2026-08-31 --only-periods-starting-in-window --yes --pretty

Use preview before apply; direct apply mode requires --yes.
"""

from __future__ import annotations

import argparse
import calendar
from datetime import date
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_dotenv  # noqa: E402


load_dotenv(PROJECT_ROOT / ".env")

from app.db import SessionLocal  # noqa: E402
from app.schemas import RolloverRequest  # noqa: E402
from app.services.rollover import apply_rollover, preview_rollover  # noqa: E402


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected YYYY-MM-DD") from error


def parse_month_window(value: str) -> tuple[date, date]:
    try:
        year_text, month_text = value.split("-", 1)
        year = int(year_text)
        month = int(month_text)
        if not 1 <= month <= 12:
            raise ValueError
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected YYYY-MM") from error

    return (
        date(year, month, 1),
        date(year, month, calendar.monthrange(year, month)[1]),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preview", "apply"))
    parser.add_argument("--month", type=parse_month_window)
    parser.add_argument("--window-start", type=parse_date)
    parser.add_argument("--window-end", type=parse_date)
    parser.add_argument("--definition-id", action="append", type=int, dest="definition_ids")
    parser.add_argument("--include-inactive-cards", action="store_true")
    parser.add_argument("--include-inactive-definitions", action="store_true")
    parser.add_argument("--only-periods-starting-in-window", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required for apply mode after preview review.",
    )
    args = parser.parse_args()
    if args.month and (args.window_start or args.window_end):
        parser.error("--month cannot be combined with --window-start or --window-end")
    if args.month:
        args.window_start, args.window_end = args.month
    elif not args.window_start or not args.window_end:
        parser.error("Either --month or both --window-start and --window-end are required")
    return args


def main() -> int:
    args = parse_args()
    if args.mode == "apply" and not args.yes:
        raise SystemExit("apply mode requires --yes after preview review")

    request = RolloverRequest(
        window_start=args.window_start,
        window_end=args.window_end,
        definition_ids=args.definition_ids,
        include_inactive_cards=args.include_inactive_cards,
        include_inactive_definitions=args.include_inactive_definitions,
        only_periods_starting_in_window=args.only_periods_starting_in_window,
    )

    with SessionLocal() as session:
        if args.mode == "preview":
            response = preview_rollover(session, request)
        else:
            response = apply_rollover(session, request)
            session.commit()

    print(
        json.dumps(
            response.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
