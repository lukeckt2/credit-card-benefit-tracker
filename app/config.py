"""Configuration helpers that avoid hardcoded credentials.

Supports an ``APP_ENV`` environment variable (default ``"prod"``).  When set to
a non-prod value such as ``"dev"``, the configuration resolver checks for
environment-specific overrides **first** — for example ``DEV_DATABASE_HOST`` is
consulted before ``DATABASE_HOST``.  Only the values that actually differ between
environments need an override; everything else falls through to the base keys.

Usage examples::

    # Local debugging against the dev database:
    APP_ENV=dev uvicorn app.main:app --reload --host 127.0.0.1 --port 9211

    # Alembic migrations against dev:
    APP_ENV=dev alembic upgrade head

    # Default (prod) — no change required:
    uvicorn app.main:app --reload --host 127.0.0.1 --port 9211
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus


DEFAULT_DATABASE_NAME = "credit_card_benefits"
DEFAULT_DATABASE_USER = "credit_card_db_user"


def get_app_env() -> str:
    """Return the current environment name, lower-cased (default ``"prod"``)."""
    return os.getenv("APP_ENV", "prod").strip().lower()


def load_dotenv(path: str | os.PathLike[str] = ".env") -> None:
    """Load simple KEY=VALUE entries without overwriting existing env vars."""

    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ[key] = value


def _env_with_override(env: str, key: str, default: str) -> str:
    """Resolve an env var with optional environment-specific override.

    When *env* is ``"prod"`` (the default), this is equivalent to
    ``os.getenv(key, default)``.  For any other *env* value the resolver first
    checks ``{ENV}_{key}`` (e.g. ``DEV_DATABASE_HOST``) before falling back to
    *key* itself.
    """
    if env != "prod":
        override = os.getenv(f"{env.upper()}_{key}")
        if override is not None:
            return override
    return os.getenv(key, default)


def _prefixed_env(prefix: str, name: str, default: str, env: str = "prod") -> str:
    """Resolve a ``{prefix}_{name}`` variable with env-override and fallback.

    For the ``MIGRATION_DATABASE`` prefix the fallback chain is:
    ``{ENV}_MIGRATION_DATABASE_{name}`` → ``MIGRATION_DATABASE_{name}``
    → ``{ENV}_DATABASE_{name}`` → ``DATABASE_{name}`` → *default*.
    """
    full_key = f"{prefix}_{name}"
    if prefix == "DATABASE":
        return _env_with_override(env, full_key, default)
    # MIGRATION_DATABASE_* → fall back to DATABASE_*
    value = _env_with_override(env, full_key, "")
    if value:
        return value
    return _env_with_override(env, f"DATABASE_{name}", default)


def build_database_url(prefix: str = "DATABASE") -> str:
    """Build a SQLAlchemy URL from environment variables.

    ``MIGRATION_DATABASE_*`` values fall back to ``DATABASE_*`` values so Alembic
    can be configured before the final admin username is approved.

    When ``APP_ENV`` is set to a non-prod value (e.g. ``"dev"``), the resolver
    checks for ``{ENV}_{prefix}_{field}`` overrides first (e.g.
    ``DEV_DATABASE_HOST``).
    """

    env = get_app_env()

    override = _env_with_override(env, f"{prefix}_URL", "")
    if override:
        return override

    driver = _prefixed_env(prefix, "DRIVER", "mysql+pymysql", env)
    host = _prefixed_env(prefix, "HOST", "localhost", env)
    port = _prefixed_env(prefix, "PORT", "3306", env)
    database = _prefixed_env(prefix, "NAME", DEFAULT_DATABASE_NAME, env)
    user = _prefixed_env(prefix, "USER", DEFAULT_DATABASE_USER, env)
    password = _prefixed_env(prefix, "PASSWORD", "", env)

    auth = quote_plus(user)
    if password:
        auth = f"{auth}:{quote_plus(password)}"

    return f"{driver}://{auth}@{host}:{port}/{database}?charset=utf8mb4"


def _bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    admin_local_only: bool
    app_env: str


def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        database_url=build_database_url("DATABASE"),
        admin_local_only=_bool_env("ADMIN_LOCAL_ONLY", True),
        app_env=get_app_env(),
    )
