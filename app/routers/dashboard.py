"""Dashboard read endpoints."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.data_wrapper import dashboard as dashboard_wrapper
from app.db import get_session
from app.schemas import CycleType, DashboardResponse, PeriodStatus


router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    as_of: date | None = None,
    include_inactive_cards: bool = False,
    include_inactive_definitions: bool = False,
    status: Annotated[list[PeriodStatus] | None, Query()] = None,
    card_id: int | None = None,
    issuer: str | None = None,
    cycle_type: Annotated[list[CycleType] | None, Query()] = None,
    deadline_start: date | None = None,
    deadline_end: date | None = None,
    session: Session = Depends(get_session),
) -> DashboardResponse:
    return dashboard_wrapper.build_dashboard(
        session,
        as_of=as_of or date.today(),
        include_inactive_cards=include_inactive_cards,
        include_inactive_definitions=include_inactive_definitions,
        statuses=list(status) if status else None,
        card_id=card_id,
        issuer=issuer,
        cycle_types=list(cycle_type) if cycle_type else None,
        deadline_start=deadline_start,
        deadline_end=deadline_end,
    )
