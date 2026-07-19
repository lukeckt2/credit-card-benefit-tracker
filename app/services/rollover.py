"""Idempotent benefit-period rollover generation."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BenefitDefinition, BenefitPeriod, CardMaster
from app.schemas import (
    RolloverPeriod,
    RolloverRequest,
    RolloverResponse,
    RolloverWarning,
    decimal_to_api,
)


@dataclass(frozen=True)
class PeriodCandidate:
    period_key: str
    period_start: date
    period_end: date
    deadline: date


def last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def annual_date(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, last_day_of_month(year, month)))


def periods_overlap(start: date, end: date, window_start: date, window_end: date) -> bool:
    return start <= window_end and end >= window_start


def _month_candidates(window_start: date, window_end: date) -> list[PeriodCandidate]:
    candidates: list[PeriodCandidate] = []
    year = window_start.year
    month = window_start.month
    while date(year, month, 1) <= window_end:
        period_start = date(year, month, 1)
        period_end = date(year, month, last_day_of_month(year, month))
        if periods_overlap(period_start, period_end, window_start, window_end):
            candidates.append(
                PeriodCandidate(
                    period_key=f"{year}-{month:02d}",
                    period_start=period_start,
                    period_end=period_end,
                    deadline=period_end,
                )
            )
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return candidates


def _quarter_candidates(window_start: date, window_end: date) -> list[PeriodCandidate]:
    candidates: list[PeriodCandidate] = []
    year = window_start.year
    quarter = ((window_start.month - 1) // 3) + 1
    while year < window_end.year or (
        year == window_end.year and (quarter - 1) * 3 + 1 <= window_end.month
    ):
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 2
        period_start = date(year, start_month, 1)
        period_end = date(year, end_month, last_day_of_month(year, end_month))
        if periods_overlap(period_start, period_end, window_start, window_end):
            candidates.append(
                PeriodCandidate(
                    period_key=f"{year}-Q{quarter}",
                    period_start=period_start,
                    period_end=period_end,
                    deadline=period_end,
                )
            )
        if quarter == 4:
            year += 1
            quarter = 1
        else:
            quarter += 1
    return candidates


def _semiannual_candidates(window_start: date, window_end: date) -> list[PeriodCandidate]:
    candidates: list[PeriodCandidate] = []
    year = window_start.year
    half = 1 if window_start.month <= 6 else 2
    while year < window_end.year or (year == window_end.year and half_start_month(half) <= window_end.month):
        if half == 1:
            period_start = date(year, 1, 1)
            period_end = date(year, 6, 30)
        else:
            period_start = date(year, 7, 1)
            period_end = date(year, 12, 31)
        if periods_overlap(period_start, period_end, window_start, window_end):
            candidates.append(
                PeriodCandidate(
                    period_key=f"{year}-H{half}",
                    period_start=period_start,
                    period_end=period_end,
                    deadline=period_end,
                )
            )
        if half == 2:
            year += 1
            half = 1
        else:
            half = 2
    return candidates


def half_start_month(half: int) -> int:
    return 1 if half == 1 else 7


def _annual_candidates(window_start: date, window_end: date) -> list[PeriodCandidate]:
    candidates: list[PeriodCandidate] = []
    for year in range(window_start.year, window_end.year + 1):
        period_start = date(year, 1, 1)
        period_end = date(year, 12, 31)
        if periods_overlap(period_start, period_end, window_start, window_end):
            candidates.append(
                PeriodCandidate(
                    period_key=f"{year}",
                    period_start=period_start,
                    period_end=period_end,
                    deadline=period_end,
                )
            )
    return candidates


def _anniversary_candidates(
    window_start: date, window_end: date, open_month: int, open_day: int
) -> list[PeriodCandidate]:
    candidates: list[PeriodCandidate] = []
    for year in range(window_start.year - 1, window_end.year + 1):
        period_start = annual_date(year, open_month, open_day)
        period_end = annual_date(year + 1, open_month, open_day)
        if periods_overlap(period_start, period_end, window_start, window_end):
            candidates.append(
                PeriodCandidate(
                    period_key=f"{period_start.isoformat()}~{period_end.isoformat()}",
                    period_start=period_start,
                    period_end=period_end,
                    deadline=period_end,
                )
            )
    return candidates


def generate_candidate_periods(
    cycle_type: str,
    window_start: date,
    window_end: date,
    *,
    open_month: int | None = None,
    open_day: int | None = None,
) -> list[PeriodCandidate]:
    if cycle_type == "monthly":
        return _month_candidates(window_start, window_end)
    if cycle_type == "quarterly":
        return _quarter_candidates(window_start, window_end)
    if cycle_type == "semiannual":
        return _semiannual_candidates(window_start, window_end)
    if cycle_type == "annual":
        return _annual_candidates(window_start, window_end)
    if cycle_type in {"membership_year", "anniversary"}:
        if open_month is None or open_day is None:
            return []
        return _anniversary_candidates(window_start, window_end, open_month, open_day)
    return []


def _definition_rows(session: Session, request: RolloverRequest):
    statement = select(BenefitDefinition, CardMaster).join(CardMaster)
    if request.definition_ids:
        statement = statement.where(
            BenefitDefinition.benefit_definition_id.in_(request.definition_ids)
        )
    if not request.include_inactive_cards:
        statement = statement.where(CardMaster.status == "active")
    if not request.include_inactive_definitions:
        statement = statement.where(BenefitDefinition.active.is_(True))
    return session.execute(
        statement.order_by(CardMaster.display_name, BenefitDefinition.name)
    ).all()


def build_rollover_response(
    session: Session, request: RolloverRequest, *, dry_run: bool
) -> RolloverResponse:
    periods: list[RolloverPeriod] = []
    warnings: list[RolloverWarning] = []
    skipped = 0
    not_due = 0

    for definition, card in _definition_rows(session, request):
        if definition.default_period_rule or definition.default_deadline_rule:
            skipped += 1
            warnings.append(
                RolloverWarning(
                    type="unsupported_custom_rule",
                    message="Custom period/deadline rules need an approved structured format before automation can use them.",
                    benefit_definition_id=definition.benefit_definition_id,
                    card_id=card.card_id,
                )
            )
            continue

        if definition.cycle_type in {"membership_year", "anniversary"} and (
            card.open_month is None or card.open_day is None
        ):
            skipped += 1
            warnings.append(
                RolloverWarning(
                    type="missing_open_month_day",
                    message="Membership-year and anniversary rollover requires card open month/day.",
                    benefit_definition_id=definition.benefit_definition_id,
                    card_id=card.card_id,
                )
            )
            continue

        if definition.cycle_type in {"cert", "multi_year"}:
            skipped += 1
            warnings.append(
                RolloverWarning(
                    type="fixed_period_not_generated",
                    message="Certificate and multi-year benefits require explicit fixed periods or approved recurrence rules.",
                    benefit_definition_id=definition.benefit_definition_id,
                    card_id=card.card_id,
                )
            )
            continue

        candidates = generate_candidate_periods(
            definition.cycle_type,
            request.window_start,
            request.window_end,
            open_month=card.open_month,
            open_day=card.open_day,
        )
        if request.only_periods_starting_in_window:
            candidates = [
                candidate
                for candidate in candidates
                if request.window_start <= candidate.period_start <= request.window_end
            ]

        if not candidates:
            if request.only_periods_starting_in_window:
                not_due += 1
                continue

            skipped += 1
            warnings.append(
                RolloverWarning(
                    type="no_periods_generated",
                    message="No periods were generated for this benefit in the requested window.",
                    benefit_definition_id=definition.benefit_definition_id,
                    card_id=card.card_id,
                )
            )
            continue

        existing_keys = set(
            session.scalars(
                select(BenefitPeriod.period_key).where(
                    BenefitPeriod.benefit_definition_id
                    == definition.benefit_definition_id,
                    BenefitPeriod.period_key.in_(
                        [candidate.period_key for candidate in candidates]
                    ),
                )
            )
        )
        for candidate in candidates:
            action = "exists" if candidate.period_key in existing_keys else "create"
            periods.append(
                RolloverPeriod(
                    action=action,
                    benefit_definition_id=definition.benefit_definition_id,
                    card_id=card.card_id,
                    card_name=card.display_name,
                    benefit_name=definition.name,
                    cycle_type=definition.cycle_type,
                    period_key=candidate.period_key,
                    period_start=candidate.period_start,
                    period_end=candidate.period_end,
                    deadline=candidate.deadline,
                    amount_total=decimal_to_api(definition.default_amount_total) or 0.0,
                )
            )

    would_create = sum(1 for period in periods if period.action == "create")
    existing = sum(1 for period in periods if period.action == "exists")
    return RolloverResponse(
        dry_run=dry_run,
        window_start=request.window_start,
        window_end=request.window_end,
        would_create=would_create,
        created=0,
        existing=existing,
        skipped=skipped,
        not_due=not_due,
        warnings=warnings,
        periods=periods,
    )


def preview_rollover(session: Session, request: RolloverRequest) -> RolloverResponse:
    return build_rollover_response(session, request, dry_run=True)


def apply_rollover(session: Session, request: RolloverRequest) -> RolloverResponse:
    response = build_rollover_response(session, request, dry_run=False)
    created = 0
    for period in response.periods:
        if period.action != "create":
            continue
        session.add(
            BenefitPeriod(
                benefit_definition_id=period.benefit_definition_id,
                period_key=period.period_key,
                period_start=period.period_start,
                period_end=period.period_end,
                deadline=period.deadline,
                amount_total=Decimal(str(period.amount_total)),
                status="pending",
            )
        )
        created += 1
    session.flush()
    return response.model_copy(update={"created": created})
