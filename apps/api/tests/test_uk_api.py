"""A product in a subheading the UK side has no rate for gets one read on demand (recorded Trade Tariff here), so the UK column prices."""
import json

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_api.services import catalogue as cat
from landfall_register import uk_ondemand
from landfall_register.db import make_engine
from sqlalchemy import text
from test_uk_ondemand_helpers import recorded_tariff

CLASSIFY = {"reason": "men's knitted cotton t-shirt", "hs6": "6109.10", "runner_up": None, "decisive_unknown": None, "origin_reason": "sewn in the workshop",
            "origin": "GB", "signals": [{"kind": "listing_text", "text": "sewn in our Leicester workshop", "points_to": "GB"}]}


class FakeLLM:
    def complete(self, system, user, max_tokens=600):
        if "national tariff line" in system:
            code = "6109.10.00" if "t-shirt" in user.lower() else "6912.00.44.00"
            return json.dumps({"reason": "plain line", "code": code, "runner_up": None, "decisive_unknown": None})
        if "t-shirt" in user.lower():
            return json.dumps(CLASSIFY)
        return json.dumps({**CLASSIFY, "hs6": "6912.00", "reason": "stoneware mug"})


@pytest.fixture(scope="module")
def client():
    with make_engine().begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    main.cat.llm_client = lambda: FakeLLM()
    with TestClient(main.app) as c:
        yield c


def gb(detail):
    return next(p for p in detail["recommendation"]["pricing"] if p["destination"] == "GB")


def test_uk_column_is_unpriced_until_the_subheading_is_read_then_priced(client, monkeypatch):
    body = {"title": "Mens cotton t-shirt", "description": "Men's knitted 100% cotton crew neck t-shirt, sewn in our Leicester workshop.",
            "prices": {"GBP": "30.00", "USD": "38.00", "EUR": "35.00"}, "category": "cotton"}
    monkeypatch.setattr(cat, "uk_get", lambda path: (_ for _ in ()).throw(OSError("offline")))  # the read fails: honest "no priced line"
    p1 = client.post("/api/products", json=body).json()
    d1 = client.post(f"/api/products/{p1['id']}/recommend").json()
    assert not gb(d1)["supported"] and "No priced" in gb(d1)["rule_applied"]
    monkeypatch.setattr(cat, "uk_get", recorded_tariff())
    p2 = client.post("/api/products", json={**body, "title": "Mens cotton t-shirt, second listing"}).json()
    d2 = client.post(f"/api/products/{p2['id']}/recommend").json()
    assert gb(d2)["supported"], gb(d2)
    with make_engine().connect() as c:
        row = c.execute(text("SELECT code, rate, source_url FROM rate_row WHERE destination = 'GB' AND code LIKE '610910%'")).mappings().one()
    assert row["code"] == "6109100010" and float(row["rate"]) == 12 and "trade-tariff.service.gov.uk" in row["source_url"]
    assert uk_ondemand  # the module the API uses
