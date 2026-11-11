"""The origin question's "Somewhere else" is a country list, not a dead end: the seller can name any country Landfall prices, or say the country is not priced yet."""
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


def asked(client):
    m = client.post("/api/merchants", json={"name": "Origin Shop", "country": "GB", "city": "Leeds"}).json()
    h = {"Authorization": f"Bearer {m['api_key']}"}
    p = client.post("/api/products", headers=h, json={"title": "Hand-thrown stoneware mug", "description": "A stoneware mug thrown by hand in our studio, 350 ml.", "prices": {"USD": "38.00", "GBP": "30.00", "EUR": "35.00"}}).json()
    d = client.post(f"/api/products/{p['id']}/recommend", headers=h).json()
    q = next(q for q in d["recommendation"]["questions"] if q["id"] == "q_origin")
    return h, d, q


def test_any_country_landfall_prices_can_be_named_even_if_it_was_not_one_of_the_options(client):
    h, d, q = asked(client)
    assert "origin_VN" not in [o["id"] for o in q["options"]]
    r = client.post(f"/api/recommendations/{d['recommendation']['id']}/answer", headers=h, json={"question_id": "q_origin", "option_id": "origin_VN"})
    assert r.status_code == 200, r.text
    rec = r.json()["recommendation"]
    assert rec["origin"] == "VN" and rec["band"] != "check"
    assert rec["pricing"] and any(x["supported"] for x in rec["pricing"]), "a named covered country must be priced"
    vn = next(o for o in next(x for x in rec["questions"] if x["id"] == "q_origin")["options"] if o["id"] == "origin_VN")
    assert vn["price_impact"] is not None, "the named country shows what it does to the price, like the other options"
    p = client.get(f"/api/products/{d['product']['id']}", headers=h).json()["product"]
    assert p["origin"] == "VN"


def test_somewhere_else_that_landfall_does_not_price_is_never_high_confidence_and_says_what_happens(client):
    h, d, _ = asked(client)
    r = client.post(f"/api/recommendations/{d['recommendation']['id']}/answer", headers=h, json={"question_id": "q_origin", "option_id": "origin_other"}).json()["recommendation"]
    assert r["origin"] == "other" and r["band"] == "check"
    assert "buyers check out normally" in r["headline"]
    assert client.get(f"/api/products/{d['product']['id']}", headers=h).json()["product"]["band"] == "check"


def test_an_unpriced_origin_really_checks_out_with_no_duty_added(client):
    """The headline promises "buyers check out normally, with no duty added": the quote must say the same, never a zero-duty line marked as priced."""
    h, d, _ = asked(client)
    rid = d["recommendation"]["id"]
    client.post(f"/api/recommendations/{rid}/answer", headers=h, json={"question_id": "q_origin", "option_id": "origin_other"})
    ok = client.post(f"/api/recommendations/{rid}/decision", headers=h, json={"action": "accepted", "fine_print_version": d["fine_print_version"]})
    assert ok.status_code == 200, ok.text
    q = client.post("/api/quote", headers=h, json={"items": [{"product_id": d["product"]["id"], "quantity": 1}], "ship_to_country": "US"})
    assert q.status_code == 200, q.text
    q = q.json()
    assert q["duties_included"] is False and q["tax_total"]["amount"] == "0.00"
    assert q["lines"][0]["duties_included"] is False and "does not cover this origin" in q["lines"][0]["unpriced_reason"]
    assert "may be due on delivery" in q["paused_reason"]


@pytest.mark.parametrize("bad", ["origin_CA", "origin_MX", "origin_ZZ", "origin_vn", "origin_", "origin_VNN", "x"])
def test_a_country_landfall_does_not_cover_or_a_made_up_option_is_refused(client, bad):
    h, d, _ = asked(client)
    r = client.post(f"/api/recommendations/{d['recommendation']['id']}/answer", headers=h, json={"question_id": "q_origin", "option_id": bad})
    assert r.status_code in (400, 422)


def test_override_can_say_the_country_is_not_priced_yet_and_that_product_is_never_high_confidence(client):
    h, d, _ = asked(client)
    rid = d["recommendation"]["id"]
    ok = client.post(f"/api/recommendations/{rid}/decision", headers=h, json={"action": "overridden", "code": "6912.00.44.00", "origin": "other", "fine_print_version": d["fine_print_version"]})
    assert ok.status_code == 200 and ok.json()["origin"] == "other", ok.text
    p = client.get(f"/api/products/{d['product']['id']}", headers=h).json()
    assert p["product"]["band"] == "check" and "buyers check out normally" in p["recommendation"]["headline"]
    q = client.post("/api/quote", headers=h, json={"items": [{"product_id": d["product"]["id"], "quantity": 1}], "ship_to_country": "US"}).json()
    assert q["duties_included"] is False


def test_override_to_a_country_outside_the_covered_list_is_also_never_high_confidence(client):
    h, d, _ = asked(client)
    rid = d["recommendation"]["id"]
    ok = client.post(f"/api/recommendations/{rid}/decision", headers=h, json={"action": "overridden", "code": "6912.00.44.00", "origin": "CA", "fine_print_version": d["fine_print_version"]})
    assert ok.status_code == 200, ok.text
    assert client.get(f"/api/products/{d['product']['id']}", headers=h).json()["product"]["band"] == "check"
