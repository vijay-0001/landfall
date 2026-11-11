"""The demo shop opens with the mug accepted. When the recommender asks the seller which national line fits (the two
independent picks disagree), the seeded demo seller answers with the demo mug line first, then accepts: a recorded
seller decision with its audit trail, never a mock."""
import json

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_register.db import make_engine
from sqlalchemy import text

CLASSIFY = {"reason": "stoneware mug", "hs6": "6912.00", "runner_up": None, "decisive_unknown": None, "origin_reason": "made in the studio",
            "origin": "GB", "signals": [{"kind": "listing_text", "text": "Thrown by hand in our Stoke studio", "points_to": "GB"}]}


class DisagreeingLLM:
    def complete(self, system, user, max_tokens=600):
        if "national tariff line" in system:
            if "Method: start from" in system:
                return json.dumps({"reason": "mug", "code": "6912.00.44.00", "runner_up": "6912.00.10.00", "decisive_unknown": "whether the stoneware is coarse-grained"})
            return json.dumps({"reason": "coarse stoneware", "code": "6912.00.10.00", "runner_up": "6912.00.44.00", "decisive_unknown": "whether the stoneware is coarse-grained"})
        return json.dumps(CLASSIFY)


@pytest.fixture(scope="module")
def client():
    with make_engine().begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    main.cat.llm_client = lambda: DisagreeingLLM()
    with TestClient(main.app) as c:
        yield c


def test_demo_mug_is_accepted_on_its_demo_line_even_when_the_recommender_asks(client):
    detail = client.get("/api/products/p_mug").json()
    assert any(q["id"] == "q_line" for q in detail["recommendation"]["questions"])  # the question really was asked
    assert detail["product"]["review_status"] == "accepted"
    assert detail["product"]["code"] == "6912.00.44.00"
    with make_engine().connect() as c:
        acts = {(r[0], r[1]) for r in c.execute(text("SELECT actor, action FROM audit_event WHERE entity_id = :i"), {"i": detail["recommendation"]["id"]})}
    assert ("seed:demo-shop", "answered") in acts


def test_a_write_is_committed_before_the_response_reaches_the_client():
    """FastAPI closes a yield dependency after the response is sent unless its scope is "function". A client that creates a
    product and recommends it right away (the add-product page) would race the commit. TestClient waits for the whole
    app, so the scope is asserted directly on every route that takes the connection."""
    from landfall_api.deps import get_conn

    def walk(dep):
        yield dep
        for sub in dep.dependencies:
            yield from walk(sub)

    seen = 0
    for route in main.app.routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        for d in walk(dependant):
            if d.call is get_conn:
                seen += 1
                assert d.scope == "function", f"{route.path} would commit after the response is sent"
    assert seen >= 15
