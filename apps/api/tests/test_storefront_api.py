"""Storefront and multi-item checkout on the real register: any accepted product, quantity and ship-to country; one unpriced item never takes
the others down; receipt after capture. PayPal is faked at the client boundary; the recommender is faked (canned JSON)."""
import json

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_api.services import checkout
from landfall_paypal.client import PayPalError
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
        self.fail_capture = False

    def create_order(self, body, request_id):
        self.created.append(body)
        return {"id": f"PP-{next(FakePayPal.ids)}", "status": "PAYER_ACTION_REQUIRED", "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=PP"}]}

    def capture(self, paypal_order_id, request_id):
        if self.fail_capture:
            raise PayPalError(500, "capture refused")
        unit = self.created[-1]["purchase_units"][0]
        return {"status": "COMPLETED", "purchase_units": [{"amount": unit["amount"], "payments": {"captures": [{
            "id": "CAP-9", "status": "COMPLETED", "custom_id": unit["custom_id"],
            "seller_receivable_breakdown": {"gross_amount": unit["amount"], "paypal_fee": {"currency_code": "USD", "value": "2.00"}, "net_amount": unit["amount"]}}]}}]}


@pytest.fixture(scope="module")
def client():
    eng = make_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    main.cat.llm_client = lambda: FakeLLM()
    with TestClient(main.app) as c:
        yield c


def quote(client, items, dest="US", cur="USD", **kw):
    return client.post("/api/quote", json={"shop_id": "shop_kiln", "destination": dest, "currency": cur, "items": items, **kw})


def order_body(items, dest="US", cur="USD", **kw):
    return {"quote": {"shop_id": "shop_kiln", "destination": dest, "currency": cur, "items": items, **kw}, "return_url": "https://x.test/shop", "cancel_url": "https://x.test/cart"}


def test_the_storefront_lists_products_countries_and_whether_duties_are_included(client):
    j = client.get("/api/shop").json()
    by = {p["id"]: p for p in j["products"]}
    assert by["p_mug"]["duties_included"] and by["p_mug"]["origin"] == "GB" and by["p_mug"]["prices"]["USD"] == "38.00"
    assert not by["p_bowl"]["duties_included"] and "not accepted" in by["p_bowl"]["note"]
    codes = {c["country"] for c in j["countries"]}
    assert {"US", "GB", "DE", "GR", "FR", "IE"} <= codes and len([c for c in j["countries"] if c["destination"] == "EU"]) == 27


def test_quantity_three_prices_the_whole_line(client):
    j = quote(client, [{"product_id": "p_mug", "quantity": 3}]).json()
    assert j["duties_included"] and j["item_total"]["amount"] == "114.00" and j["tax_total"]["amount"] == "22.80"  # 20% of 114
    assert j["lines"][0]["duty_and_tax"]["amount"] == "22.80" and j["total"]["amount"] == "150.80"


def test_one_unpriced_product_does_not_take_the_priced_one_down(client):
    j = quote(client, [{"product_id": "p_mug", "quantity": 1}, {"product_id": "p_bowl", "quantity": 2}]).json()
    by = {ln["product_id"]: ln for ln in j["lines"]}
    assert by["p_mug"]["duties_included"] and by["p_mug"]["duty_and_tax"]["amount"] == "7.60"
    assert not by["p_bowl"]["duties_included"] and "not been reviewed" in by["p_bowl"]["unpriced_reason"]
    assert j["duties_included"] and j["tax_total"]["amount"] == "7.60"  # only the priced line carries duty


def test_the_same_product_twice_is_one_line(client):
    j = quote(client, [{"product_id": "p_mug", "quantity": 1}, {"product_id": "p_mug", "quantity": 1}]).json()
    assert len(j["lines"]) == 1 and j["lines"][0]["quantity"] == 2 and j["tax_total"]["amount"] == "15.20"


def test_a_ship_to_country_decides_destination_and_member_state(client):
    j = quote(client, [{"product_id": "p_mug", "quantity": 1}], dest="EU", cur="EUR", ship_to_country="FR").json()
    assert j["destination"] == "EU" and j["ship_to_label"] == "France"
    g = quote(client, [{"product_id": "p_mug", "quantity": 1}], dest="EU", cur="EUR", ship_to_country="GR").json()
    assert g["ship_to_label"] == "Greece" and g["tax_total"]["amount"] != j["tax_total"]["amount"]  # Greece is EL in the register and has its own VAT


@pytest.mark.parametrize("body", [
    {"items": []},
    {"items": [{"product_id": "p_mug", "quantity": 0}]},
    {"items": [{"product_id": "p_mug", "quantity": -3}]},
    {"items": [{"product_id": "p_mug", "quantity": 100}]},
    {"items": [{"product_id": "nope", "quantity": 1}]},
    {"items": [{"product_id": "p_mug", "quantity": 1}], "ship_to_country": "ZZ"},
    {"items": [{"product_id": "p_mug", "quantity": 1}], "ship_to_country": "' OR 1=1 --"},
])
def test_absurd_quotes_are_refused_plainly(client, body):
    r = client.post("/api/quote", json={"shop_id": "shop_kiln", "destination": "US", "currency": "USD", **body})
    assert r.status_code == 422 and r.json()["detail"]


def test_a_product_without_a_price_in_the_currency_says_so(client):
    r = client.post("/api/products", json={"title": "Pound-only mug", "description": "A plain stoneware mug for tea.", "prices": {"GBP": "10.00"}})
    q = quote(client, [{"product_id": r.json()["id"], "quantity": 1}])
    assert q.status_code == 422 and "not sold in USD" in q.json()["detail"]


def test_the_receipt_after_capture_shows_every_line_and_the_duty(client, monkeypatch):
    pp = FakePayPal()
    monkeypatch.setattr(checkout, "paypal_client", lambda: pp)
    o = client.post("/api/orders", json=order_body([{"product_id": "p_mug", "quantity": 2}, {"product_id": "p_bowl", "quantity": 1}])).json()
    unit = pp.created[0]["purchase_units"][0]
    assert unit["amount"]["breakdown"]["tax_total"]["value"] == "15.20"
    assert [(i["quantity"], i["tax"]["value"]) for i in unit["items"]] == [("2", "7.60"), ("1", "0.00")]  # per-unit duty on the priced line; the unpriced one carries none
    assert client.get(f"/api/orders/{o['order_id']}").json()["status"] == "CREATED"
    assert client.post(f"/api/orders/{o['order_id']}/capture").status_code == 200
    r = client.get(f"/api/orders/{o['order_id']}").json()
    assert r["status"] == "CAPTURED" and r["capture_id"] == "CAP-9" and len(r["lines"]) == 2 and r["tax_total"]["amount"] == "15.20"
    assert client.get("/api/orders/ord_missing").status_code == 404


def test_paypal_failing_to_create_leaves_no_order_row(client, monkeypatch):
    class Down:
        def create_order(self, body, request_id):
            raise PayPalError(500, "down")

    monkeypatch.setattr(checkout, "paypal_client", lambda: Down())
    with make_engine().connect() as c:
        before = c.execute(text("SELECT count(*) FROM app_order")).scalar_one()
    r = client.post("/api/orders", json=order_body([{"product_id": "p_mug", "quantity": 1}]))
    assert r.status_code == 502 and "PayPal could not create" in r.json()["detail"]
    with make_engine().connect() as c:
        assert c.execute(text("SELECT count(*) FROM app_order")).scalar_one() == before


def test_capture_failing_after_approval_can_be_retried(client, monkeypatch):
    pp = FakePayPal()
    monkeypatch.setattr(checkout, "paypal_client", lambda: pp)
    o = client.post("/api/orders", json=order_body([{"product_id": "p_mug", "quantity": 1}])).json()
    pp.fail_capture = True
    assert client.post(f"/api/orders/{o['order_id']}/capture").status_code == 502
    assert client.get(f"/api/orders/{o['order_id']}").json()["status"] == "CREATED"  # still open: nothing marked paid
    pp.fail_capture = False
    assert client.post(f"/api/orders/{o['order_id']}/capture").status_code == 200


def test_australia_prices_a_low_value_order_with_gst_only(client):
    j = quote(client, [{"product_id": "p_mug", "quantity": 1}], dest="AU", cur="AUD", ship_to_country="AU").json()
    assert j["destination"] == "AU" and j["currency"] == "AUD" and j["duties_included"]
    assert j["tax_total"]["amount"] == "7.70" and j["total"]["amount"] == "84.70"  # 58 + 19 shipping + 10% GST of 77


def test_goods_that_cannot_be_sold_are_blocked_in_the_shop_and_in_the_quote(client):
    p = client.post("/api/products", json={"title": "Uranium glass vase", "description": "Vintage uranium glass vase that glows green under UV light.", "prices": {"USD": "110.00"}}).json()
    assert client.post(f"/api/products/{p['id']}/recommend").status_code == 200
    shop = {x["id"]: x for x in client.get("/api/shop").json()["products"]}
    assert shop[p["id"]]["blocked"] and "radioactive" in shop[p["id"]]["note"]
    r = quote(client, [{"product_id": p["id"], "quantity": 1}])
    assert r.status_code == 422 and "cannot be sold" in r.json()["detail"] and "radioactive" in r.json()["detail"]
