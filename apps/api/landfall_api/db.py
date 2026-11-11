"""API database helpers: migrations for the register and the app tables, and one shared engine."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from landfall_register.db import database_url, make_engine
from landfall_register.db import migrate as migrate_register
from sqlalchemy import Engine


@lru_cache(maxsize=1)
def engine() -> Engine:
    return make_engine()


def migrate_app(url: str | None = None) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", (url or database_url()).replace("%", "%%"))
    command.upgrade(cfg, "head")


def migrate_all() -> None:
    migrate_register()
    migrate_app()
