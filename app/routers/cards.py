"""Card endpoints."""

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
from app.services import card_csv_import
import uuid
import tempfile
from pathlib import Path
from datetime import date
from typing import Any
from pydantic import BaseModel
from fastapi import File, UploadFile, HTTPException

UPLOAD_DIR = Path(tempfile.gettempdir()) / "catch_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

class ImportConfirmRequest(BaseModel):
    token: str


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


@router.post("/cards/upload")
def upload_card_csv(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    token = uuid.uuid4().hex
    tmp_path = UPLOAD_DIR / f"{token}.csv"
    
    with tmp_path.open("wb") as tmp:
        tmp.write(file.file.read())

    plan = card_csv_import.build_plan(tmp_path, as_of=date.today())
    preview_data = card_csv_import.plan_output(plan, session, user_id=current_user.user_id, include_details=True)
    
    preview_data["token"] = token
    return preview_data


@router.post("/cards/import", status_code=201)
def confirm_import_card(
    request: ImportConfirmRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    tmp_path = UPLOAD_DIR / f"{request.token}.csv"
    if not tmp_path.exists():
        raise HTTPException(status_code=404, detail="Upload session not found or expired.")

    plan = card_csv_import.build_plan(tmp_path, as_of=date.today())
    card_csv_import.annotate_actions(plan, session, user_id=current_user.user_id)
    
    if card_csv_import.has_blocking_issues(plan):
        warnings = card_csv_import.output_warnings(plan)
        raise HTTPException(
            status_code=400,
            detail={
                "message": "CSV has blocking issues or conflicts.",
                "warnings": [w.as_dict() for w in warnings],
                "skipped": [s.as_dict() for s in plan.skipped_rows]
            }
        )
    
    result = card_csv_import.apply_plan(plan, session, user_id=current_user.user_id)
    commit_or_conflict(session)
    
    tmp_path.unlink(missing_ok=True)
    
    return result
