"""Contract tests: recorded official-source responses parse into stable rows. No network."""
from decimal import Decimal

from landfall_register import loaders, repo


def test_parse_general_rate():
    p = loaders.parse_general_rate
    assert p("10%") == Decimal("10")
    assert p("9.8%") == Decimal("9.8")
    assert p("Free") == Decimal("0")
    assert p("5.3¢/kg + 11%") is None  # compound: the engine refuses these codes rather than under-charge
    assert p("") is None and p(None) is None


def test_usitc_loader_mug_row_matches_the_published_schedule(conn):
    v = repo.new_version(conn, "t1")
    rep = loaders.load_usitc_headings(conn, v)
    assert rep.rows_added > 100
    mug = [r for r in repo.rows_visible(conn, v, "US") if r["code"] == "6912.00.44.00"]
    assert len(mug) == 1 and mug[0]["rate"] == "10"
    wallet = [r for r in repo.rows_visible(conn, v, "US") if r["code"] == "4202.31.60.00"]
    assert wallet[0]["rate"] == "8"
    bowl = [r for r in repo.rows_visible(conn, v, "US") if r["code"] == "6912.00.48"]
    assert bowl[0]["rate"] == "9.8"
    assert all(r["source_ref"] for r in repo.rows_visible(conn, v, "US"))


def test_usitc_loader_reports_what_it_skips(conn):
    v = repo.new_version(conn, "t1")
    rep = loaders.load_usitc_headings(conn, v)
    assert any("not a pure ad valorem" in s for s in rep.skipped)


def test_uk_loader_stoneware_and_vat(conn):
    v = repo.new_version(conn, "t1")
    rep = loaders.load_uk_commodities(conn, v)
    rows = repo.rows_visible(conn, v, "GB")
    by = {(r["code"], r["measure"]): r for r in rows}
    assert by[("6912002310", "base_duty")]["rate"] == "4"
    assert by[("*", "import_vat")]["rate"] == "20"
    assert rep.rows_added >= 5


def test_tedb_loader_27_rates_greece_is_el(conn):
    v = repo.new_version(conn, "t1")
    rep = loaders.load_tedb_vat(conn, v)
    rows = repo.rows_visible(conn, v, "EU")
    assert rep.rows_added == 27 and len(rows) == 27
    by = {r["variant"]: r["rate"] for r in rows}
    assert by["EL"] == "24" and by["DE"] == "19" and "GR" not in by
