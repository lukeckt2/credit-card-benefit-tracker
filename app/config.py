"""Configuration helpers that avoid hardcoded credentials."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus


DEFAULT_DATABASE_NAME = "credit_card_benefits"
DEFAULT_DATABASE_USER = "credit_card_db_user"


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


def _prefixed_env(prefix: str, name: str, default: str) -> str:
    if prefix == "DATABASE":
        return os.getenv(f"{prefix}_{name}", default)
    return os.getenv(f"{prefix}_{name}") or os.getenv(f"DATABASE_{name}", default)


def build_database_url(prefix: str = "DATABASE") -> str:
    """Build a SQLAlchemy URL from environment variables.

    `MIGRATION_DATABASE_*` values fall back to `DATABASE_*` values so Alembic can
    be configured before the final admin username is approved.
    """

    override = os.getenv(f"{prefix}_URL")
    if override:
        return override

    driver = _prefixed_env(prefix, "DRIVER", "mysql+pymysql")
    host = _prefixed_env(prefix, "HOST", "localhost")
    port = _prefixed_env(prefix, "PORT", "3306")
    database = _prefixed_env(prefix, "NAME", DEFAULT_DATABASE_NAME)
    user = _prefixed_env(prefix, "USER", DEFAULT_DATABASE_USER)
    password = _prefixed_env(prefix, "PASSWORD", "")

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


def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        database_url=build_database_url("DATABASE"),
        admin_local_only=_bool_env("ADMIN_LOCAL_ONLY", True),
    )
