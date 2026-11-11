"""The AI rate limit for public sites: at most N AI requests a minute and M per visitor per session window, counted per API key or per address.
Off by default. No model is reached: the limiter runs before anything else in the route, and a refused call never gets that far."""
import json

import pytest
from fastapi.testclient import TestClient
from landfall_api import deps, main
from landfall_api import schemas as s
from landfall_register.db import make_engine
from sqlalchemy import text

KEY_A = "Bearer lf_test_" + "a" * 48


class FakeLLM:
    def complete(self, system, user, max_tokens=600):
        return json.dumps({"hs6": "6912.00", "reason": "mug", "origin": "GB", "origin_reason": "studio", "signals": []})


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
def fresh(monkeypatch):
    # the assistant itself stops after 40 questions per product; these tests are about the limiter, so the assistant is a stub that costs nothing
    monkeypatch.setattr(main.assistant, "ask", lambda conn, llm, pid, q: s.AssistantReply(id=1, question=q, answer="ok", kind="explain", refused=False))
    deps._AI_CALLS.clear()
    for n in ("LANDFALL_AI_PER_MINUTE", "LANDFALL_AI_PER_SESSION", "LANDFALL_AI_SESSION_SECONDS", "LANDFALL_DEMO_READONLY", "LANDFALL_OPS_LOCKED"):
        monkeypatch.delenv(n, raising=False)


def ask(client, ip="1.1.1.1", **kw):
    return client.post("/api/products/p_mug/assistant", json={"question": "Why this code?"}, headers={"X-Forwarded-For": ip}, **kw)


def test_unset_means_no_limit(client):
    assert all(ask(client).status_code != 429 for _ in range(15))


def test_ten_a_minute_then_a_plain_429(client, monkeypatch):
    monkeypatch.setenv("LANDFALL_AI_PER_MINUTE", "10")
    codes = [ask(client).status_code for _ in range(12)]
    assert 429 not in codes[:10] and codes[10:] == [429, 429]
    r = ask(client)
    assert "at most 10 a minute" in r.json()["detail"] and int(r.headers["Retry-After"]) >= 1


def test_the_minute_window_slides(client, monkeypatch):
    monkeypatch.setenv("LANDFALL_AI_PER_MINUTE", "2")
    t = [1000.0]
    monkeypatch.setattr(deps.time, "time", lambda: t[0])
    assert ask(client).status_code != 429 and ask(client).status_code != 429
    assert ask(client).status_code == 429
    t[0] += 61
    assert ask(client).status_code != 429


def test_a_hundred_per_session_then_429(client, monkeypatch):
    monkeypatch.setenv("LANDFALL_AI_PER_SESSION", "100")
    codes = [ask(client).status_code for _ in range(102)]
    assert 429 not in codes[:100] and codes[100:] == [429, 429]
    assert "100 AI requests per visitor" in ask(client).json()["detail"]


def test_the_session_window_expires(client, monkeypatch):
    monkeypatch.setenv("LANDFALL_AI_PER_SESSION", "3")
    monkeypatch.setenv("LANDFALL_AI_SESSION_SECONDS", "3600")
    t = [5000.0]
    monkeypatch.setattr(deps.time, "time", lambda: t[0])
    [ask(client) for _ in range(3)]
    assert ask(client).status_code == 429
    t[0] += 3601
    assert ask(client).status_code != 429


def test_visitors_are_counted_separately(client, monkeypatch):
    monkeypatch.setenv("LANDFALL_AI_PER_MINUTE", "1")
    assert ask(client, ip="2.2.2.2").status_code != 429
    assert ask(client, ip="2.2.2.2").status_code == 429
    assert ask(client, ip="3.3.3.3").status_code != 429   # someone else is not affected


def test_the_first_forwarded_address_is_the_visitor(client, monkeypatch):
    monkeypatch.setenv("LANDFALL_AI_PER_MINUTE", "1")
    h = {"X-Forwarded-For": "4.4.4.4, 10.0.0.9"}
    assert client.post("/api/products/p_mug/assistant", json={"question": "Why?"}, headers=h).status_code != 429
    h2 = {"X-Forwarded-For": "4.4.4.4, 10.0.0.77"}
    assert client.post("/api/products/p_mug/assistant", json={"question": "Why?"}, headers=h2).status_code == 429


def test_a_refused_call_never_reaches_the_ai(client, monkeypatch):
    monkeypatch.setenv("LANDFALL_AI_PER_MINUTE", "1")
    calls = []
    monkeypatch.setattr(main.cat, "llm_client", lambda: calls.append(1) or FakeLLM())
    ask(client, ip="5.5.5.5")
    n = len(calls)
    assert ask(client, ip="5.5.5.5").status_code == 429
    assert len(calls) == n


def test_recommend_and_answer_and_sync_are_counted_too(client, monkeypatch):
    monkeypatch.setenv("LANDFALL_AI_PER_MINUTE", "1")
    client.post("/api/products/p_mug/recommend", headers={"X-Forwarded-For": "6.6.6.6"})
    for path in ("/api/products/p_mug/recommend", "/api/products/p_mug/assistant"):
        assert client.post(path, json={"question": "x"}, headers={"X-Forwarded-For": "6.6.6.6"}).status_code == 429, path
    r = client.post("/api/recommendations/rec_x/answer", json={"question_id": "q", "option_id": "o"}, headers={"X-Forwarded-For": "6.6.6.6"})
    assert r.status_code == 429


def test_ops_lock_alone_blocks_rule_approval_but_not_the_sample_shop(client, monkeypatch):
    monkeypatch.setenv("LANDFALL_OPS_LOCKED", "1")
    assert client.post("/api/ops/rules/r_x/approve").status_code == 403
    assert client.post("/api/ops/rules/r_x/reject").status_code == 403
    assert client.get("/api/ops/rules").status_code == 200
    assert client.post("/api/products/p_mug/assistant", json={"question": "Why?"}).status_code != 403
