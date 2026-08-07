"""Frontend-ready dashboard section builder."""

from __future__ import annotations

from datetime import date
from typing import Callable

from sqlalchemy.orm import Session

from app.schemas import (
    CycleType,
    DashboardCategoryGroup,
    DashboardResponse,
    DashboardRow,
    DashboardSection,
    PeriodStatus,
)
from app.services import read as read_service


SectionPredicate = Callable[[DashboardRow], bool]
SectionSortKey = Callable[[DashboardRow], tuple]

CATEGORY_ORDER = ("dining", "travel", "others")


def _by_deadline(row: DashboardRow) -> tuple:
    return (row.deadline, row.card_name, row.benefit_name)


SECTION_DEFINITIONS: tuple[tuple[str, str, SectionPredicate, SectionSortKey, bool], ...] = (
    (
        "active_current",
        "ACTIVE (Current)",
        lambda row: row.status == "pending" and row.amount_remaining > 0,
        _by_deadline,
        True,   # use_category_groups
    ),
    (
        "due_within_45_days",
        "45-Day Due",
        lambda row: row.status == "pending"
        and row.amount_remaining > 0
        and 0 <= row.days_until_deadline <= 45,
        _by_deadline,
        False,
    ),
)


def build_dashboard(
    session: Session,
    *,
    user_id: int,
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
        user_id=user_id,
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

    sections = []
    for key, title, predicate, sort_key, use_category_groups in SECTION_DEFINITIONS:
        section_rows = sorted((row for row in rows if predicate(row)), key=sort_key)
        category_groups = None
        if use_category_groups:
            grouped: dict[str | None, list[DashboardRow]] = {}
            for row in section_rows:
                grouped.setdefault(row.category, []).append(row)
            # Order: dining -> travel -> others -> None (uncategorised)
            ordered_keys = [k for k in CATEGORY_ORDER if k in grouped]
            if None in grouped:
                ordered_keys.append(None)
            category_groups = [
                DashboardCategoryGroup(category=k, rows=grouped[k])
                for k in ordered_keys
            ]
        sections.append(
            DashboardSection(
                key=key,
                title=title,
                rows=section_rows,
                category_groups=category_groups,
            )
        )
    return DashboardResponse(as_of=as_of, sections=sections)
