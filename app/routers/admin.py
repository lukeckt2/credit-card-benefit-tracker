"""Administrative operation endpoints."""

from __future__ import annotations

from ipaddress import ip_address

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.routers._errors import commit_or_conflict
from app.schemas import RolloverRequest, RolloverResponse
from app.services import rollover as rollover_service


router = APIRouter(tags=["admin"])


def is_local_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


@router.post("/admin/rollover/preview", response_model=RolloverResponse)
def rollover_preview(
    payload: RolloverRequest,
    session: Session = Depends(get_session),
) -> RolloverResponse:
    return rollover_service.preview_rollover(session, payload)


@router.post("/admin/rollover/apply", response_model=RolloverResponse)
def rollover_apply(
    payload: RolloverRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> RolloverResponse:
    settings = get_settings()
    if settings.admin_local_only and not is_local_request(request):
        raise HTTPException(
            status_code=403,
            detail="Rollover apply is restricted to local requests.",
        )

    response = rollover_service.apply_rollover(session, payload)
    commit_or_conflict(session)
    return response
