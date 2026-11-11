"""A listing identical to an earlier one reuses that recommendation and gets its own copy. A listing never ends up with no recommendation
because someone else's identical listing came first; and when the AI step produces nothing, the seller is told and can retry."""
import json

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_register.db import make_engine
from sqlalchemy import text

GOOD = {"reason": "stoneware mug", "hs6": "6912.00", "runner_up": None, "decisive_unknown": None, "origin_reason": "made in the studio", "origin": "GB",
        "signals": [{"kind": "listing_text", "text": "Thrown in our Stoke studio", "points_to": "GB"}]}


class Counting:
    def __init__(self):
        self.calls = 0
        self.broken = False

    def complete(self, system, user, max_tokens=600):
        self.calls += 1
        if self.broken:
            raise TimeoutError("model unavailable")
        if "national tariff line" in system:
            return json.dumps({"reason": "mug", "code": "6912.00.44.00", "runner_up": None, "decisive_unknown": None})
        return json.dumps(GOOD)


@pytest.fixture(scope="module")
def env():
    with make_engine().begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    llm = Counting()
    main.cat.llm_client = lambda: llm
    with TestClient(main.app) as client:
        yield client, llm


BODY = {"title": "Same mug", "description": "A stoneware mug thrown in Stoke.", "prices": {"GBP": "30.00", "USD": "38.00", "EUR": "35.00"}}


def test_an_identical_listing_gets_its_own_copy_without_new_model_calls(env):
    client, llm = env
    p1 = client.post("/api/products", json=BODY).json()
    d1 = client.post(f"/api/products/{p1['id']}/recommend").json()
    assert d1["recommendation"]["code"].startswith("6912")
    calls = llm.calls
    p2 = client.post("/api/products", json=BODY).json()
    d2 = client.post(f"/api/products/{p2['id']}/recommend")
    assert d2.status_code == 200 and d2.json()["recommendation"] is not None
    assert d2.json()["recommendation"]["product_id"] == p2["id"] and d2.json()["recommendation"]["id"] != d1["recommendation"]["id"]
    assert llm.calls == calls  # reused, no model call
    assert client.get(f"/api/products/{p2['id']}").json()["product"]["band"] is not None
    with make_engine().connect() as c:
        assert c.execute(text("SELECT count(*) FROM audit_event WHERE action = 'recommendation_reused' AND entity_id = :i"), {"i": d2.json()["recommendation"]["id"]}).scalar_one() == 1


def test_a_reused_answer_is_not_shared_across_different_photos_or_past_a_refusal_rule(env):
    """What the AI read in a product's photos travels with its recommendation, and a refusal rule added later must apply to a copy as well."""
    client, llm = env
    body = {"title": "Pair of mugs", "description": "Two stoneware mugs thrown in Stoke.", "prices": {"GBP": "30.00", "USD": "38.00", "EUR": "35.00"}}
    p1 = client.post("/api/products", json={**body, "image_urls": ["https://shop.example/a.jpg"]}).json()
    client.post(f"/api/products/{p1['id']}/recommend")
    calls = llm.calls
    p2 = client.post("/api/products", json={**body, "image_urls": ["https://shop.example/b.jpg"]}).json()  # same words, other photo: a fresh recommendation
    client.post(f"/api/products/{p2['id']}/recommend")
    assert llm.calls > calls
    # a listing the refusal screen catches never takes a copy of an earlier answer
    risky = {"title": "Uranium glass vase", "description": "Vintage vase made of radioactive uranium glass.", "prices": {"GBP": "8.00", "USD": "10.00", "EUR": "9.00"}}
    a = client.post("/api/products", json=risky).json()
    ra = client.post(f"/api/products/{a['id']}/recommend").json()["recommendation"]
    assert ra["headline"].startswith("Landfall will not price this")
    b = client.post("/api/products", json=risky).json()
    rb = client.post(f"/api/products/{b['id']}/recommend").json()["recommendation"]
    assert rb["headline"].startswith("Landfall will not price this")


def test_when_the_ai_cannot_answer_the_seller_is_told_and_can_retry(env):
    client, llm = env
    llm.broken = True
    p = client.post("/api/products", json={**BODY, "title": "Odd mug", "description": "Something else entirely."}).json()
    r = client.post(f"/api/products/{p['id']}/recommend")
    assert r.status_code == 503 and "try again" in r.json()["detail"].lower()
    prod = client.get(f"/api/products/{p['id']}").json()
    assert prod["recommendation"] is None and prod["product"]["band"] is None
    llm.broken = False
    assert client.post(f"/api/products/{p['id']}/recommend").json()["recommendation"]["code"].startswith("6912")
