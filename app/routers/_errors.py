"""Router helpers for mapping service errors to HTTP responses."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services.errors import NotFoundError, ServiceValidationError


def http_not_found(error: NotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(error))


def http_validation_error(error: ServiceValidationError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(error))


def commit_or_conflict(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="The request conflicts with an existing database row.",
        ) from error
