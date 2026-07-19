"""Read-side query helpers for dashboard and entity endpoints."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import BenefitDefinition, BenefitPeriod, CardMaster, UsageEvent
from app.schemas import (
    BenefitDefinitionRead,
    BenefitDefinitionSummary,
    BenefitDefinitionWithPeriods,
    BenefitPeriodRead,
    BenefitPeriodSummary,
    CardDetail,
    CardRead,
    DashboardRow,
    UsageEventRead,
    decimal_to_api,
)
from app.services.errors import NotFoundError


ZERO = Decimal("0")


def to_decimal(value: Decimal | int | float | str | None) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def usage_totals_for_periods(session: Session, period_ids: Iterable[int]) -> dict[int, Decimal]:
    ids = list(period_ids)
    if not ids:
        return {}

    rows = session.execute(
        select(
            UsageEvent.benefit_period_id,
            func.coalesce(func.sum(UsageEvent.amount_delta), 0),
        )
        .where(UsageEvent.benefit_period_id.in_(ids))
        .group_by(UsageEvent.benefit_period_id)
    )
    totals = {period_id: to_decimal(total) for period_id, total in rows}
    for period_id in ids:
        totals.setdefault(period_id, ZERO)
    return totals


def usage_total_for_period(session: Session, period_id: int) -> Decimal:
    total = session.scalar(
        select(func.coalesce(func.sum(UsageEvent.amount_delta), 0)).where(
            UsageEvent.benefit_period_id == period_id
        )
    )
    return to_decimal(total)


def card_to_read(card: CardMaster) -> CardRead:
    return CardRead(
        card_id=card.card_id,
        slug=card.slug,
        display_name=card.display_name,
        card_name=card.card_name,
        issuer=card.issuer,
        annual_fee=decimal_to_api(card.annual_fee),
        status=card.status,
        open_date=card.open_date,
        open_month=card.open_month,
        open_day=card.open_day,
        source_url=card.source_url,
        notes=card.notes,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


def definition_to_summary(definition: BenefitDefinition) -> BenefitDefinitionSummary:
    return BenefitDefinitionSummary(
        benefit_definition_id=definition.benefit_definition_id,
        card_id=definition.card_id,
        name=definition.name,
        normalized_name=definition.normalized_name,
        cycle_type=definition.cycle_type,
        unit=definition.unit,
        default_amount_total=decimal_to_api(definition.default_amount_total) or 0.0,
        active=definition.active,
    )


def definition_to_read(
    definition: BenefitDefinition, card: CardMaster | None = None
) -> BenefitDefinitionRead:
    return BenefitDefinitionRead(
        **definition_to_summary(definition).model_dump(),
        default_deadline_rule=definition.default_deadline_rule,
        default_period_rule=definition.default_period_rule,
        notes=definition.notes,
        created_at=definition.created_at,
        updated_at=definition.updated_at,
        card=card_to_read(card) if card else None,
    )


def period_to_summary(period: BenefitPeriod, amount_used: Decimal) -> BenefitPeriodSummary:
    amount_total = to_decimal(period.amount_total)
    return BenefitPeriodSummary(
        benefit_period_id=period.benefit_period_id,
        benefit_definition_id=period.benefit_definition_id,
        period_key=period.period_key,
        period_start=period.period_start,
        period_end=period.period_end,
        deadline=period.deadline,
        amount_total=decimal_to_api(amount_total) or 0.0,
        status=period.status,
        completed_at=period.completed_at,
        amount_used=decimal_to_api(amount_used) or 0.0,
        amount_remaining=decimal_to_api(amount_total - amount_used) or 0.0,
    )


def period_to_read(
    period: BenefitPeriod,
    amount_used: Decimal,
    definition: BenefitDefinition | None = None,
    card: CardMaster | None = None,
) -> BenefitPeriodRead:
    return BenefitPeriodRead(
        **period_to_summary(period, amount_used).model_dump(),
        created_at=period.created_at,
        updated_at=period.updated_at,
        card=card_to_read(card) if card else None,
        benefit_definition=definition_to_summary(definition) if definition else None,
    )


def usage_event_to_read(event: UsageEvent) -> UsageEventRead:
    return UsageEventRead(
        usage_event_id=event.usage_event_id,
        benefit_period_id=event.benefit_period_id,
        event_type=event.event_type,
        amount_delta=decimal_to_api(event.amount_delta) or 0.0,
        note=event.note,
        used_at=event.used_at,
        source_key=event.source_key,
        created_at=event.created_at,
    )


def _usage_totals_subquery():
    return (
        select(
            UsageEvent.benefit_period_id.label("benefit_period_id"),
            func.coalesce(func.sum(UsageEvent.amount_delta), 0).label("amount_used"),
        )
        .group_by(UsageEvent.benefit_period_id)
        .subquery()
    )


def _period_join_statement():
    usage_totals = _usage_totals_subquery()
    return (
        select(BenefitPeriod, BenefitDefinition, CardMaster, usage_totals.c.amount_used)
        .join(
            BenefitDefinition,
            BenefitPeriod.benefit_definition_id
            == BenefitDefinition.benefit_definition_id,
        )
        .join(CardMaster, BenefitDefinition.card_id == CardMaster.card_id)
        .outerjoin(
            usage_totals,
            usage_totals.c.benefit_period_id == BenefitPeriod.benefit_period_id,
        )
    )


def _apply_common_period_filters(
    statement: Select[tuple[BenefitPeriod, BenefitDefinition, CardMaster, Decimal]],
    *,
    include_inactive_cards: bool,
    include_inactive_definitions: bool,
    statuses: list[str] | None = None,
    card_id: int | None = None,
    definition_id: int | None = None,
    issuer: str | None = None,
    cycle_types: list[str] | None = None,
    deadline_start: date | None = None,
    deadline_end: date | None = None,
    current_as_of: date | None = None,
) -> Select[tuple[BenefitPeriod, BenefitDefinition, CardMaster, Decimal]]:
    if not include_inactive_cards:
        statement = statement.where(CardMaster.status == "active")
    if not include_inactive_definitions:
        statement = statement.where(BenefitDefinition.active.is_(True))
    if statuses:
        statement = statement.where(BenefitPeriod.status.in_(statuses))
    if card_id is not None:
        statement = statement.where(CardMaster.card_id == card_id)
    if definition_id is not None:
        statement = statement.where(
            BenefitPeriod.benefit_definition_id == definition_id
        )
    if issuer is not None:
        statement = statement.where(CardMaster.issuer == issuer)
    if cycle_types:
        statement = statement.where(BenefitDefinition.cycle_type.in_(cycle_types))
    if deadline_start is not None:
        statement = statement.where(BenefitPeriod.deadline >= deadline_start)
    if deadline_end is not None:
        statement = statement.where(BenefitPeriod.deadline <= deadline_end)
    if current_as_of is not None:
        statement = statement.where(
            BenefitPeriod.period_start <= current_as_of,
            BenefitPeriod.period_end >= current_as_of,
        )
    return statement


def priority_for_period(period: BenefitPeriod, as_of: date) -> str:
    if period.status == "completed":
        return "completed"
    if period.status == "skipped":
        return "skipped"
    days_until_deadline = (period.deadline - as_of).days
    if days_until_deadline < 0:
        return "overdue"
    if days_until_deadline <= 14:
        return "due_soon"
    if days_until_deadline <= 45:
        return "upcoming"
    return "later"


def list_dashboard_rows(
    session: Session,
    *,
    as_of: date,
    include_inactive_cards: bool,
    include_inactive_definitions: bool,
    statuses: list[str] | None,
    card_id: int | None = None,
    issuer: str | None = None,
    cycle_types: list[str] | None = None,
    deadline_start: date | None = None,
    deadline_end: date | None = None,
    current_only: bool = False,
) -> list[DashboardRow]:
    statement = _apply_common_period_filters(
        _period_join_statement(),
        include_inactive_cards=include_inactive_cards,
        include_inactive_definitions=include_inactive_definitions,
        statuses=statuses,
        card_id=card_id,
        issuer=issuer,
        cycle_types=cycle_types,
        deadline_start=deadline_start,
        deadline_end=deadline_end,
        current_as_of=as_of if current_only else None,
    ).order_by(BenefitPeriod.deadline, CardMaster.display_name, BenefitDefinition.name)

    rows: list[DashboardRow] = []
    for period, definition, card, amount_used_raw in session.execute(statement):
        amount_used = to_decimal(amount_used_raw)
        amount_total = to_decimal(period.amount_total)
        rows.append(
            DashboardRow(
                period_id=period.benefit_period_id,
                benefit_definition_id=definition.benefit_definition_id,
                card_id=card.card_id,
                card_name=card.card_name,
                issuer=card.issuer,
                benefit_name=definition.name,
                cycle_type=definition.cycle_type,
                unit=definition.unit,
                period_key=period.period_key,
                period_start=period.period_start,
                period_end=period.period_end,
                amount_total=decimal_to_api(amount_total) or 0.0,
                amount_used=decimal_to_api(amount_used) or 0.0,
                amount_remaining=decimal_to_api(amount_total - amount_used) or 0.0,
                deadline=period.deadline,
                days_until_deadline=(period.deadline - as_of).days,
                status=period.status,
                completed_at=period.completed_at,
                priority=priority_for_period(period, as_of),
                is_current=period.period_start <= as_of <= period.period_end,
                is_pending=period.status == "pending",
                is_completed=period.status == "completed",
            )
        )
    return rows


def list_cards(session: Session, *, include_inactive: bool) -> list[CardRead]:
    statement = select(CardMaster).order_by(CardMaster.display_name)
    if not include_inactive:
        statement = statement.where(CardMaster.status == "active")
    return [card_to_read(card) for card in session.scalars(statement)]


def get_card_detail(
    session: Session,
    card_id: int,
    *,
    include_inactive_definitions: bool,
) -> CardDetail:
    card = session.get(CardMaster, card_id)
    if card is None:
        raise NotFoundError(f"Card {card_id} was not found.")

    definitions_statement = select(BenefitDefinition).where(
        BenefitDefinition.card_id == card_id
    )
    if not include_inactive_definitions:
        definitions_statement = definitions_statement.where(BenefitDefinition.active.is_(True))
    definitions = list(
        session.scalars(
            definitions_statement.order_by(BenefitDefinition.active.desc(), BenefitDefinition.name)
        )
    )
    definition_ids = [definition.benefit_definition_id for definition in definitions]

    periods_by_definition: dict[int, list[BenefitPeriodSummary]] = {
        definition_id: [] for definition_id in definition_ids
    }
    if definition_ids:
        periods = list(
            session.scalars(
                select(BenefitPeriod)
                .where(BenefitPeriod.benefit_definition_id.in_(definition_ids))
                .order_by(BenefitPeriod.deadline, BenefitPeriod.period_key)
            )
        )
        totals = usage_totals_for_periods(
            session, [period.benefit_period_id for period in periods]
        )
        for period in periods:
            periods_by_definition[period.benefit_definition_id].append(
                period_to_summary(period, totals[period.benefit_period_id])
            )

    return CardDetail(
        **card_to_read(card).model_dump(),
        benefit_definitions=[
            BenefitDefinitionWithPeriods(
                **definition_to_read(definition).model_dump(),
                periods=periods_by_definition[definition.benefit_definition_id],
            )
            for definition in definitions
        ],
    )


def list_benefit_definitions(
    session: Session,
    *,
    include_inactive_cards: bool,
    include_inactive_definitions: bool,
    card_id: int | None,
) -> list[BenefitDefinitionRead]:
    statement = select(BenefitDefinition, CardMaster).join(CardMaster)
    if not include_inactive_cards:
        statement = statement.where(CardMaster.status == "active")
    if not include_inactive_definitions:
        statement = statement.where(BenefitDefinition.active.is_(True))
    if card_id is not None:
        statement = statement.where(BenefitDefinition.card_id == card_id)
    statement = statement.order_by(CardMaster.display_name, BenefitDefinition.name)
    return [
        definition_to_read(definition, card)
        for definition, card in session.execute(statement)
    ]


def get_benefit_definition(
    session: Session, definition_id: int
) -> BenefitDefinitionRead:
    row = session.execute(
        select(BenefitDefinition, CardMaster)
        .join(CardMaster)
        .where(BenefitDefinition.benefit_definition_id == definition_id)
    ).one_or_none()
    if row is None:
        raise NotFoundError(f"Benefit definition {definition_id} was not found.")
    definition, card = row
    return definition_to_read(definition, card)


def list_benefit_periods(
    session: Session,
    *,
    include_inactive_cards: bool,
    include_inactive_definitions: bool,
    statuses: list[str] | None,
    card_id: int | None,
    definition_id: int | None,
    deadline_start: date | None,
    deadline_end: date | None,
) -> list[BenefitPeriodRead]:
    statement = _apply_common_period_filters(
        _period_join_statement(),
        include_inactive_cards=include_inactive_cards,
        include_inactive_definitions=include_inactive_definitions,
        statuses=statuses,
        card_id=card_id,
        definition_id=definition_id,
            deadline_start=deadline_start,
            deadline_end=deadline_end,
    ).order_by(BenefitPeriod.deadline, CardMaster.display_name, BenefitDefinition.name)

    return [
        period_to_read(period, to_decimal(amount_used), definition, card)
        for period, definition, card, amount_used in session.execute(statement)
    ]


def get_benefit_period(session: Session, period_id: int) -> BenefitPeriodRead:
    statement = _period_join_statement().where(
        BenefitPeriod.benefit_period_id == period_id
    )
    row = session.execute(statement).one_or_none()
    if row is None:
        raise NotFoundError(f"Benefit period {period_id} was not found.")
    period, definition, card, amount_used = row
    return period_to_read(period, to_decimal(amount_used), definition, card)


def list_usage_events(session: Session, period_id: int) -> list[UsageEventRead]:
    if session.get(BenefitPeriod, period_id) is None:
        raise NotFoundError(f"Benefit period {period_id} was not found.")
    events = session.scalars(
        select(UsageEvent)
        .where(UsageEvent.benefit_period_id == period_id)
        .order_by(UsageEvent.used_at.desc(), UsageEvent.usage_event_id.desc())
    )
    return [usage_event_to_read(event) for event in events]
