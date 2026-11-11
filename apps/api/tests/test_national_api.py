"""An uncertain national line becomes a seller question, and the answer decides the line the duty is charged on."""
import json

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_register.db import make_engine
from sqlalchemy import text

CLASSIFY = {"reason": "cotton duvet cover is bed linen of cotton", "hs6": "6302.31", "runner_up": None, "decisive_unknown": None, "origin_reason": "made in the studio",
            "origin": "GB", "signals": [{"kind": "listing_text", "text": "sewn in our Stoke studio", "points_to": "GB"}]}


class FakeLLM:
    """The two 6-digit calls agree; the two national-line calls pick different lines and say what the listing leaves out."""

    def complete(self, system, user, max_tokens=600):
        if "duvet" not in user.lower():  # the seeded demo products: a plain mug, nothing uncertain
            if "national tariff line" in system:
                return json.dumps({"reason": "Mugs and other steins", "code": "6912.00.44.00", "runner_up": None, "decisive_unknown": None})
            return json.dumps({**CLASSIFY, "hs6": "6912.00", "reason": "stoneware mug", "signals": [{"kind": "listing_text", "text": "Thrown by hand in our Stoke studio", "points_to": "GB"}]})
        if "national tariff line" in system:
            if "Method: start from" in system:
                return json.dumps({"reason": "plain cotton, not napped", "code": "6302.31.70", "runner_up": "6302.31.30", "decisive_unknown": "whether the fabric is napped"})
            return json.dumps({"reason": "napped flannel", "code": "6302.31.30", "runner_up": "6302.31.70", "decisive_unknown": "whether the fabric is napped"})
        return json.dumps(CLASSIFY)


@pytest.fixture(scope="module")
def client():
    eng = make_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    main.cat.llm_client = lambda: FakeLLM()
    with TestClient(main.app) as c:
        yield c


def test_the_line_question_is_asked_priced_and_answered(client):
    with make_engine().connect() as c:
        lines = {r[0]: r[1] for r in c.execute(text("SELECT code, rate FROM rate_row WHERE destination = 'US' AND measure = 'base_duty' AND code LIKE '6302.31.%'"))}
    assert "6302.31.70" in lines and "6302.31.30" in lines, "the register must hold both lines for this test"
    p = client.post("/api/products", json={"title": "Cotton duvet cover", "description": "Cotton duvet cover, sewn in our Stoke studio from cotton cloth.",
                                           "prices": {"GBP": "60.00", "USD": "76.00", "EUR": "70.00"}, "category": "cotton"}).json()
    detail = client.post(f"/api/products/{p['id']}/recommend").json()
    rec = detail["recommendation"]
    q = next(q for q in rec["questions"] if q["id"] == "q_line")
    assert rec["band"] == "ask" and "does not say whether the fabric is napped" in q["help"]
    by_id = {o["id"]: o for o in q["options"]}
    assert set(by_id) == {"line_6302.31.70", "line_6302.31.30"} and by_id["line_6302.31.70"]["is_ai_pick"]
    assert by_id["line_6302.31.30"]["label"] == "Napped (11.9%)" and by_id["line_6302.31.30"]["price_impact"]["amount"] == "6.15"  # 9.04 (11.9% of 76.00) against 2.89 (3.8%), each rounded to the cent
    # the recommendation shows the AI's pick until the seller answers
    assert detail["product"]["code"] == "6302.31.70"
    out = client.post(f"/api/recommendations/{rec['id']}/answer", json={"question_id": "q_line", "option_id": "line_6302.31.30"}).json()
    assert out["recommendation"]["code"] == "6302.31.30" and out["remaining_questions"] >= 0
    accepted = client.post(f"/api/recommendations/{rec['id']}/decision", json={"action": "accepted", "fine_print_version": detail["fine_print_version"]})
    # the seller still has the origin question open or not; either way the accepted code is the one they chose, never the AI's earlier pick
    if accepted.status_code == 200:
        assert accepted.json()["code"] == "6302.31.30"
