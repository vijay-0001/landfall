"""A public deployment (LANDFALL_DEMO_READONLY=1): a caller without an API key can read the sample shop but cannot change it, spend model
tokens, or approve rule proposals. With a key everything works as before. Nothing here reaches the internet."""
import json

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_register.db import make_engine
from sqlalchemy import text


class CountingLLM:
    calls = 0

    def complete(self, system, user, max_tokens=600):
        CountingLLM.calls += 1
        return json.dumps({"hs6": "6912.00", "reason": "mug", "origin": "GB", "origin_reason": "studio", "signals": []})


@pytest.fixture(scope="module")
def client():
    eng = make_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    main.cat.llm_client = lambda: CountingLLM()
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def public(monkeypatch):
    monkeypatch.setenv("LANDFALL_DEMO_READONLY", "1")
    CountingLLM.calls = 0


def test_a_keyless_visitor_can_read_everything(client, public):
    for path in ("/api/catalogue", "/api/radar", "/api/passport", "/api/coverage", "/api/health", "/api/ops/rules"):
        assert client.get(path).status_code == 200, path


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/products", {"title": "Anything at all", "description": "A long enough description", "prices": {"USD": "10.00"}}),
    ("post", "/api/products/p_mug/recommend", None),
    ("post", "/api/products/p_mug/assistant", {"question": "Why this code?"}),
    ("post", "/api/recommendations/rec_x/answer", {"question_id": "q", "option_id": "o"}),
    ("post", "/api/recommendations/rec_x/decision", {"action": "accept"}),
    ("post", "/api/products/bulk-accept", {"recommendation_ids": []}),
    ("post", "/api/radar/a_x/choice", {"choice": "absorb"}),
    ("post", "/api/ops/rules/r_x/approve", None),
    ("post", "/api/ops/rules/r_x/reject", None),
])
def test_a_keyless_visitor_cannot_change_anything_or_spend_tokens(client, public, method, path, body):
    r = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
    assert r.status_code == 403, (path, r.status_code, r.text)
    assert CountingLLM.calls == 0, "a refused call must never reach the model"


def test_the_refusal_is_in_plain_words(client, public):
    detail = client.post("/api/products/p_mug/recommend").json()["detail"]
    assert "read-only" in detail and "INSTALL.md" in detail


def test_a_bad_key_is_still_a_401_not_a_free_pass(client, public):
    r = client.post("/api/products/p_mug/recommend", headers={"Authorization": "Bearer lf_test_" + "0" * 48})
    assert r.status_code == 401


def test_the_switch_is_off_by_default_so_local_runs_and_tests_are_unchanged(client, monkeypatch):
    monkeypatch.delenv("LANDFALL_DEMO_READONLY", raising=False)
    r = client.post("/api/products/p_mug/recommend")
    assert r.status_code != 403
