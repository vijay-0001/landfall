"""Database access. Sync SQLAlchemy with the pg8000 driver (BSD); psycopg is LGPL and is not used."""
from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine

DEFAULT_URL = "postgresql+pg8000://postgres:landfall@localhost:55432/landfall_test"


def database_url() -> str:
    url = os.environ.get("LANDFALL_DATABASE_URL") or os.environ.get("LANDFALL_TEST_DATABASE_URL") or DEFAULT_URL
    return url.replace("postgresql+asyncpg://", "postgresql+pg8000://").replace("postgresql://", "postgresql+pg8000://")


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url(), future=True, pool_pre_ping=True)


def migrate(url: str | None = None, revision: str = "head") -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", (url or database_url()).replace("%", "%%"))
    command.upgrade(cfg, revision)
