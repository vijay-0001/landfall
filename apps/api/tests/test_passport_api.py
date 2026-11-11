"""Passport: stamps from captured duties-included orders, levels from products reviewed and duty-paid orders.

EF-02: points never depend on duty amount or override direction. The scoring function takes three counts and nothing else,
and the counts are taken so that neither of those can change them.
"""
import inspect
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_api.services import passport
from landfall_register.db import make_engine
from sqlalchemy import text

CLASSIFY = {"hs6": "6912.00", "reason": "stoneware mug", "origin": "GB", "origin_reason": "thrown in the studio",
            "signals": [{"kind": "listing_text", "text": "Thrown by hand in our Stoke studio", "points_to": "GB"}]}


class FakeLLM:
    def complete(self, system, user, max_tokens=600):
        if "national tariff line" in system:
            return json.dumps({"code": "6912.00.44.00", "reason": "Mugs and other steins"})
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


def order(oid: str, dest: str, duty: str, included: bool = True, status: str = "CAPTURED") -> None:
    cur = {"US": "USD", "GB": "GBP", "EU": "EUR"}[dest]
    with make_engine().begin() as c:
        v = c.execute(text("SELECT max(id) FROM register_version")).scalar_one()
        c.execute(text("""INSERT INTO app_order (id, shop_id, destination, currency, item_total, shipping, duty_tax, register_version, import_date, status, quote)
                          VALUES (:i, 'shop_kiln', :d, :c, 38, 14, :t, :v, :on, :s, CAST(:q AS jsonb))"""),
                  {"i": oid, "d": dest, "c": cur, "t": duty, "v": v, "on": date(2026, 11, 5), "s": status, "q": json.dumps({"duties_included": included, "lines": [{"product_id": "p_mug"}]})})


def stamp(dest: str, oid: str) -> None:
    with make_engine().begin() as c:
        c.execute(text("INSERT INTO stamp (shop_id, destination, first_order_id) VALUES ('shop_kiln', :d, :o) ON CONFLICT DO NOTHING"), {"d": dest, "o": oid})


# ---------------------------------------------------------------- the pure scoring function
def test_levels_come_from_three_counts_and_nothing_else():
    assert list(inspect.signature(passport.score).parameters) == ["products_reviewed", "stamps", "duty_paid_orders"]
    assert passport.score(0, 0, 0).level == 1
    assert passport.score(2, 1, 0).level == 1 and passport.score(3, 0, 0).level == 1  # needs both
    assert passport.score(3, 1, 0).level == 2 and passport.score(3, 1, 0).name == "Explorer"
    assert passport.score(5, 2, 9).level == 2 and passport.score(5, 2, 10).level == 3
    assert passport.score(10, 3, 50).level == 4 and passport.score(999, 3, 999).level == 4


def test_progress_and_requirements_point_at_the_next_level():
    s = passport.score(3, 1, 0)  # Explorer, working towards Navigator: 5 products, 2 stamps, 10 orders
    assert [r.text for r in s.requirements] == ["Review 5 products", "Earn 2 stamps", "Ship 10 duties-included orders"]
    assert [r.done for r in s.requirements] == [False, False, False]
    assert s.progress_pct == round((3 / 5 + 1 / 2 + 0) / 3 * 100)
    top = passport.score(10, 3, 50)
    assert top.progress_pct == 100 and top.requirements == []


def test_a_shared_passport_is_that_sellers_own_and_public_by_its_link_only(client):
    a = client.post("/api/merchants", json={"name": "Share Pots", "country": "GB", "city": "Leeds"}).json()
    mine = client.get("/api/passport", headers={"Authorization": f"Bearer {a['api_key']}"}).json()
    assert mine["share_url"] == f"/share/passport?shop={a['shop_id']}"
    shared = client.get(f"/api/passport/shared/{a['shop_id']}").json()  # no key: the link is the share
    assert "Share Pots" in shared["badge_headline"]
    assert "Share Pots" not in client.get("/api/passport").json()["badge_headline"]  # never the demo seller's badge for someone else
    assert client.get("/api/passport/shared/shop_nope").status_code == 404
    assert client.get("/api/passport/badge.png", params={"shop": "../x"}).status_code == 422


# ---------------------------------------------------------------- the endpoint on real rows
def test_fresh_passport_has_no_stamps_and_says_so(client):
    d = client.get("/api/passport").json()
    assert d["level"] == 1 and d["level_name"] == "Newcomer" and d["stamps"] == []
    assert {s["destination"] for s in d["next_stamps"]} >= {"US", "EU"} and "GB" not in {s["destination"] for s in d["next_stamps"]}  # the UK is home
    assert all(not s["earned"] for s in d["next_stamps"])
    assert d["badge_image_url"].startswith("/api/passport/badge.png?shop=") and d["share_url"].startswith("/share/passport?shop=")  # each seller shares their own passport
    assert "getting ready" in d["badge_headline"]


def test_stamps_and_counts_come_from_captured_duties_included_orders(client):
    order("o1", "US", "7.60")
    stamp("US", "o1")
    order("o2", "EU", "3.00")
    stamp("EU", "o2")
    order("o3", "US", "0.00", included=False)  # not duties-included: no count
    order("o4", "US", "7.60", status="CREATED")  # not captured: no count
    d = client.get("/api/passport").json()
    assert [s["destination"] for s in d["stamps"]] == ["US", "EU"] and all(s["earned"] and s["earned_on"] for s in d["stamps"])
    assert [s["product_count"] for s in d["stamps"]] == [1, 1]  # distinct products sold duty-paid to each destination
    assert "28 countries" in d["badge_headline"]  # United States (1) + European Union (27)
    assert [(r["text"], r["done"]) for r in d["requirements"]] == [("Review 3 products", False), ("Earn 1 stamp", True)]  # Explorer needs no orders
    assert {s["destination"] for s in d["next_stamps"]} == {"CA", "AU"}  # US and EU earned, the UK is home


def test_duty_amount_and_override_direction_cannot_move_the_level(client):
    before = client.get("/api/passport").json()
    order("o5", "US", "99.99")  # a huge duty
    order("o6", "US", "0.01")  # a tiny duty
    with make_engine().begin() as c:  # an override of the mug, with a different code, after the original accept
        rec = c.execute(text("SELECT recommendation_id, product_id FROM decision WHERE product_id = 'p_mug' LIMIT 1")).mappings().one()
        c.execute(text("""INSERT INTO decision (id, recommendation_id, product_id, action, code, origin, fine_print_version, user_id)
                          SELECT 'dec_override', :r, :p, 'overridden', '6912.00.48.90', 'CN', fine_print_version, user_id FROM decision WHERE product_id = :p LIMIT 1"""),
                  {"r": rec["recommendation_id"], "p": rec["product_id"]})
    after = client.get("/api/passport").json()
    assert after["level"] == before["level"]
    with make_engine().connect() as c:
        counts = passport.counts(c)
        assert counts["duty_paid_orders"] == 4  # o1, o2, o5, o6: each counted once, whatever its duty
        # the override added a second decision row for the same product, and the product is still counted once
        assert c.execute(text("SELECT count(*) FROM decision WHERE product_id = 'p_mug'")).scalar_one() == 2
        assert counts["products_reviewed"] == c.execute(text("SELECT count(DISTINCT product_id) FROM decision")).scalar_one()


def test_badge_png_comes_from_the_renderer_share_page(client, monkeypatch):
    seen = {}

    class R:
        status_code, content, text = 200, b"\x89PNG-fake", ""

    def fake_get(url, params=None, timeout=None):
        seen["url"], seen["params"] = url, params
        return R()

    monkeypatch.setattr(main.httpx, "get", fake_get)
    r = client.get("/api/passport/badge.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == b"\x89PNG-fake"
    assert seen["params"]["path"] == "/share/passport" and seen["url"].endswith("/render")
