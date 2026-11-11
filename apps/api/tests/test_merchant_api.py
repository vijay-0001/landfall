"""Merchants: sign-up and a key, import from a store feed, quote and order by SKU with the key, and one merchant never sees another's data.
PayPal is faked at the client boundary, the recommender is faked (canned JSON), and the feed fetch is faked: no live internet."""
import json

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_api.services import checkout, merchants
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
        return {"id": f"PP-M{next(FakePayPal.ids)}", "status": "PAYER_ACTION_REQUIRED", "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=PP"}]}

    def capture(self, paypal_order_id, request_id):
        unit = self.created[-1]["purchase_units"][0]
        return {"status": "COMPLETED", "purchase_units": [{"amount": unit["amount"], "payments": {"captures": [{
            "id": "CAP-M", "status": "COMPLETED", "custom_id": unit["custom_id"],
            "seller_receivable_breakdown": {"gross_amount": unit["amount"], "paypal_fee": {"currency_code": "USD", "value": "2.00"}, "net_amount": unit["amount"]}}]}}]}


FEED = {"products": [
    {"id": 1, "title": "Hand-thrown stoneware mug", "body_html": "<p>A <b>stoneware</b> mug thrown by hand in our Stoke studio.</p>",
     "images": [{"src": "https://cdn.example.test/mug.jpg"}],
     "variants": [{"sku": "MUG-001", "title": "Default Title", "price": "30.00",
                   "presentment_prices": [{"price": {"amount": "38.00", "currency_code": "USD"}}, {"price": {"amount": "30.00", "currency_code": "GBP"}}]}]},
    {"id": 2, "title": "Linen napkins", "body_html": "Set of four linen napkins, hemmed by hand.",
     "variants": [{"sku": "NAP-S", "title": "Small", "price": "20.00"}, {"sku": "NAP-L", "title": "Large", "price": "28.00"}]},
    {"id": 3, "title": "No SKU thing", "body_html": "A product without any SKU at all in the feed.", "variants": [{"sku": "", "title": "Default Title", "price": "5.00"}]},
]}


@pytest.fixture(scope="module")
def client():
    eng = make_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    main.cat.llm_client = lambda: FakeLLM()
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(autouse=True)
def feed(monkeypatch):
    monkeypatch.setattr(merchants, "fetch_feed", lambda url: FEED)


def signup(client, name="Acme Pots", country="GB"):
    r = client.post("/api/merchants", json={"name": name, "country": country, "city": "Stoke-on-Trent"})
    assert r.status_code == 200, r.text
    return r.json()


def auth(m):
    return {"Authorization": f"Bearer {m['api_key']}"}


def accepted_product(client, m, title="Test stoneware mug"):
    p = client.post("/api/products", headers=auth(m), json={"title": title, "description": "A plain stoneware mug thrown by hand in our studio.",
                                                         "prices": {"USD": "38.00", "GBP": "30.00"}}).json()
    d = client.post(f"/api/products/{p['id']}/recommend", headers=auth(m)).json()
    client.post(f"/api/recommendations/{d['recommendation']['id']}/decision", headers=auth(m), json={"action": "accepted", "fine_print_version": d["fine_print_version"]})
    return p["id"]


def test_sign_up_gives_a_key_once_and_only_its_hash_is_stored(client):
    m = signup(client)
    assert m["api_key"].startswith("lf_test_") and len(m["api_key"]) >= 40 and m["shop_id"].startswith("shop_")
    me = client.get("/api/merchants/me", headers=auth(m)).json()
    assert me["name"] == "Acme Pots" and "api_key" not in me and me["api_key_prefix"] == m["api_key"][:12]
    with make_engine().connect() as c:
        stored = c.execute(text("SELECT api_key_hash FROM shop WHERE id = :i"), {"i": m["shop_id"]}).scalar_one()
    assert stored and m["api_key"] not in stored


def test_a_wrong_or_missing_key_is_refused(client):
    assert client.get("/api/merchants/me").status_code == 401
    assert client.get("/api/merchants/me", headers={"Authorization": "Bearer lf_test_nope"}).status_code == 401
    assert client.get("/api/catalogue", headers={"Authorization": "Bearer lf_test_nope"}).status_code == 401


@pytest.mark.parametrize("body", [{"name": "x", "country": "GB", "city": "Y"}, {"name": "Okay name", "country": "Britain", "city": "Y"},
                                  {"name": "Okay name", "country": "GB", "city": ""}, {"name": "<script>alert(1)</script>", "country": "GB", "city": "Y"}])
def test_sign_up_refuses_absurd_input(client, body):
    assert client.post("/api/merchants", json=body).status_code == 422


def test_import_creates_one_product_per_sku_with_the_feed_prices(client):
    m = signup(client, "Feed Shop")
    r = client.post("/api/products/import", headers=auth(m), json={"feed_url": "https://shop.example.test/products.json", "currency": "GBP"}).json()
    assert {p["sku"] for p in r["created"]} == {"MUG-001", "NAP-S", "NAP-L"}
    assert r["skipped"] == [{"title": "No SKU thing", "reason": "No SKU on the variant: Landfall needs one to match your checkout to the product"}]
    cat = client.get("/api/catalogue", headers=auth(m)).json()
    by = {p["sku"]: p for p in cat["products"]}
    assert by["MUG-001"]["prices"] == {"USD": "38.00", "GBP": "30.00"}  # presentment prices win over the single price
    assert by["NAP-S"]["prices"] == {"GBP": "20.00"} and by["NAP-S"]["title"] == "Linen napkins, Small"
    assert "<" not in by["MUG-001"]["description"]  # HTML in the feed is stripped to text
    assert cat["shop"]["name"] == "Feed Shop"


def test_importing_again_updates_prices_and_never_duplicates(client):
    m = signup(client, "Twice Shop")
    url = {"feed_url": "https://shop.example.test/products.json", "currency": "GBP"}
    first = client.post("/api/products/import", headers=auth(m), json=url).json()
    again = client.post("/api/products/import", headers=auth(m), json=url).json()
    assert len(first["created"]) == 3 and again["created"] == [] and len(again["updated"]) == 3
    assert len(client.get("/api/catalogue", headers=auth(m)).json()["products"]) == 3


@pytest.mark.parametrize("url", ["http://shop.example.test/products.json", "ftp://x.test/p.json", "https://localhost/products.json", "https://127.0.0.1/p.json",
                                 "https://169.254.169.254/latest/meta-data", "https://10.0.0.5/p.json", "https://[::1]/p.json", "not a url", "https://user:pw@shop.example.test/p.json"])
def test_the_feed_url_must_be_a_public_https_address(client, url):
    m = signup(client, "Url Shop")
    r = client.post("/api/products/import", headers=auth(m), json={"feed_url": url, "currency": "GBP"})
    assert r.status_code == 422 and r.json()["detail"]


def test_a_feed_that_is_not_a_product_list_is_refused_plainly(client, monkeypatch):
    m = signup(client, "Bad Feed Shop")
    monkeypatch.setattr(merchants, "fetch_feed", lambda url: {"hello": "world"})
    r = client.post("/api/products/import", headers=auth(m), json={"feed_url": "https://shop.example.test/products.json", "currency": "GBP"})
    assert r.status_code == 422 and "products" in r.json()["detail"]


def test_import_needs_a_key(client):
    assert client.post("/api/products/import", json={"feed_url": "https://shop.example.test/products.json", "currency": "GBP"}).status_code == 401


def test_a_new_merchants_console_is_its_own_not_the_demo_shops(client):
    m = signup(client, "Empty Shop")
    assert client.get("/api/catalogue", headers=auth(m)).json()["products"] == []
    assert client.get("/api/shop", headers=auth(m)).json()["products"] == []
    assert client.get("/api/passport", headers=auth(m)).json()["stamps"] == []
    radar = client.get("/api/radar", headers=auth(m)).json()  # rule changes are register-wide; what they affect is the merchant's own products
    assert all(a["affected_product_ids"] == [] for a in radar)
    assert any(a["affected_product_ids"] for a in client.get("/api/radar").json())  # the demo shop has accepted products that some changes touch
    assert len(client.get("/api/catalogue").json()["products"]) > 0  # without a key the console shows the demo merchant, as before


def test_quote_by_sku_with_the_key_prices_the_accepted_product(client):
    m = signup(client, "Quote Shop")
    r = client.post("/api/products/import", headers=auth(m), json={"feed_url": "https://shop.example.test/products.json", "currency": "GBP"}).json()
    pid = {p["sku"]: p["id"] for p in r["created"]}["MUG-001"]
    d = client.post(f"/api/products/{pid}/recommend", headers=auth(m)).json()
    client.post(f"/api/recommendations/{d['recommendation']['id']}/decision", headers=auth(m), json={"action": "accepted", "fine_print_version": d["fine_print_version"]})
    q = client.post("/api/quote", headers=auth(m), json={"destination": "US", "currency": "USD", "ship_to_country": "US", "items": [{"sku": "MUG-001", "quantity": 1}]})
    assert q.status_code == 200, q.text
    j = q.json()
    assert j["tax_total"]["amount"] == "7.60" and j["total"]["amount"] == "59.60" and j["lines"][0]["product_id"] == pid and j["lines"][0]["sku"] == "MUG-001"


def test_quote_refuses_an_unknown_sku_and_an_item_with_both_or_neither_id(client):
    m = signup(client, "Sku Shop")
    base = {"destination": "US", "currency": "USD", "ship_to_country": "US"}
    assert client.post("/api/quote", headers=auth(m), json={**base, "items": [{"sku": "NOPE"}]}).status_code == 422
    assert client.post("/api/quote", headers=auth(m), json={**base, "items": [{}]}).status_code == 422
    assert client.post("/api/quote", headers=auth(m), json={**base, "items": [{"sku": "A", "product_id": "p_mug"}]}).status_code == 422


def test_one_merchant_cannot_quote_anothers_product(client):
    a, b = signup(client, "Owner Shop"), signup(client, "Other Shop")
    pid = accepted_product(client, a)
    base = {"destination": "US", "currency": "USD", "ship_to_country": "US"}
    assert client.post("/api/quote", headers=auth(a), json={**base, "items": [{"product_id": pid}]}).status_code == 200
    assert client.post("/api/quote", headers=auth(b), json={**base, "items": [{"product_id": pid}]}).status_code == 422
    assert client.get(f"/api/products/{pid}", headers=auth(b)).status_code == 404


def test_the_order_is_the_keyed_merchants_and_only_they_can_capture_it(client, monkeypatch):
    pp = FakePayPal()
    monkeypatch.setattr(checkout, "paypal_client", lambda: pp)
    a, b = signup(client, "Seller A"), signup(client, "Seller B")
    pid = accepted_product(client, a)
    body = {"quote": {"destination": "US", "currency": "USD", "ship_to_country": "US", "items": [{"product_id": pid, "quantity": 1}]},
            "return_url": "https://merchant.example.test/return", "cancel_url": "https://merchant.example.test/cancel"}
    o = client.post("/api/orders", headers=auth(a), json=body)
    assert o.status_code == 200, o.text
    unit = pp.created[0]["purchase_units"][0]
    assert unit["amount"]["breakdown"]["tax_total"]["value"] == "7.60" and "Seller A" in unit["description"]
    oid = o.json()["order_id"]
    assert client.post(f"/api/orders/{oid}/capture", headers=auth(b)).status_code == 404  # not B's order: it does not even exist for B
    assert client.get(f"/api/orders/{oid}", headers=auth(b)).status_code == 404
    assert client.post(f"/api/orders/{oid}/capture", headers=auth(a)).status_code == 200
    assert client.get(f"/api/orders/{oid}", headers=auth(a)).json()["status"] == "CAPTURED"
    assert client.get("/api/passport", headers=auth(a)).json()["stamps"][0]["destination"] == "US"  # the stamp belongs to the merchant that sold
    assert client.get("/api/passport", headers=auth(b)).json()["stamps"] == []


def test_the_demo_shop_still_works_without_a_key(client):
    assert client.get("/api/shop").json()["shop"]["id"] == "shop_kiln"


def test_the_order_answer_shows_where_the_duty_lands_in_the_paypal_order(client, monkeypatch):
    monkeypatch.setattr(checkout, "paypal_client", lambda: FakePayPal())
    m = signup(client, "Shows Duty Shop")
    pid = accepted_product(client, m)
    body = {"quote": {"destination": "US", "currency": "USD", "ship_to_country": "US", "items": [{"product_id": pid, "quantity": 3}]},
            "return_url": "https://merchant.example.test/return", "cancel_url": "https://merchant.example.test/cancel"}
    j = client.post("/api/orders", headers=auth(m), json=body).json()
    unit = j["paypal_purchase_unit"]
    assert unit["amount"]["breakdown"]["tax_total"] == {"currency_code": "USD", "value": "22.80"}
    assert unit["items"][0]["tax"]["value"] == "7.60" and unit["items"][0]["quantity"] == "3"


def test_sign_up_is_closed_unless_the_deployment_opens_it(client, monkeypatch):
    monkeypatch.delenv("LANDFALL_ALLOW_SIGNUP")
    r = client.post("/api/merchants", json={"name": "Closed Shop", "country": "GB", "city": "Stoke"})
    assert r.status_code == 403 and "closed" in r.json()["detail"]
    monkeypatch.setenv("LANDFALL_ALLOW_SIGNUP", "1")
    assert client.post("/api/merchants", json={"name": "Open Shop", "country": "GB", "city": "Stoke"}).status_code == 200
