"""
CATCH - FastAPI entry point.

A self-hosted FastAPI + MariaDB application for tracking credit card benefits, usage, and rollovers.

Local debugging (prod database):
    DATABASE_HOST=127.0.0.1 uvicorn app.main:app --reload --host 127.0.0.1 --port 9211

Local debugging (dev database — DEV_DATABASE_HOST resolved from .env):
    DEV_DEFAULT_USER=admin APP_ENV=dev uvicorn app.main:app --reload --host 127.0.0.1 --port 9211

Authentication Testing:
    - By default, requests without proxy headers in dev mode will fallback to the user specified in .env.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers import admin, auth, benefit_definitions, benefit_periods, cards, dashboard


STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="CATCH")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/api/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok", "database": "not_checked"}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.ico")


app.include_router(auth.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(cards.router, prefix="/api")
app.include_router(benefit_definitions.router, prefix="/api")
app.include_router(benefit_periods.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
