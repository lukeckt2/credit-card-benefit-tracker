"""Benefit-definition read endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.routers._errors import commit_or_conflict, http_not_found
from app.schemas import BenefitDefinitionListResponse, BenefitDefinitionRead
from app.services import deletion as deletion_service
from app.services import read as read_service
from app.services.errors import NotFoundError


router = APIRouter(tags=["benefit-definitions"])


@router.get("/benefit-definitions", response_model=BenefitDefinitionListResponse)
def benefit_definitions(
    include_inactive_cards: bool = False,
    include_inactive_definitions: bool = False,
    card_id: int | None = None,
    session: Session = Depends(get_session),
) -> BenefitDefinitionListResponse:
    return BenefitDefinitionListResponse(
        benefit_definitions=read_service.list_benefit_definitions(
            session,
            include_inactive_cards=include_inactive_cards,
            include_inactive_definitions=include_inactive_definitions,
            card_id=card_id,
        )
    )


@router.get("/benefit-definitions/{definition_id}", response_model=BenefitDefinitionRead)
def benefit_definition(
    definition_id: int,
    session: Session = Depends(get_session),
) -> BenefitDefinitionRead:
    try:
        return read_service.get_benefit_definition(session, definition_id)
    except NotFoundError as error:
        raise http_not_found(error) from error


@router.delete("/benefit-definitions/{benefit_definition_id}", status_code=204)
def remove_benefit_definition(
    benefit_definition_id: int,
    session: Session = Depends(get_session),
) -> Response:
    try:
        deletion_service.delete_benefit_definition(session, benefit_definition_id)
        commit_or_conflict(session)
        return Response(status_code=204)
    except NotFoundError as error:
        session.rollback()
        raise http_not_found(error) from error
