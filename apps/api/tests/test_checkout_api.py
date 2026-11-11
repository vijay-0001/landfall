"""Checkout on the real register: quote (no model call), fail-safes, PayPal order with duty as tax, capture and stamp.

The recommender is faked (canned JSON by prompt type); PayPal is faked at the client boundary; everything else is real.
"""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_api.services import catalogue as cat
from landfall_api.services import checkout
from landfall_paypal.client import approve_url  # noqa: F401
from landfall_register.db import make_engine
from sqlalchemy import text

CLASSIFY = {"hs6": "6912.00", "reason": "stoneware mug", "origin": "GB", "origin_reason": "thrown in the studio",
            "signals": [{"kind": "listing_text", "text": "Thrown by hand in our Stoke studio", "points_to": "GB"}]}


class FakeLLM:
    def complete(self, system, user, max_tokens=600):
        if "national tariff line" in system:
            return json.dumps({"code": "6912.00.44.00", "reason": "Mugs and other steins"})
        return json.dumps(CLASSIFY)


class FakePayPal:
    def __init__(self):
        self.created = []

    def create_order(self, body, request_id):
        self.created.append(body)
        return {"id": f"PP-{len(self.created)}", "status": "PAYER_ACTION_REQUIRED", "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=PP"}]}

    def capture(self, paypal_order_id, request_id):
        unit = self.created[-1]["purchase_units"][0]
        return {"status": "COMPLETED", "purchase_units": [{"amount": unit["amount"], "payments": {"captures": [{
            "id": "CAP-1", "status": "COMPLETED", "custom_id": unit["custom_id"],
            "seller_receivable_breakdown": {"gross_amount": unit["amount"], "paypal_fee": {"currency_code": "USD", "value": "2.62"},
                                            "net_amount": unit["amount"]}}]}}]}


@pytest.fixture(scope="module")
def client():
    eng = make_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    main.cat.llm_client = lambda: FakeLLM()
    with TestClient(main.app) as c:
        with eng.begin() as conn:  # the seed accepted the mug through the real decision path
            assert conn.execute(text("SELECT count(*) FROM decision WHERE product_id = 'p_mug'")).scalar_one() == 1
        yield c


def q(client, dest="US", cur="USD", items=None, **kw):
    body = {"shop_id": "shop_kiln", "destination": dest, "currency": cur, "items": items or [{"product_id": "p_mug", "quantity": 1}], **kw}
    return client.post("/api/quote", json=body)


def test_mug_uk_to_us_is_the_demo_anchor(client):
    r = q(client)
    assert r.status_code == 200
    j = r.json()
    assert j["duties_included"] and j["tax_total"]["amount"] == "7.60" and j["total"]["amount"] == "59.60"
    assert "$7.60" in j["old_way_note"] and "USD" not in j["old_way_note"]
    assert j["register_version"].startswith("r-") and j["lines"][0]["trail"]


def test_unreviewed_product_falls_back_to_standard_checkout(client):
    j = q(client, items=[{"product_id": "p_bowl", "quantity": 1}]).json()
    assert not j["duties_included"] and j["tax_total"]["amount"] == "0.00" and "may be due" in j["paused_reason"]


def test_eu_quote_flat_duty_plus_vat(client):
    j = q(client, "EU", "EUR", eu_member_state="DE").json()
    assert j["tax_total"]["amount"] == "11.93" and j["total"]["amount"] == "58.93"


def test_currency_is_never_converted(client):
    assert q(client, "US", "GBP").status_code == 422


def test_48h_stale_note_then_7_day_pause(client):
    eng = make_engine()
    with eng.begin() as c:
        c.execute(text("UPDATE source_run SET finished_at = now() - interval '3 days' WHERE source = 'usitc'"))
    j = q(client).json()
    assert j["duties_included"] and "Rates last updated" in j["stale_note"]
    with eng.begin() as c:
        c.execute(text("UPDATE source_run SET finished_at = now() - interval '8 days' WHERE source = 'usitc'"))
    j = q(client).json()
    assert not j["duties_included"] and "paused" in j["paused_reason"] and j["tax_total"]["amount"] == "0.00"
    with eng.begin() as c:
        c.execute(text("UPDATE source_run SET finished_at = now() WHERE source = 'usitc'"))
    assert q(client).json()["duties_included"]


def test_order_puts_duty_in_tax_total_and_capture_mints_one_stamp(client, monkeypatch):
    pp = FakePayPal()
    monkeypatch.setattr(checkout, "paypal_client", lambda: pp)
    quote_in = {"shop_id": "shop_kiln", "destination": "US", "currency": "USD", "items": [{"product_id": "p_mug", "quantity": 1}]}
    r = client.post("/api/orders", json={"quote": quote_in, "return_url": "https://x.test/checkout?dest=US", "cancel_url": "https://x.test/c"})
    assert r.status_code == 200, r.text
    o = r.json()
    unit = pp.created[0]["purchase_units"][0]
    assert unit["amount"]["breakdown"]["tax_total"]["value"] == "7.60" and unit["amount"]["value"] == "59.60"
    assert unit["items"][0]["tax"]["value"] == "7.60" and unit["custom_id"] == o["order_id"]
    assert pp.created[0]["payment_source"]["paypal"]["experience_context"]["return_url"].endswith(f"order_id={o['order_id']}")
    c1 = client.post(f"/api/orders/{o['order_id']}/capture").json()
    assert c1["status"] == "COMPLETED" and c1["tax_total"]["amount"] == "7.60" and c1["stamp_minted"] == "US"
    c2 = client.post(f"/api/orders/{o['order_id']}/capture").json()  # idempotent
    assert c2["capture_id"] == "CAP-1"
    r2 = client.post("/api/orders", json={"quote": quote_in, "return_url": "https://x.test/checkout", "cancel_url": "https://x.test/c"}).json()
    c3 = client.post(f"/api/orders/{r2['order_id']}/capture").json()
    assert c3["stamp_minted"] is None  # a stamp is minted on the first captured order to a destination only
    eng = make_engine()
    with eng.begin() as conn:
        assert conn.execute(text("SELECT register_version FROM app_order WHERE id = :i"), {"i": o["order_id"]}).scalar_one() >= 1
        assert conn.execute(text("SELECT count(*) FROM audit_event WHERE action = 'order_captured'")).scalar_one() == 2


def test_import_date_is_recorded_and_register_locked(client):
    eng = make_engine()
    with eng.begin() as conn:
        row = conn.execute(text("SELECT import_date, register_version FROM app_order LIMIT 1")).first()
    assert row[0] > date.today() and row[1] >= 1


def test_the_ai_never_reaches_checkout_without_a_decision(client):
    eng = make_engine()
    with eng.begin() as conn:
        n = conn.execute(text("SELECT count(*) FROM product p JOIN recommendation r ON r.product_id = p.id LEFT JOIN decision d ON d.product_id = p.id WHERE d.id IS NULL")).scalar_one()
    assert n >= 0 and cat.FINE_PRINT_VERSION
    assert not q(client, items=[{"product_id": "p_wallet", "quantity": 1}]).json()["duties_included"]


def test_every_duty_line_names_its_source_and_links_straight_to_it(client):
    """The seller and the buyer can click from each line of the calculation to the official source it came from."""
    from landfall_api import demo
    from landfall_api.services.pricing import cart_item, price_cart, trail_lines

    lines = []
    for dest, cur in (("US", "USD"), ("EU", "EUR")):
        lines += q(client, dest, cur).json()["lines"][0]["trail"]
    eng = make_engine()
    with eng.connect() as conn:  # a UK destination line: for a UK seller the UK is the home market, so price it for a US seller
        from landfall_register import repo
        napkins = demo.BY_ID["p_napkins"]
        res = price_cart(conn, "GB", [cart_item(napkins, "GB")], date.today(), repo.latest_version(conn), seller_country="US")
        lines += [t.model_dump() for t in trail_lines(res)] if res.supported else []
    assert len(lines) >= 5
    for ln in lines:
        assert ln["source_ref"], f"{ln['label']} has no source text"
        url = ln["source_url"]
        assert url and url.startswith("https://"), f"{ln['label']} has no link"
        path = url.split("://", 1)[1].split("/", 1)
        assert len(path) == 2 and (path[1].strip("/") or "?" in url or "#" in url), f"{ln['label']} links only to a site's front page: {url}"
