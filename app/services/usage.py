"""Usage-event and benefit-period mutation workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import BenefitPeriod, UsageEvent
from app.schemas import PeriodUpdate, QuickCompleteCreate, UsageAdjustmentCreate, UsageEventCreate
from app.services.errors import NotFoundError, ServiceValidationError
from app.services.read import usage_total_for_period


from app.services.read import _period_join_statement, usage_total_for_period


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_period_for_update(session: Session, period_id: int, *, user_id: int) -> BenefitPeriod:
    statement = _period_join_statement(user_id=user_id).where(BenefitPeriod.benefit_period_id == period_id)
    row = session.execute(statement).first()
    if row is None:
        raise NotFoundError(f"Benefit period {period_id} was not found.")
    return row[0]


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


def patch_period(session: Session, period_id: int, payload: PeriodUpdate, *, user_id: int) -> BenefitPeriod:
    period = get_period_for_update(session, period_id, user_id=user_id)
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


def complete_period(session: Session, period_id: int, *, user_id: int) -> BenefitPeriod:
    period = get_period_for_update(session, period_id, user_id=user_id)
    require_no_remaining_amount(session, period)
    period.status = "completed"
    if period.completed_at is None:
        period.completed_at = utc_now()
    session.flush()
    return period


def reopen_period(session: Session, period_id: int, *, user_id: int) -> BenefitPeriod:
    period = get_period_for_update(session, period_id, user_id=user_id)
    period.status = "pending"
    period.completed_at = None
    session.flush()
    return period


def create_usage_event(
    session: Session, period_id: int, payload: UsageEventCreate, *, user_id: int
) -> UsageEvent:
    period = get_period_for_update(session, period_id, user_id=user_id)
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
    session: Session, period_id: int, payload: UsageAdjustmentCreate, *, user_id: int
) -> UsageEvent:
    period = get_period_for_update(session, period_id, user_id=user_id)
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


from sqlalchemy import select as sa_select


def _pre_completion_amount(session: Session, period: BenefitPeriod) -> Decimal:
    """Return the used total just before the most recent auto-complete event.

    Subtracts the most recent quick-complete event delta from
    the current running total. Returns Decimal("0") as a fallback or if restoring
    would result in a fully completed state.
    """
    recent_event = session.scalar(
        sa_select(UsageEvent)
        .where(
            UsageEvent.benefit_period_id == period.benefit_period_id,
            UsageEvent.event_type == "quick_complete",
        )
        .order_by(UsageEvent.used_at.desc(), UsageEvent.usage_event_id.desc())
        .limit(1)
    )
    if recent_event is None:
        return Decimal("0")

    current_total = usage_total_for_period(session, period.benefit_period_id)
    target = current_total - recent_event.amount_delta
    
    if target >= period.amount_total:
        return Decimal("0")

    return target


def quick_complete_period(
    session: Session, period_id: int, payload: QuickCompleteCreate, *, user_id: int
) -> UsageEvent:
    period = get_period_for_update(session, period_id, user_id=user_id)
    current_used = usage_total_for_period(session, period_id)
    
    if payload.completed and period.amount_total is None:
        raise ServiceValidationError("Cannot quick-complete a benefit without a total amount.")

    if payload.completed:
        target_used = Decimal(period.amount_total)
    else:
        target_used = _pre_completion_amount(session, period)
        
    delta = target_used - current_used
    if delta == 0:
        raise ServiceValidationError("No change needed.")

    event = UsageEvent(
        benefit_period_id=period_id,
        event_type="quick_complete" if payload.completed else "adjustment",
        amount_delta=delta,
        note=payload.note or (
            "Auto-completed via checkbox"
            if payload.completed
            else "Restored prior amount via checkbox"
        ),
        source_key=None,
        used_at=utc_now(),
    )
    session.add(event)
    session.flush()
    sync_completion_from_usage_total(session, period)
    session.flush()
    return event
