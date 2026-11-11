"""Rule Radar on the real register: seeded real items, a synthetic future row priced both sides, Absorb / Pass it on.

The seeded items (FR 2026-21600, the EU flat duty end date, the UK relief timing) are real and cited. The synthetic rows
exist only in this test database to prove the matching and pricing; they are never in a shipped seed.
"""
import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_api.services import radar
from landfall_register import repo
from landfall_register.db import make_engine
from sqlalchemy import text

TODAY = date(2026, 11, 1)
CLASSIFY = {"hs6": "6912.00", "reason": "stoneware mug", "origin": "GB", "origin_reason": "thrown in the studio",
            "signals": [{"kind": "listing_text", "text": "Thrown by hand in our Stoke studio", "points_to": "GB"}]}


class FakeLLM:
    def complete(self, system, user, max_tokens=600):
        if "national tariff line" in system:
            return json.dumps({"code": "6912.00.44.00", "reason": "Mugs and other steins"})
        return json.dumps(CLASSIFY)


@pytest.fixture(scope="module")
def client():
    eng = make_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    main.cat.llm_client = lambda: FakeLLM()
    radar.today = lambda: TODAY
    with TestClient(main.app) as c:
        yield c


def add_row(code: str, origin: str, rate: str, valid_from: str, measure: str = "additional_duty", dest: str = "US", title: str = "Test duty on ceramic tableware", variant: str | None = None) -> int:
    eng = make_engine()
    with eng.begin() as conn:
        v = repo.new_version(conn, f"test-{code}-{origin}-{valid_from}-{measure}", "test")
        return repo.add_row(conn, v, {
            "destination": dest, "code": code, "origin_scope": origin, "measure": measure, "variant": variant, "rate_kind": "percent", "rate": rate,
            "valid_from": date.fromisoformat(valid_from), "valid_to": None, "params": {"title": title},
            "source_ref": "Test notice, synthetic", "source_url": "https://www.federalregister.gov/d/test"})


def alerts(client) -> dict:
    r = client.get("/api/radar")
    assert r.status_code == 200, r.text
    return {a["title"]: a for a in r.json()}


def test_real_items_are_listed_with_sources(client):
    a = alerts(client)
    entry = a["Formal entry becomes mandatory for postal parcels carrying extra duties"]
    assert entry["status"] == "further_out" and entry["effective_from"] == "2027-01-20" and entry["days_left"] == 80
    assert entry["source_url"] == "https://www.federalregister.gov/d/2026-21600" and entry["impact_per_order"] is None
    assert entry["affected_product_ids"] == []
    eu = next(x for x in a.values() if x["destination"] == "EU")
    assert eu["effective_from"] == "2028-07-01" and eu["status"] == "further_out" and eu["source_url"]
    uk = next(x for x in a.values() if x["destination"] == "GB")
    assert uk["status"] == "watching" and uk["effective_from"] is None and uk["days_left"] is None
    assert "OCT 2028" in uk["effective_label"] and uk["source_url"].startswith("https://www.gov.uk/")
    took = [x for x in a.values() if x["status"] == "in_effect" and x["destination"] == "US"]
    uk_s301 = next(x for x in took if x["title"] == "Additional duty on goods from the United Kingdom")
    assert uk_s301["effective_from"] == "2026-07-24" and uk_s301["days_left"] is None and "TOOK EFFECT 24 JUL 2026" in uk_s301["effective_label"]
    assert uk_s301["source_url"] == "https://www.federalregister.gov/d/2026-15181" and "Section 301" in uk_s301["summary"]
    assert client.post(f"/api/radar/{uk_s301['id']}/choice", json={"choice": "absorb"}).status_code == 422  # already in prices: nothing to decide
    assert all(x["source_url"] for x in a.values())  # EF-03: a source link on every item


def test_future_row_becomes_an_act_alert_with_days_and_impact(client):
    add_row("6912", "GB", "5", "2026-12-01")
    a = alerts(client)["Test duty on ceramic tableware"]
    assert a["status"] == "act" and a["days_left"] == 30 and a["effective_from"] == "2026-12-01"
    assert a["affected_product_ids"] == ["p_mug"]  # the only accepted product that matches code and origin
    assert a["impact_per_order"] == {"amount": "1.90", "currency": "USD"}  # 5% of 38.00, priced both sides with the engine
    assert a["choice"] is None and a["source_url"] == "https://www.federalregister.gov/d/test"


def test_other_origin_does_not_match_the_product(client):
    add_row("6912", "CN", "7", "2026-12-15", title="Test duty on Chinese ceramics")
    a = [x for x in client.get("/api/radar").json() if x["effective_from"] == "2026-12-15"][0]
    assert a["affected_product_ids"] == [] and a["status"] == "further_out" and a["impact_per_order"] is None


def test_choice_is_persisted_and_can_change(client):
    a = alerts(client)["Test duty on ceramic tableware"]
    r = client.post(f"/api/radar/{a['id']}/choice", json={"choice": "pass_on"})
    assert r.status_code == 200 and r.json()["choice"] == "pass_on"
    assert "$1.90" in r.json()["scheduled_price_change"] and "1 Dec 2026" in r.json()["scheduled_price_change"]
    again = alerts(client)["Test duty on ceramic tableware"]
    assert again["choice"] == "pass_on"
    r = client.post(f"/api/radar/{a['id']}/choice", json={"choice": "absorb"})
    assert r.json()["choice"] == "absorb" and "unchanged" in r.json()["scheduled_price_change"]
    with make_engine().connect() as c:
        assert c.execute(text("SELECT choice FROM radar_choice WHERE alert_key = :k"), {"k": a["id"]}).scalar_one() == "absorb"
        assert c.execute(text("SELECT count(*) FROM audit_event WHERE action = 'radar_choice'")).scalar_one() == 2


def test_choice_needs_a_price_change_and_a_known_alert(client):
    entry = alerts(client)["Formal entry becomes mandatory for postal parcels carrying extra duties"]
    assert client.post(f"/api/radar/{entry['id']}/choice", json={"choice": "absorb"}).status_code == 422
    assert client.post("/api/radar/ra_nope/choice", json={"choice": "absorb"}).status_code == 404


def test_neither_choice_changes_the_declared_duty(client):
    """Radar never rewards declaring less duty: the choice has no path into the quote or the PayPal tax lines."""
    a = alerts(client)["Test duty on ceramic tableware"]
    body = {"shop_id": "shop_kiln", "destination": "US", "currency": "USD", "items": [{"product_id": "p_mug", "quantity": 1}],
            "import_date": "2026-12-02"}
    seen = []
    for choice in ("pass_on", "absorb"):
        client.post(f"/api/radar/{a['id']}/choice", json={"choice": choice})
        q = client.post("/api/quote", json=body).json()
        seen.append((q["tax_total"], [ln["duty_and_tax"] for ln in q["lines"]]))
    assert seen[0] == seen[1]
    assert seen[0][0] == {"amount": "9.50", "currency": "USD"}  # 10% + 10% Section 301 + the 5% test row on 38.00 = 25%


def test_absorb_is_a_seller_funded_discount_that_leaves_the_declared_duty_alone(client):
    """Absorb it: from the effective date each order carries a discount equal to the rise, so the buyer pays what they paid the
    day before. The duty (tax_total, per-item tax) is the full new duty. Pass it on: no discount, the buyer total rises.
    Orders with an import date before the effective date are untouched."""
    a = alerts(client)["Test duty on ceramic tableware"]
    body = {"shop_id": "shop_kiln", "destination": "US", "currency": "USD", "items": [{"product_id": "p_mug", "quantity": 2}]}
    before = client.post("/api/quote", json={**body, "import_date": "2026-11-20"}).json()
    after = {"import_date": "2026-12-02"}

    client.post(f"/api/radar/{a['id']}/choice", json={"choice": "pass_on"})
    passed = client.post("/api/quote", json={**body, **after}).json()
    assert passed["seller_discount"]["amount"] == "0.00"
    assert Decimal(passed["total"]["amount"]) - Decimal(before["total"]["amount"]) == Decimal("3.80")  # 5% of 76.00

    client.post(f"/api/radar/{a['id']}/choice", json={"choice": "absorb"})
    absorbed = client.post("/api/quote", json={**body, **after}).json()
    assert absorbed["tax_total"] == passed["tax_total"]  # the declared duty never shrinks
    assert [ln["duty_and_tax"] for ln in absorbed["lines"]] == [ln["duty_and_tax"] for ln in passed["lines"]]
    assert absorbed["seller_discount"] == {"amount": "3.80", "currency": "USD"}
    assert absorbed["total"] == before["total"]  # the buyer pays what they paid before the change
    still_before = client.post("/api/quote", json={**body, "import_date": "2026-11-20"}).json()
    assert still_before["seller_discount"]["amount"] == "0.00" and still_before["total"] == before["total"]


def test_absorbed_order_reaches_paypal_with_a_discount_and_the_full_tax(client, monkeypatch):
    from landfall_api.services import checkout
    created = []

    class PP:
        def create_order(self, body, request_id):
            created.append(body)
            return {"id": "PP-ABS", "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=PP"}]}

    monkeypatch.setattr(checkout, "paypal_client", lambda: PP())
    a = alerts(client)["Test duty on ceramic tableware"]
    client.post(f"/api/radar/{a['id']}/choice", json={"choice": "absorb"})
    quote_in = {"shop_id": "shop_kiln", "destination": "US", "currency": "USD", "items": [{"product_id": "p_mug", "quantity": 1}], "import_date": "2026-12-02"}
    r = client.post("/api/orders", json={"quote": quote_in, "return_url": "https://x.test/c", "cancel_url": "https://x.test/x"})
    assert r.status_code == 200, r.text
    unit = created[0]["purchase_units"][0]
    br = unit["amount"]["breakdown"]
    assert br["tax_total"]["value"] == "9.50" and unit["items"][0]["tax"]["value"] == "9.50"
    assert br["discount"]["value"] == "1.90" and unit["amount"]["value"] == "59.60"
    assert r.json()["total"]["amount"] == "59.60"


def test_absorb_covers_only_the_changes_the_seller_chose_to_absorb(client):
    """The discount is the sum of the absorbed steps. A later rise the seller did not absorb (or never saw) is paid by the buyer."""
    add_row("6912", "GB", "3", "2026-12-20", title="Test later rise on ceramic tableware", variant="later")
    mine = alerts(client)["Test duty on ceramic tableware"]
    later = alerts(client)["Test later rise on ceramic tableware"]
    assert client.post(f"/api/radar/{mine['id']}/choice", json={"choice": "absorb"}).status_code == 200
    assert client.post(f"/api/radar/{later['id']}/choice", json={"choice": "pass_on"}).status_code == 200
    body = {"shop_id": "shop_kiln", "destination": "US", "currency": "USD", "items": [{"product_id": "p_mug", "quantity": 2}], "import_date": "2026-12-25"}
    q = client.post("/api/quote", json=body).json()
    assert q["seller_discount"]["amount"] == "3.80"  # the 5% step on 76.00 only, not the 3% that followed
    before = client.post("/api/quote", json={**body, "import_date": "2026-11-20"}).json()
    assert Decimal(q["total"]["amount"]) - Decimal(before["total"]["amount"]) == Decimal("2.28")  # the buyer pays the 3% rise
    client.post(f"/api/radar/{later['id']}/choice", json={"choice": "absorb"})  # absorbing it too covers both steps
    assert client.post("/api/quote", json=body).json()["seller_discount"]["amount"] == "6.08"
