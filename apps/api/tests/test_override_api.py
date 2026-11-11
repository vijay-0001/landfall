"""Never a dead end: when Landfall finds no code the seller can look one up and override with it; goods refused for legal, safety or moral reasons cannot be accepted or overridden."""
import json

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_register.db import make_engine
from sqlalchemy import text

NONE = {"hs6": "none", "reason": "carved from stone, not ceramic", "origin": "GB", "origin_reason": "shop country", "signals": [{"kind": "shop_country", "text": "UK shop", "points_to": "GB"}]}


class FakeLLM:
    def complete(self, system, user, max_tokens=600):
        return json.dumps(NONE)


@pytest.fixture(scope="module")
def client():
    with make_engine().begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    main.cat.llm_client = lambda: FakeLLM()
    with TestClient(main.app) as c:
        yield c


def product(client, title, description="Hand carved from a block of stone, 300 ml, polished."):
    p = client.post("/api/products", json={"title": title, "description": description, "prices": {"GBP": "50.00", "USD": "65.00", "EUR": "59.00"}}).json()
    d = client.post(f"/api/products/{p['id']}/recommend").json()
    return p["id"], d["recommendation"]["id"], d


def decide(client, rec, **body):
    return client.post(f"/api/recommendations/{rec}/decision", json={"fine_print_version": "fp-2026-11-01.1", **body})


def test_no_code_found_leads_to_help_links_and_accept_is_refused(client):
    pid, rec, d = product(client, "Stone mug")
    r = d["recommendation"]
    assert r["code"] == "none" and r["help_prominent"] and len(r["help_links"]) >= 4 and "stone mug" in r["help_terms"]
    assert all("stone" in k["url"].lower() or "taric" in k["url"].lower() for k in r["help_links"])
    assert decide(client, rec, action="accepted").status_code == 409  # nothing to accept


def test_override_with_a_real_code_makes_the_product_sellable_and_priced(client):
    pid, rec, _ = product(client, "Stone cup")
    r = decide(client, rec, action="overridden", code="6912.00.44.00", origin="GB")
    assert r.status_code == 200 and r.json()["code"] == "6912.00.44.00"
    detail = client.get(f"/api/products/{pid}").json()
    assert detail["product"]["review_status"] == "overridden" and not detail["product"]["paused_reason"]
    assert any(p["destination"] == "US" and p["supported"] for p in detail["recommendation"]["pricing"])
    q = client.post("/api/quote", json={"shop_id": "shop_kiln", "destination": "US", "currency": "USD", "items": [{"product_id": pid, "quantity": 1}]}).json()
    assert q["duties_included"] and q["tax_total"]["amount"] == "13.00"  # 20% of 65


@pytest.mark.parametrize("code,why", [("12", "8 or 10 digits"), ("abcd.ef.gh", "8 or 10 digits"), ("6912.00", "8 or 10 digits"), ("9999.99.99.99", "no priced line"),
                                       ("0201.10.05", "no priced line")])
def test_an_override_code_must_be_a_priced_us_line(client, code, why):
    pid, rec, _ = product(client, f"Stone jar {code}")
    r = decide(client, rec, action="overridden", code=code, origin="GB")
    assert r.status_code == 422 and why in r.json()["detail"]
    assert client.get(f"/api/products/{pid}").json()["product"]["review_status"] == "not_reviewed"


def test_an_override_origin_must_be_a_country_code(client):
    _, rec, _ = product(client, "Stone pot")
    assert decide(client, rec, action="overridden", code="6912.00.44.00", origin="Narnia").status_code == 422


def test_goods_refused_for_legal_reasons_cannot_be_accepted_or_overridden(client):
    pid, rec, d = product(client, "Uranium glass vase", "Vintage uranium glass vase, slightly radioactive.")
    assert d["recommendation"]["help_links"] == [] and "radioactive" in d["product"]["paused_reason"]
    assert decide(client, rec, action="accepted").status_code == 409
    assert decide(client, rec, action="overridden", code="6912.00.44.00", origin="GB").status_code == 409
    for word in ("plutonium", "cocaine", "ivory tusk", "assault rifle", "human skull", "stolen", "counterfeit Rolex"):
        _, _, dd = product(client, f"Rare {word} item", f"A genuine {word} for sale, very rare.")
        assert dd["product"]["paused_reason"].startswith("Landfall will not price this"), word
