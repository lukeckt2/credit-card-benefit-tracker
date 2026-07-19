"""Usage-event and benefit-period mutation workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import BenefitPeriod, UsageEvent
from app.schemas import PeriodUpdate, UsageAdjustmentCreate, UsageEventCreate
from app.services.errors import NotFoundError, ServiceValidationError
from app.services.read import usage_total_for_period


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_period_for_update(session: Session, period_id: int) -> BenefitPeriod:
    period = session.get(BenefitPeriod, period_id)
    if period is None:
        raise NotFoundError(f"Benefit period {period_id} was not found.")
    return period


def remaining_amount_for_period(session: Session, period: BenefitPeriod) -> Decimal:
    return Decimal(period.amount_total) - usage_total_for_period(
        session, period.benefit_period_id
    )


def require_no_remaining_amount(session: Session, period: BenefitPeriod) -> None:
    amount_remaining = remaining_amount_for_period(session, period)
    if amount_remaining > 0:
        raise ServiceValidationError(
            f"Cannot complete benefit period with {amount_remaining} remaining."
        )


def sync_completion_from_usage_total(session: Session, period: BenefitPeriod) -> None:
    amount_remaining = remaining_amount_for_period(session, period)
    if amount_remaining <= 0 and period.status == "pending":
        period.status = "completed"
        if period.completed_at is None:
            period.completed_at = utc_now()
    elif amount_remaining > 0 and period.status == "completed":
        period.status = "pending"
        period.completed_at = None


def patch_period(session: Session, period_id: int, payload: PeriodUpdate) -> BenefitPeriod:
    period = get_period_for_update(session, period_id)
    period_start = payload.period_start or period.period_start
    period_end = payload.period_end or period.period_end
    if period_start > period_end:
        raise ServiceValidationError("period_start must be on or before period_end.")

    if payload.period_start is not None:
        period.period_start = payload.period_start
    if payload.period_end is not None:
        period.period_end = payload.period_end
    if payload.deadline is not None:
        period.deadline = payload.deadline
    if payload.amount_total is not None:
        period.amount_total = payload.amount_total
    if payload.status is not None:
        if payload.status == "completed":
            require_no_remaining_amount(session, period)
        period.status = payload.status
        period.completed_at = utc_now() if payload.status == "completed" else None

    session.flush()
    return period


def complete_period(session: Session, period_id: int) -> BenefitPeriod:
    period = get_period_for_update(session, period_id)
    require_no_remaining_amount(session, period)
    period.status = "completed"
    if period.completed_at is None:
        period.completed_at = utc_now()
    session.flush()
    return period


def reopen_period(session: Session, period_id: int) -> BenefitPeriod:
    period = get_period_for_update(session, period_id)
    period.status = "pending"
    period.completed_at = None
    session.flush()
    return period


def create_usage_event(
    session: Session, period_id: int, payload: UsageEventCreate
) -> UsageEvent:
    period = get_period_for_update(session, period_id)
    event = UsageEvent(
        benefit_period_id=period_id,
        event_type="usage",
        amount_delta=payload.amount_delta,
        note=payload.note,
        used_at=payload.used_at or utc_now(),
        source_key=payload.source_key,
    )
    session.add(event)
    session.flush()
    sync_completion_from_usage_total(session, period)
    session.flush()
    return event


def create_usage_adjustment(
    session: Session, period_id: int, payload: UsageAdjustmentCreate
) -> UsageEvent:
    period = get_period_for_update(session, period_id)
    current_used = usage_total_for_period(session, period_id)
    target_used = Decimal(payload.current_used_amount)
    delta = target_used - current_used
    event = UsageEvent(
        benefit_period_id=period_id,
        event_type=payload.event_type,
        amount_delta=delta,
        note=payload.note,
        used_at=payload.used_at or utc_now(),
        source_key=payload.source_key,
    )
    session.add(event)
    session.flush()
    sync_completion_from_usage_total(session, period)
    session.flush()
    return event
