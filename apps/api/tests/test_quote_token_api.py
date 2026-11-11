"""Signed quotes: the quote carries a PayPal-ready purchase unit and a signed token; verifying a PayPal order against it catches any change to the duty,
the totals, the currency or the items, an expired quote, another merchant's token and a forged one. No PayPal credential is used anywhere in this."""
import copy
import json

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_api.services import checkout, quote_token
from landfall_register.db import make_engine
from sqlalchemy import text

MUG = {"hs6": "6912.00", "reason": "stoneware mug", "origin": "GB", "origin_reason": "thrown in the studio",
       "signals": [{"kind": "listing_text", "text": "Thrown by hand in our Stoke studio", "points_to": "GB"}]}


class FakeLLM:
    def complete(self, system, user, max_tokens=600):
        if "national tariff line" in system:
            return json.dumps({"code": "6912.00.44.00", "reason": "Mugs and other steins"})
        return json.dumps(MUG)


class FakePayPal:
    ids = iter(range(1, 10_000))

    def __init__(self):
        self.created = []

    def create_order(self, body, request_id):
        self.created.append(body)
        return {"id": f"PP-Q{next(FakePayPal.ids)}", "status": "PAYER_ACTION_REQUIRED", "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=PP"}]}


@pytest.fixture(scope="module")
def client():
    with make_engine().begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    main.cat.llm_client = lambda: FakeLLM()
    with TestClient(main.app) as c:
        yield c


def merchant(client, name):
    m = client.post("/api/merchants", json={"name": name, "country": "GB", "city": "Stoke"}).json()
    h = {"Authorization": f"Bearer {m['api_key']}"}
    p = client.post("/api/products", headers=h, json={"title": "Test stoneware mug", "description": "A plain stoneware mug thrown by hand in our studio.", "prices": {"USD": "38.00"}}).json()
    d = client.post(f"/api/products/{p['id']}/recommend", headers=h).json()
    client.post(f"/api/recommendations/{d['recommendation']['id']}/decision", headers=h, json={"action": "accepted", "fine_print_version": d["fine_print_version"]})
    return h, p["id"]


def quote(client, h, pid, qty=3):
    return client.post("/api/quote", headers=h, json={"destination": "US", "currency": "USD", "ship_to_country": "US", "items": [{"product_id": pid, "quantity": qty}]}).json()


def as_paypal_order(q):
    """What PayPal would return for an order created from the quote's purchase unit."""
    return {"purchase_units": [copy.deepcopy(q["paypal_purchase_unit"])]}


def test_the_quote_carries_a_paypal_ready_purchase_unit_that_matches_the_order_landfall_would_send(client, monkeypatch):
    pp = FakePayPal()
    monkeypatch.setattr(checkout, "paypal_client", lambda: pp)
    h, pid = merchant(client, "Unit Shop")
    q = quote(client, h, pid)
    unit = q["paypal_purchase_unit"]
    assert unit["amount"]["value"] == "150.80" and unit["amount"]["breakdown"]["tax_total"] == {"currency_code": "USD", "value": "22.80"}
    assert unit["items"][0]["tax"]["value"] == "7.60" and unit["items"][0]["quantity"] == "3"
    body = {"quote": {"destination": "US", "currency": "USD", "ship_to_country": "US", "items": [{"product_id": pid, "quantity": 3}]}, "return_url": "https://m.test/r", "cancel_url": "https://m.test/c"}
    assert client.post("/api/orders", headers=h, json=body).status_code == 200
    sent = pp.created[0]["purchase_units"][0]
    assert sent["amount"] == unit["amount"] and sent["items"] == unit["items"]  # the same arithmetic, whichever way the order is made


def test_a_matching_order_verifies(client):
    h, pid = merchant(client, "Verify Shop")
    q = quote(client, h, pid)
    r = client.post("/api/quotes/verify", headers=h, json={"quote_token": q["quote_token"], "paypal_order": as_paypal_order(q)})
    assert r.status_code == 200 and r.json() == {"valid": True, "reasons": []}


def test_a_verified_order_with_duties_earns_the_passport_stamp_once_and_counts_as_a_duty_paid_order(client):
    """The widget flow: Landfall never sees the capture, but the merchant's verify call carries the approved order, so the Passport is not dead in the main flow."""
    h, pid = merchant(client, "Stamp Shop")
    assert client.get("/api/passport", headers=h).json()["stamps"] == []
    q = quote(client, h, pid)
    order = {**as_paypal_order(q), "id": "PP-ORDER-ONE"}
    for _ in range(2):  # verifying the same order again changes nothing
        assert client.post("/api/quotes/verify", headers=h, json={"quote_token": q["quote_token"], "paypal_order": order}).json()["valid"] is True
    p = client.get("/api/passport", headers=h).json()
    assert [x["destination"] for x in p["stamps"]] == ["US"] and p["stamps"][0]["product_count"] == 1
    second = quote(client, h, pid, qty=1)
    client.post("/api/quotes/verify", headers=h, json={"quote_token": second["quote_token"], "paypal_order": {**as_paypal_order(second), "id": "PP-ORDER-TWO"}})
    assert len(client.get("/api/passport", headers=h).json()["stamps"]) == 1  # one stamp per destination
    # a changed order earns nothing, and neither does an order with no duty
    h2, pid2 = merchant(client, "No Stamp Shop")
    q2 = quote(client, h2, pid2)
    bad = {**as_paypal_order(q2), "id": "PP-BAD"}
    bad["purchase_units"][0]["amount"]["value"] = "1.00"
    assert client.post("/api/quotes/verify", headers=h2, json={"quote_token": q2["quote_token"], "paypal_order": bad}).json()["valid"] is False
    assert client.get("/api/passport", headers=h2).json()["stamps"] == []


@pytest.mark.parametrize("name,change,expect", [
    ("a lower tax total", lambda u: u["amount"]["breakdown"]["tax_total"].update(value="1.00"), "tax_total differs"),
    ("a lower total", lambda u: u["amount"].update(value="100.00"), "total differs"),
    ("another currency", lambda u: u["amount"].update(currency_code="GBP"), "currency differs"),
    ("a lower item tax", lambda u: u["items"][0]["tax"].update(value="0.10"), "duty on"),
    ("an item that was not quoted", lambda u: u["items"].append({"name": "x", "sku": "EXTRA", "quantity": "1", "unit_amount": {"currency_code": "USD", "value": "1.00"}, "tax": {"currency_code": "USD", "value": "0.00"}}), "not quoted"),
    ("no items at all", lambda u: u.update(items=[]), "duty on"),
])
def test_a_changed_order_is_refused_with_a_plain_reason(client, name, change, expect):
    h, pid = merchant(client, f"Tamper {name}")
    q = quote(client, h, pid)
    order = as_paypal_order(q)
    change(order["purchase_units"][0])
    r = client.post("/api/quotes/verify", headers=h, json={"quote_token": q["quote_token"], "paypal_order": order}).json()
    assert r["valid"] is False and any(expect in x for x in r["reasons"]), r


def test_an_expired_quote_is_refused(client, monkeypatch):
    h, pid = merchant(client, "Expiry Shop")
    q = quote(client, h, pid)
    monkeypatch.setattr(quote_token, "now", lambda: quote_token.time.time() + quote_token.TTL_SECONDS + 5)
    r = client.post("/api/quotes/verify", headers=h, json={"quote_token": q["quote_token"], "paypal_order": as_paypal_order(q)})
    assert r.status_code == 422 and "expired" in r.json()["detail"]


def test_another_merchants_token_a_forged_token_and_a_missing_key_are_refused(client):
    ha, pa = merchant(client, "Owner Q Shop")
    hb, _ = merchant(client, "Other Q Shop")
    q = quote(client, ha, pa)
    order = as_paypal_order(q)
    assert client.post("/api/quotes/verify", headers=hb, json={"quote_token": q["quote_token"], "paypal_order": order}).status_code == 422
    body, sig = q["quote_token"].split(".")
    forged = body + "." + ("A" if sig[0] != "A" else "B") + sig[1:]
    assert client.post("/api/quotes/verify", headers=ha, json={"quote_token": forged, "paypal_order": order}).status_code == 422
    assert client.post("/api/quotes/verify", headers=ha, json={"quote_token": "garbage", "paypal_order": order}).status_code == 422
    assert client.post("/api/quotes/verify", json={"quote_token": q["quote_token"], "paypal_order": order}).status_code == 401


def test_a_signed_token_never_contains_a_secret(client):
    h, pid = merchant(client, "Plain Shop")
    q = quote(client, h, pid)
    payload = quote_token.read(q["quote_token"])
    assert set(payload) == {"v", "shop", "cur", "dest", "to", "items_total", "ship", "tax", "total", "items", "exp", "nonce"}
    assert q["quote_expires_at"] == payload["exp"]


def test_the_widget_quotes_with_a_publishable_key_and_nothing_else(client):
    m = client.post("/api/merchants", json={"name": "Widget Shop", "country": "GB", "city": "Stoke"}).json()
    assert m["publishable_key"].startswith("lf_pub_") and m["publishable_key"] != m["api_key"]
    h = {"Authorization": f"Bearer {m['api_key']}"}
    p = client.post("/api/products", headers=h, json={"title": "Widget stoneware mug", "description": "A plain stoneware mug thrown by hand in our studio.", "prices": {"USD": "38.00"}, "category": None}).json()
    d = client.post(f"/api/products/{p['id']}/recommend", headers=h).json()
    client.post(f"/api/recommendations/{d['recommendation']['id']}/decision", headers=h, json={"action": "accepted", "fine_print_version": d["fine_print_version"]})
    pub = {"X-Landfall-Key": m["publishable_key"]}
    q = client.post("/api/quote", headers=pub, json={"ship_to_country": "US", "items": [{"product_id": p["id"], "quantity": 1}]})  # destination and currency follow the country
    assert q.status_code == 200 and q.json()["tax_total"]["amount"] == "7.60" and q.json()["currency"] == "USD"
    # the publishable key can quote and nothing else
    assert client.post("/api/products/import", headers=pub, json={"feed_url": "https://x.test/p.json", "currency": "GBP"}).status_code == 401
    assert client.post("/api/orders", headers=pub, json={"quote": {"ship_to_country": "US", "items": [{"product_id": p["id"]}]}, "return_url": "https://m/r", "cancel_url": "https://m/c"}).status_code in (401, 422)
    assert client.get("/api/merchants/me", headers=pub).status_code == 401
    assert client.post("/api/quote", headers={"X-Landfall-Key": "lf_pub_nope"}, json={"ship_to_country": "US", "items": [{"product_id": p["id"]}]}).status_code == 401
    # a different currency than the country's is still refused
    assert client.post("/api/quote", headers=pub, json={"ship_to_country": "US", "currency": "GBP", "items": [{"product_id": p["id"]}]}).status_code == 422


def test_the_widget_script_is_served_and_the_browser_may_call_the_quote(client):
    r = client.get("/api/widget/landfall.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"] and "window.Landfall" in r.text
    pre = client.options("/api/quote", headers={"Origin": "https://shop.example.test", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-landfall-key,content-type"})
    assert pre.status_code == 200 and "x-landfall-key" in pre.headers["access-control-allow-headers"].lower()
