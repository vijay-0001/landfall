"""Sync contract tests on recorded payloads: diff, publish, and what a failed source does. No network."""
import json
from datetime import date
from pathlib import Path

import pytest
from landfall_register import loaders, repo
from landfall_register.db import make_engine, migrate
from landfall_worker import sync
from sqlalchemy import text

FIX = Path(loaders.FIXTURES)


@pytest.fixture()
def conn():
    eng = make_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    migrate()
    with eng.begin() as c:
        v = repo.new_version(c, "r-seed")
        loaders.load_usitc_headings(c, v)
        loaders.load_uk_commodities(c, v)
        loaders.load_tedb_vat(c, v)
    with eng.connect() as c:
        yield c
        c.rollback()


def recorded(h):
    return json.loads((FIX / "usitc" / f"hts_{h}.json").read_text(encoding="utf-8"))


def mug_rate(conn, version, on):
    rows = [r for r in repo.rows_visible(conn, version, "US") if r["code"] == "6912.00.44.00"
            and r["valid_from"] <= on.isoformat() and (r["valid_to"] is None or r["valid_to"] > on.isoformat())]
    assert len(rows) == 1
    return rows[0]["rate"]


def test_hts_sync_no_change_publishes_nothing(conn):
    before = repo.latest_version(conn)
    rep = sync.sync_hts(conn, recorded)
    assert rep.ok and rep.rows_changed == 0 and repo.latest_version(conn) == before


def test_hts_sync_detects_a_rate_change_and_keeps_history(conn):
    def changed(h):
        d = recorded(h)
        if h == "6912":
            for r in d["rows"]:
                if r["htsno"] == "6912.00.44.00":
                    r["general"] = "12%"
        return d

    v_before = repo.latest_version(conn)
    rep = sync.sync_hts(conn, changed, today=date(2026, 11, 2))
    assert rep.ok and rep.changed == 1
    v_after = repo.latest_version(conn)
    assert v_after == v_before + 1
    assert mug_rate(conn, v_after, date(2026, 11, 3)) == "12"
    assert mug_rate(conn, v_after, date(2026, 10, 1)) == "10"  # valid-time history kept
    assert mug_rate(conn, v_before, date(2026, 11, 3)) == "10"  # replay by version: what we knew then


def test_failed_source_changes_nothing_and_is_recorded(conn):
    def boom(h):
        raise RuntimeError("503 from the source")

    before = repo.latest_version(conn)
    rep = sync.sync_hts(conn, boom)
    assert not rep.ok and "fetch failed" in rep.detail and repo.latest_version(conn) == before
    sync.record_run(conn, rep)
    assert conn.execute(text("SELECT ok FROM source_run WHERE source = 'usitc'")).scalar_one() is False


def tedb_xml(de_rate):
    rows = "".join(
        f"<t:vatRateResults><t:memberState>{s}</t:memberState><t:type>STANDARD</t:type>"
        f"<t:rate><t:type>STANDARD_RATE</t:type><t:value>{de_rate if s == 'DE' else 21.0}</t:value></t:rate></t:vatRateResults>"
        for s in sync.EU_STATES)
    return f"<e xmlns:t='urn:ec.europa.eu:taxud:tedb:services:v1:IVatRetrievalService:types'>{rows}</e>".encode()


def test_tedb_parser_and_sync(conn):
    xml = tedb_xml(20.0)
    rates = sync.parse_tedb(xml)
    assert len(rates) == 27 and rates["DE"] == 20
    rep = sync.sync_tedb(conn, lambda: xml, today=date(2026, 11, 2))
    assert rep.ok and rep.changed >= 1
    de = [r for r in repo.rows_visible(conn, None, "EU") if r["variant"] == "DE" and r["valid_to"] is None][0]
    assert de["rate"] == "20"


def test_tedb_short_answer_is_rejected(conn):
    xml = b"<e xmlns:t='urn:ec.europa.eu:taxud:tedb:services:v1:IVatRetrievalService:types'></e>"
    assert not sync.sync_tedb(conn, lambda: xml).ok


def test_uk_sync_reads_recorded_commodity(conn):
    def fetch(code):
        return json.loads((FIX / "uk_tariff" / f"commodity_{code}.json").read_text(encoding="utf-8"))

    rep = sync.sync_uk(conn, fetch)
    assert rep.ok and rep.rows_changed == 0
