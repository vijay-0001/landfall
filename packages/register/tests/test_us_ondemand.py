"""US headings on demand: a heading outside the core set is read when a product lands in it, stored as one new version with its source,
only plain-percentage or Free rates enter the register, and a failed read leaves it untouched."""
from decimal import Decimal

from landfall_register import loaders, repo, us_ondemand

TOYS = {"fetched": "2026-11-03", "rows": [
    {"htsno": "9503.00", "indent": "0", "description": "Tricycles, scooters and similar wheeled toys", "general": ""},
    {"htsno": "9503.00.00", "indent": "1", "description": "Toys", "general": "Free"},
    {"htsno": "9503.00.99", "indent": "1", "description": "Other toys", "general": "3.5 cents/kg + 2%"},
    {"htsno": "9503.00.10", "indent": "1", "description": "Dolls", "general": "6.5%"},
]}


def us_rows(conn, prefix):
    return [r for r in repo.rows_visible(conn, repo.latest_version(conn), "US") if r["measure"] == "base_duty" and r["code"].startswith(prefix)]


def test_a_new_heading_is_loaded_once_with_plain_rates_only(conn):
    repo.new_version(conn, "base", "test")
    got = us_ondemand.ensure_headings(conn, ["9503"], lambda h: TOYS)
    assert got == ["9503"]
    rows = {r["code"]: r for r in us_rows(conn, "9503")}
    assert set(rows) == {"9503.00.00", "9503.00.10"}  # the compound rate is never stored: that line stays "not priced"
    assert Decimal(rows["9503.00.10"]["rate"]) == Decimal("6.5") and "USITC" in rows["9503.00.10"]["source_ref"]
    n = conn.execute(__import__("sqlalchemy").text("SELECT count(*) FROM register_version")).scalar_one()
    assert us_ondemand.ensure_headings(conn, ["9503"], lambda h: TOYS) == []  # already there: no second version
    assert conn.execute(__import__("sqlalchemy").text("SELECT count(*) FROM register_version")).scalar_one() == n


def test_a_failed_read_changes_nothing(conn):
    repo.new_version(conn, "base", "test")
    v = repo.latest_version(conn)

    def boom(h):
        raise OSError("USITC unreachable")

    assert us_ondemand.ensure_headings(conn, ["9503"], boom) == []
    assert repo.latest_version(conn) == v and us_rows(conn, "9503") == []


def test_the_initial_load_covers_the_core_headings_only(conn):
    v = repo.new_version(conn, "base", "test")
    loaders.load_usitc_headings(conn, v)
    heads = {r["code"][:4] for r in us_rows(conn, "")}
    assert heads and heads <= set(loaders.CORE_HEADINGS)
