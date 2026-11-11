import pytest
from landfall_register.db import database_url, make_engine, migrate
from sqlalchemy import text

START_DB = (
    "docker run -d --name landfall-pg -e POSTGRES_PASSWORD=landfall -e POSTGRES_DB=landfall_test "
    "-p 55432:5432 postgres:16"
)


@pytest.fixture(scope="session")
def engine():
    eng = make_engine()
    try:
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:  # fail loudly: a silently skipped register test would hide a broken constraint
        pytest.fail(f"Postgres not reachable at {database_url().split('@')[-1]} ({e}). Start it: {START_DB}")
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    migrate()
    return eng


@pytest.fixture()
def conn(engine):
    with engine.begin() as c:
        c.execute(text("TRUNCATE rate_row, source_run, register_version RESTART IDENTITY CASCADE"))
    with engine.connect() as c:
        yield c
        c.rollback()
