"""Catalog endpoints — browse and add cards from the global catalog."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_session
from app.models import User
from app.routers._errors import commit_or_conflict
from app.schemas import (
    CatalogAddRequest,
    CatalogAddResponse,
    CatalogCardListResponse,
    CatalogIssuerListResponse,
    CardSourceConfigDetail,
    CardSourceConfigRead,
)
from app.services import catalog as catalog_service


router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/issuers", response_model=CatalogIssuerListResponse)
def list_issuers(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CatalogIssuerListResponse:
    return CatalogIssuerListResponse(
        issuers=catalog_service.list_issuers(session)
    )


@router.get("/cards", response_model=CatalogCardListResponse)
def list_cards(
    issuer: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CatalogCardListResponse:
    cards = catalog_service.list_cards_by_issuer(session, issuer)
    return CatalogCardListResponse(
        cards=[CardSourceConfigRead.model_validate(c, from_attributes=True) for c in cards]
    )


@router.get("/cards/{source_id}", response_model=CardSourceConfigDetail)
def card_detail(
    source_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CardSourceConfigDetail:
    card = catalog_service.get_card_detail(session, source_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Catalog card not found")
    return CardSourceConfigDetail.model_validate(card, from_attributes=True)


@router.post("/add", status_code=201, response_model=CatalogAddResponse)
def add_card(
    request: CatalogAddRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> CatalogAddResponse:
    try:
        card = catalog_service.add_card_from_catalog(
            session,
            user_id=current_user.user_id,
            source_id=request.source_id,
            open_date=request.open_date,
            force=request.force,
        )
        commit_or_conflict(session)
        return CatalogAddResponse(
            card_id=card.card_id,
            slug=card.slug,
            display_name=card.display_name,
            message=f"Card '{card.display_name}' added to your wallet.",
        )
    except catalog_service.DuplicateCardError as e:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"You already have '{e.existing_slug}' in your wallet.",
                "existing_card_id": e.card_id,
                "slug": e.existing_slug,
            },
        ) from e
    except ValueError as e:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
