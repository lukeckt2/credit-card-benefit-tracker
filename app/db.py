"""Database engine and session setup."""

from __future__ import annotations

from collections.abc import Generator

import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)

if "host.docker.internal" in settings.database_url and not os.path.exists("/.dockerenv"):
    try:
        with engine.connect():
            pass
    except OperationalError:
        print(
            "\n" + "="*80 + "\n"
            "CRITICAL DATABASE CONNECTION ERROR\n"
            "================================================================================\n"
            "The application is trying to connect to 'host.docker.internal' from OUTSIDE\n"
            "a Docker container. This usually fails on Linux host machines.\n\n"
            "Please override the DATABASE_HOST environment variable when running directly\n"
            "on the host. For example:\n"
            "    DATABASE_HOST=127.0.0.1 <your-command>\n"
            "================================================================================\n",
            file=sys.stderr
        )
        sys.exit(1)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
