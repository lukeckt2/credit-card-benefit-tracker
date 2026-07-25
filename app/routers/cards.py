"""Card read endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.routers._errors import commit_or_conflict, http_not_found
from app.schemas import CardDetail, CardListResponse
from app.services import deletion as deletion_service
from app.services import read as read_service
from app.auth import get_current_user
from app.models import User
from app.services.errors import NotFoundError


router = APIRouter(tags=["cards"])


@router.get("/cards", response_model=CardListResponse)
def cards(
    include_inactive: bool = False,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CardListResponse:
    return CardListResponse(
        cards=read_service.list_cards(session, user_id=current_user.user_id, include_inactive=include_inactive)
    )


@router.get("/cards/{card_id}", response_model=CardDetail)
def card_detail(
    card_id: int,
    include_inactive_definitions: bool = False,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CardDetail:
    try:
        return read_service.get_card_detail(
            session,
            card_id,
            user_id=current_user.user_id,
            include_inactive_definitions=include_inactive_definitions,
        )
    except NotFoundError as error:
        raise http_not_found(error) from error


@router.delete("/cards/{card_id}", status_code=204)
def remove_card(
    card_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    try:
        deletion_service.delete_card(session, card_id, user_id=current_user.user_id)
        commit_or_conflict(session)
        return Response(status_code=204)
    except NotFoundError as error:
        session.rollback()
        raise http_not_found(error) from error
