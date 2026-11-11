"""Time Machine endpoint on the seeded register (needs Postgres, like the register tests)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from landfall_api.main import app
from landfall_register.db import make_engine
from sqlalchemy import text


@pytest.fixture(scope="module")
def client():
    eng = make_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    with TestClient(app) as c:
        yield c


def test_options(client):
    r = client.get("/api/timemachine/options").json()
    assert {"GB", "IN", "EU", "CN", "VN"} <= {o["id"] for o in r["origins"]} and len(r["products"]) == 5


def test_mug_uk_to_us_series_matches_the_legal_timeline(client):
    r = client.get("/api/timemachine/series", params={"product": "p_mug", "origin": "GB", "destination": "US"})
    assert r.status_code == 200
    s = r.json()
    by = {p["date"]: p for p in s["points"]}
    assert by["2025-01-01"]["buyer_total"]["amount"] == "52.00"      # 38 + 14, duty-free under de minimis
    assert by["2025-09-01"]["duty_and_tax"]["amount"] == "7.60"      # de minimis suspended: 10% + 10% IEEPA
    assert by["2026-11-01"]["buyer_total"]["amount"] == "59.60"      # the demo anchor
    changes = [p["date"] for p in s["points"] if p["is_change_date"]]
    assert "2025-04-05" in changes and "2025-08-29" in changes and "2026-02-24" in changes and "2026-07-24" in changes
    assert all(p["source_ref"] for p in s["points"] if p["is_change_date"])
    assert s["register_version"].startswith("r-")
    assert date.fromisoformat(s["today"]) <= date.today()


def test_origin_without_coverage_is_honest(client):
    s = client.get("/api/timemachine/series", params={"product": "p_mug", "origin": "IN", "destination": "US"}).json()
    assert s["points"][0]["date"] >= "2026-02-24"  # India is verified only from the Section 122 / 301 period


def test_unknown_product_is_404(client):
    assert client.get("/api/timemachine/series", params={"product": "nope", "origin": "GB", "destination": "US"}).status_code == 404
