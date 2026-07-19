"""Frontend-ready dashboard section builder."""

from __future__ import annotations

from datetime import date
from typing import Callable

from sqlalchemy.orm import Session

from app.schemas import CycleType, DashboardResponse, DashboardRow, DashboardSection, PeriodStatus
from app.services import read as read_service


SectionPredicate = Callable[[DashboardRow], bool]
SectionSortKey = Callable[[DashboardRow], tuple]


def _by_deadline(row: DashboardRow) -> tuple:
    return (row.deadline, row.card_name, row.benefit_name)


SECTION_DEFINITIONS: tuple[tuple[str, str, SectionPredicate, SectionSortKey], ...] = (
    (
        "active_current",
        "ACTIVE (Current)",
        lambda row: row.status == "pending" and row.amount_remaining > 0,
        _by_deadline,
    ),
    (
        "due_within_45_days",
        "45-Day Due",
        lambda row: row.status == "pending"
        and row.amount_remaining > 0
        and 0 <= row.days_until_deadline <= 45,
        _by_deadline,
    ),
)


def build_dashboard(
    session: Session,
    *,
    as_of: date,
    include_inactive_cards: bool,
    include_inactive_definitions: bool,
    statuses: list[PeriodStatus] | None,
    card_id: int | None,
    issuer: str | None,
    cycle_types: list[CycleType] | None,
    deadline_start: date | None,
    deadline_end: date | None,
) -> DashboardResponse:
    rows = read_service.list_dashboard_rows(
        session,
        as_of=as_of,
        include_inactive_cards=include_inactive_cards,
        include_inactive_definitions=include_inactive_definitions,
        statuses=list(statuses) if statuses else None,
        card_id=card_id,
        issuer=issuer,
        cycle_types=list(cycle_types) if cycle_types else None,
        deadline_start=deadline_start,
        deadline_end=deadline_end,
        current_only=True,
    )

    sections = [
        DashboardSection(
            key=key,
            title=title,
            rows=sorted((row for row in rows if predicate(row)), key=sort_key),
        )
        for key, title, predicate, sort_key in SECTION_DEFINITIONS
    ]
    return DashboardResponse(as_of=as_of, sections=sections)
