"""If the recommender asks the demo mug's origin (weak evidence on an origin-specific list, T4), the demo seller answers Britain and the mug is accepted."""
import json

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_register.db import make_engine
from sqlalchemy import text


class WeakOriginLLM:
    def complete(self, system, user, max_tokens=600):
        if "national tariff line" in system:
            return json.dumps({"reason": "mug", "code": "6912.00.44.00", "runner_up": None, "decisive_unknown": None})
        return json.dumps({"reason": "stoneware mug", "hs6": "6912.00", "runner_up": None, "decisive_unknown": None, "origin_reason": "no clear sign", "origin": "GB", "signals": []})


@pytest.fixture(scope="module")
def client():
    with make_engine().begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    main.cat.llm_client = lambda: WeakOriginLLM()
    with TestClient(main.app) as c:
        yield c


def test_mug_is_accepted_after_the_demo_seller_answers_origin(client):
    detail = client.get("/api/products/p_mug").json()
    assert any(q["id"] == "q_origin" for q in detail["recommendation"]["questions"])  # the origin question really was asked
    assert detail["product"]["review_status"] == "accepted" and detail["product"]["origin"] == "GB"
    q = client.post("/api/quote", json={"shop_id": "shop_kiln", "destination": "US", "currency": "USD", "items": [{"product_id": "p_mug", "quantity": 1}]}).json()
    assert q["duties_included"] and q["total"]["amount"] == "59.60"
