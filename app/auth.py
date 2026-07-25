"""Authelia reverse-proxy authentication: read trusted headers."""

import logging
import os

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import User

logger = logging.getLogger(__name__)

# Header name set by the reverse proxy (Authelia default: "Remote-User")
REMOTE_USER_HEADER = os.getenv("TRUSTED_PROXY_HEADER", "Remote-User")

# Dev-mode fallback: when APP_ENV=dev and no header is present, use this user
DEV_DEFAULT_USER = os.getenv("DEV_DEFAULT_USER", "")

# Authelia base URL (configurable — used to build the logout redirect)
AUTHELIA_URL = os.getenv("AUTHELIA_URL", "")


def get_current_user(
    request: Request,
    session: Session = Depends(get_session),
) -> User:
    """FastAPI dependency: resolve the authenticated user from proxy headers.

    In production, Authelia sets the Remote-User header after authentication.
    In dev mode (APP_ENV=dev), falls back to DEV_DEFAULT_USER env var if the
    header is absent, so local development works without a proxy.
    """
    username = request.headers.get(REMOTE_USER_HEADER)

    if not username:
        app_env = os.getenv("APP_ENV", "prod").strip().lower()
        if app_env != "prod" and DEV_DEFAULT_USER:
            username = DEV_DEFAULT_USER
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication header",
            )

    # Look up existing user or auto-provision
    user = session.execute(
        select(User).where(User.username == username)
    ).scalar_one_or_none()

    if user is None:
        user = User(username=username)
        session.add(user)
        session.flush()  # Assign user_id
        session.commit() # Save to DB
        logger.info("Auto-provisioned new user: %s (user_id=%d)", username, user.user_id)

    return user
