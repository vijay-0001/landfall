"""Scheduled feed sync: a new SKU is added and recommended, a price change keeps the decision, a wording change sends the product back to review, a SKU that
leaves the feed stops being sold. The feed fetch and the recommender are faked: no live internet and no model call."""
import copy
import json

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_api.services import merchants
from landfall_register.db import make_engine
from sqlalchemy import text

MUG = {"hs6": "6912.00", "reason": "stoneware mug", "origin": "GB", "origin_reason": "thrown in the studio",
       "signals": [{"kind": "listing_text", "text": "Thrown by hand in our Stoke studio", "points_to": "GB"}]}
URL = {"feed_url": "https://shop.example.test/products.json", "currency": "GBP"}
BASE = {"products": [
    {"id": 1, "title": "Hand-thrown stoneware mug", "body_html": "<p>A stoneware mug thrown by hand in our Stoke studio.</p>",
     "variants": [{"sku": "MUG-001", "title": "Default Title", "price": "30.00",
                   "presentment_prices": [{"price": {"amount": "38.00", "currency_code": "USD"}}, {"price": {"amount": "30.00", "currency_code": "GBP"}}]}]},
]}


class CountingLLM:
    calls = 0

    def complete(self, system, user, max_tokens=600):
        CountingLLM.calls += 1
        if "national tariff line" in system:
            return json.dumps({"code": "6912.00.44.00", "reason": "Mugs and other steins"})
        return json.dumps(MUG)


class Feed:
    data = copy.deepcopy(BASE)


@pytest.fixture(scope="module")
def client():
    eng = make_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    main.cat.llm_client = lambda: CountingLLM()
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(autouse=True)
def feed(monkeypatch):
    Feed.data = copy.deepcopy(BASE)
    CountingLLM.calls = 0
    monkeypatch.setattr(merchants, "fetch_feed", lambda url: Feed.data)


def shop(client, name):
    m = client.post("/api/merchants", json={"name": name, "country": "GB", "city": "Stoke-on-Trent"}).json()
    return {"Authorization": f"Bearer {m['api_key']}"}


def mug_variant(sku, title, body, usd="38.00"):
    return {"id": 9, "title": title, "body_html": body, "variants": [{"sku": sku, "title": "Default Title", "price": "30.00",
                                                                      "presentment_prices": [{"price": {"amount": usd, "currency_code": "USD"}}, {"price": {"amount": "30.00", "currency_code": "GBP"}}]}]}


def accept(client, h, sku):
    pid = next(p["id"] for p in client.get("/api/catalogue", headers=h).json()["products"] if p["sku"] == sku)
    d = client.post(f"/api/products/{pid}/recommend", headers=h).json()
    ok = client.post(f"/api/recommendations/{d['recommendation']['id']}/decision", headers=h, json={"action": "accepted", "fine_print_version": d["fine_print_version"]})
    assert ok.status_code == 200, ok.text
    return pid


def quote(client, h, sku="MUG-001"):
    return client.post("/api/quote", headers=h, json={"ship_to_country": "US", "items": [{"sku": sku, "quantity": 1}]})


def product(client, h, sku):
    return next(p for p in client.get("/api/catalogue", headers=h).json()["products"] if p["sku"] == sku)


def test_sync_needs_a_key_and_a_connected_feed(client):
    assert client.post("/api/products/sync").status_code == 401
    h = shop(client, "No Feed Shop")
    r = client.post("/api/products/sync", headers=h)
    assert r.status_code == 422 and "Connect a product feed first" in r.json()["detail"]


def test_a_new_sku_is_added_and_recommended_and_an_identical_listing_reuses_it_with_no_model_call(client):
    h = shop(client, "Grow Shop")
    client.post("/api/products/import", headers=h, json=URL)
    first = client.post("/api/products/sync", headers=h).json()
    assert (first["added"], first["changed"], first["removed"]) == (0, 0, 0) and first["last_synced_at"]
    Feed.data["products"].append(mug_variant("MUG-002", "Hand-thrown stoneware mug", "<p>A stoneware mug thrown by hand in our Stoke studio.</p>"))  # same words as MUG-001
    Feed.data["products"].append(mug_variant("MUG-003", "Hand-thrown stoneware mug, tall", "A tall stoneware mug thrown by hand in our Stoke studio, with a pulled handle."))
    accept(client, h, "MUG-001")
    one_product = CountingLLM.calls  # what the full pipeline costs for one product
    assert one_product > 0
    before = CountingLLM.calls
    r = client.post("/api/products/sync", headers=h).json()
    assert r["added"] == 2 and r["recommended"] == 2 and r["pending"] == 0
    calls = CountingLLM.calls - before
    assert calls == one_product, "MUG-002 reuses MUG-001's recommendation (no model call); only MUG-003 runs the pipeline"
    assert product(client, h, "MUG-002")["review_status"] == "not_reviewed"  # recommended, but nothing is priced duty-paid until the seller accepts
    assert quote(client, h, "MUG-002").json()["duties_included"] is False
    assert client.get("/api/merchants/me", headers=h).json()["last_synced_at"]


def test_a_price_change_refreshes_prices_and_keeps_the_decision(client):
    h = shop(client, "Price Shop")
    client.post("/api/products/import", headers=h, json=URL)
    accept(client, h, "MUG-001")
    assert quote(client, h).json()["total"]["amount"] == "59.60"
    Feed.data["products"][0]["variants"][0]["presentment_prices"][0]["price"]["amount"] = "40.00"
    r = client.post("/api/products/sync", headers=h).json()
    assert r["price_updated"] == 1 and r["changed"] == 0
    p = product(client, h, "MUG-001")
    assert p["review_status"] == "accepted" and p["listing_changed"] is False and p["prices"]["USD"] == "40.00"
    assert quote(client, h).json()["tax_total"]["amount"] == "8.00"  # 20% of 40.00: the earlier decision still applies


def test_a_changed_listing_sends_the_product_back_to_review_until_the_seller_decides_again(client):
    h = shop(client, "Wording Shop")
    client.post("/api/products/import", headers=h, json=URL)
    pid = accept(client, h, "MUG-001")
    Feed.data["products"][0]["body_html"] = "<p>A porcelain cup, not a mug, made in a factory abroad.</p>"
    r = client.post("/api/products/sync", headers=h).json()
    assert r["changed"] == 1 and r["recommended"] == 1
    p = product(client, h, "MUG-001")
    assert p["review_status"] == "not_reviewed" and p["listing_changed"] is True
    q = quote(client, h).json()
    assert q["duties_included"] is False
    assert "changed" in q["lines"][0]["unpriced_reason"] and "reviewed again" in q["lines"][0]["unpriced_reason"]
    again = client.post(f"/api/products/{pid}/recommend", headers=h).json()  # a fresh recommendation exists for the new wording
    assert "porcelain" in client.get(f"/api/products/{pid}", headers=h).json()["product"]["description"]
    ok = client.post(f"/api/recommendations/{again['recommendation']['id']}/decision", headers=h, json={"action": "accepted", "fine_print_version": again["fine_print_version"]})
    assert ok.status_code == 200
    p = product(client, h, "MUG-001")
    assert p["review_status"] == "accepted" and p["listing_changed"] is False and quote(client, h).json()["duties_included"] is True


def test_a_sku_that_leaves_the_feed_stops_being_sold_and_comes_back_when_it_returns(client):
    h = shop(client, "Gone Shop")
    client.post("/api/products/import", headers=h, json=URL)
    Feed.data["products"].append(mug_variant("MUG-009", "Cream jug", "A small cream jug, thrown by hand in our Stoke studio."))
    client.post("/api/products/sync", headers=h)
    accept(client, h, "MUG-009")
    assert quote(client, h, "MUG-009").status_code == 200
    Feed.data["products"].pop()  # MUG-009 is no longer in the feed
    r = client.post("/api/products/sync", headers=h).json()
    assert r["removed"] == 1
    q = quote(client, h, "MUG-009")
    assert q.status_code == 422 and "no longer sold" in q.json()["detail"]
    assert "MUG-009" not in {p["sku"] for p in client.get("/api/catalogue", headers=h).json()["products"]}
    assert quote(client, h, "MUG-001").status_code == 200  # the rest is untouched
    Feed.data["products"].append(mug_variant("MUG-009", "Cream jug", "A small cream jug, thrown by hand in our Stoke studio."))
    back = client.post("/api/products/sync", headers=h).json()
    assert back["restored"] == 1 and back["removed"] == 0
    assert quote(client, h, "MUG-009").status_code == 200  # same listing, so the seller's earlier decision still stands


def test_an_empty_or_broken_feed_changes_nothing(client):
    h = shop(client, "Outage Shop")
    client.post("/api/products/import", headers=h, json=URL)
    Feed.data = {"products": []}
    r = client.post("/api/products/sync", headers=h)
    assert r.status_code == 422 and "nothing was changed" in r.json()["detail"]
    assert len(client.get("/api/catalogue", headers=h).json()["products"]) == 1
    Feed.data = {"nope": 1}
    assert client.post("/api/products/sync", headers=h).status_code == 422


def test_the_nightly_job_syncs_every_connected_shop_and_one_bad_feed_does_not_block_the_rest(client):
    h1, h2 = shop(client, "Night One"), shop(client, "Night Two")
    client.post("/api/products/import", headers=h1, json={**URL, "feed_url": "https://down.example.test/products.json"})
    client.post("/api/products/import", headers=h2, json=URL)
    Feed.data["products"].append(mug_variant("MUG-100", "Nightly jug", "A jug thrown by hand in our Stoke studio, glazed in blue."))

    def fetch(url):
        if "down.example" in url:
            raise ValueError("the feed is down")
        return Feed.data

    out = merchants.sync_all(make_engine(), None, fetch)
    ours = [o for o in out if o["shop"] in (client.get("/api/merchants/me", headers=h1).json()["shop_id"], client.get("/api/merchants/me", headers=h2).json()["shop_id"])]
    assert sorted(o["ok"] for o in ours) == [False, True]
    assert any(o.get("added") == 1 for o in ours)
