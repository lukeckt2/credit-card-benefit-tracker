"""Benefit-period read and tracking endpoints."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.routers._errors import commit_or_conflict, http_not_found, http_validation_error
from app.schemas import (
    BenefitPeriodListResponse,
    BenefitPeriodRead,
    PeriodStatus,
    PeriodUpdate,
    UsageAdjustmentCreate,
    UsageEventCreate,
    UsageEventListResponse,
    UsageMutationResponse,
)
from app.services import read as read_service
from app.services import usage as usage_service
from app.services.errors import NotFoundError, ServiceValidationError


router = APIRouter(tags=["benefit-periods"])


@router.get("/benefit-periods", response_model=BenefitPeriodListResponse)
def benefit_periods(
    include_inactive_cards: bool = False,
    include_inactive_definitions: bool = False,
    status: Annotated[list[PeriodStatus] | None, Query()] = None,
    card_id: int | None = None,
    definition_id: int | None = None,
    deadline_start: date | None = None,
    deadline_end: date | None = None,
    session: Session = Depends(get_session),
) -> BenefitPeriodListResponse:
    return BenefitPeriodListResponse(
        benefit_periods=read_service.list_benefit_periods(
            session,
            include_inactive_cards=include_inactive_cards,
            include_inactive_definitions=include_inactive_definitions,
            statuses=list(status) if status else None,
            card_id=card_id,
            definition_id=definition_id,
            deadline_start=deadline_start,
            deadline_end=deadline_end,
        )
    )


@router.get("/benefit-periods/{period_id}", response_model=BenefitPeriodRead)
def benefit_period(
    period_id: int,
    session: Session = Depends(get_session),
) -> BenefitPeriodRead:
    try:
        return read_service.get_benefit_period(session, period_id)
    except NotFoundError as error:
        raise http_not_found(error) from error


@router.get(
    "/benefit-periods/{period_id}/usage-events",
    response_model=UsageEventListResponse,
)
def period_usage_events(
    period_id: int,
    session: Session = Depends(get_session),
) -> UsageEventListResponse:
    try:
        return UsageEventListResponse(
            usage_events=read_service.list_usage_events(session, period_id)
        )
    except NotFoundError as error:
        raise http_not_found(error) from error


@router.patch("/benefit-periods/{period_id}", response_model=BenefitPeriodRead)
def update_benefit_period(
    period_id: int,
    payload: PeriodUpdate,
    session: Session = Depends(get_session),
) -> BenefitPeriodRead:
    try:
        usage_service.patch_period(session, period_id, payload)
        commit_or_conflict(session)
        return read_service.get_benefit_period(session, period_id)
    except NotFoundError as error:
        session.rollback()
        raise http_not_found(error) from error
    except ServiceValidationError as error:
        session.rollback()
        raise http_validation_error(error) from error


@router.post("/benefit-periods/{period_id}/complete", response_model=BenefitPeriodRead)
def complete_benefit_period(
    period_id: int,
    session: Session = Depends(get_session),
) -> BenefitPeriodRead:
    try:
        usage_service.complete_period(session, period_id)
        commit_or_conflict(session)
        return read_service.get_benefit_period(session, period_id)
    except NotFoundError as error:
        session.rollback()
        raise http_not_found(error) from error
    except ServiceValidationError as error:
        session.rollback()
        raise http_validation_error(error) from error


@router.post("/benefit-periods/{period_id}/reopen", response_model=BenefitPeriodRead)
def reopen_benefit_period(
    period_id: int,
    session: Session = Depends(get_session),
) -> BenefitPeriodRead:
    try:
        usage_service.reopen_period(session, period_id)
        commit_or_conflict(session)
        return read_service.get_benefit_period(session, period_id)
    except NotFoundError as error:
        session.rollback()
        raise http_not_found(error) from error


@router.post(
    "/benefit-periods/{period_id}/usage-events",
    response_model=UsageMutationResponse,
)
def add_usage_event(
    period_id: int,
    payload: UsageEventCreate,
    session: Session = Depends(get_session),
) -> UsageMutationResponse:
    try:
        event = usage_service.create_usage_event(session, period_id, payload)
        commit_or_conflict(session)
        return UsageMutationResponse(
            usage_event=read_service.usage_event_to_read(event),
            period=read_service.get_benefit_period(session, period_id),
        )
    except NotFoundError as error:
        session.rollback()
        raise http_not_found(error) from error


@router.post(
    "/benefit-periods/{period_id}/usage-adjustment",
    response_model=UsageMutationResponse,
)
def set_current_used_amount(
    period_id: int,
    payload: UsageAdjustmentCreate,
    session: Session = Depends(get_session),
) -> UsageMutationResponse:
    try:
        event = usage_service.create_usage_adjustment(session, period_id, payload)
        commit_or_conflict(session)
        return UsageMutationResponse(
            usage_event=read_service.usage_event_to_read(event),
            period=read_service.get_benefit_period(session, period_id),
        )
    except NotFoundError as error:
        session.rollback()
        raise http_not_found(error) from error
