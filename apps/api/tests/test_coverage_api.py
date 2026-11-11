"""GET /api/coverage: what is covered today and where the data comes from. Only what is covered is listed. Origins come from the register, run times from source_run."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_api.services import coverage as cov
from landfall_register.db import make_engine
from sqlalchemy import text


@pytest.fixture(scope="module")
def client():
    eng = make_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    with TestClient(main.app) as c:
        yield c


def test_coverage_is_a_matrix_of_covered_origins_by_covered_destinations_and_nothing_else(client):
    r = client.get("/api/coverage")
    assert r.status_code == 200, r.text
    j = r.json()
    assert [d["id"] for d in j["destinations"]] == ["US", "GB", "EU", "AU"]
    assert "broker" in next(d for d in j["destinations"] if d["id"] == "AU")["note"]
    origins = {o["code"]: o for o in j["origins"]}
    assert set(origins) == {"GB", "IN", "EU", "CN", "VN", "TR", "TH", "ID", "BD", "PK", "JP", "KR"}
    assert all(o["destinations"] == ["US", "GB", "EU", "AU"] for o in origins.values())
    assert [o["name"] for o in j["origins"]] == sorted(o["name"] for o in j["origins"]), "alphabetical"
    text_ = str(j)
    for left_out in ("Canada", "Mexico", "TARIC", "Section 232", "not built", "compound"):
        assert left_out not in text_, f"{left_out} is not covered, so it is not listed"
    assert "planned for a later phase" in j["disclaimer"] and "not customs advice" in j["disclaimer"]


def test_sources_are_the_four_automatic_ones_and_the_curated_table_with_their_schedule(client):
    j = client.get("/api/coverage").json()
    by = {x["id"]: x for x in j["sources"]}
    assert list(by) == ["usitc", "uk", "tedb", "federal_register", "au_table"]
    assert by["usitc"]["refreshed"] == "Every night, 02:00 UTC"
    assert "person approves" in by["federal_register"]["provides"]
    assert by["au_table"]["status"] == "manual" and by["au_table"]["last_success_at"] is None and "not refreshed automatically" in by["au_table"]["refreshed"]
    assert "48 hours" in j["stale_rule"] and "7 days" in j["pause_rule"]


def test_source_status_follows_source_run_and_the_48h_and_7d_rules(client):
    now = datetime.now(UTC)
    with make_engine().begin() as c:
        c.execute(text("DELETE FROM source_run WHERE source IN ('usitc', 'uk', 'tedb')"))
        for src, age in (("usitc", timedelta(hours=1)), ("uk", timedelta(hours=60)), ("tedb", timedelta(days=8))):
            c.execute(text("INSERT INTO source_run (source, finished_at, ok, rows_changed, future_dated, publish, detail) VALUES (:s, :t, true, 0, 0, 'automatic', NULL)"),
                      {"s": src, "t": now - age})
        out = cov.coverage(c, now)
    st = {x.id: x.status for x in out.sources}
    assert (st["usitc"], st["uk"], st["tedb"]) == ("ok", "stale", "paused")
