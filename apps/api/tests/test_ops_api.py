"""Ops: sync table from source_run, and the rule queue (approve writes a register row and Radar shows it; edit; reject; audit)."""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_api.services import radar
from landfall_register import repo
from landfall_register.db import make_engine
from landfall_rules import store
from landfall_rules.draft import Draft
from sqlalchemy import text

TODAY = date(2026, 11, 1)
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
    radar.today = lambda: TODAY
    with TestClient(main.app) as c:
        yield c


def q(value, quote=None):
    return {"value": value, "quote": quote if value else None}


def queue(doc: str, **fields) -> str:
    blank = {n: q(None) for n in ["destination", "code_pattern", "origin_scope", "measure", "rate", "valid_from", "valid_to"]}
    blank.update(fields)
    d = Draft(relevant=True, title="t", fields=blank)
    notice = {"document_number": doc, "title": f"Notice {doc}", "html_url": f"https://www.federalregister.gov/d/{doc}", "publication_date": "2026-10-30"}
    with make_engine().begin() as c:
        return store.insert_proposal(c, notice, "SUMMARY: test notice body", d)


FULL = dict(destination=q("US", "goods entered for consumption"), code_pattern=q("6912", "products of subheading 6912"),
            origin_scope=q("GB", "products of the United Kingdom"), measure=q("additional_duty", "an additional duty"),
            rate=q("5", "an additional 5 percent"), valid_from=q("2026-12-10", "on or after December 10, 2026"))


def rules(client):
    r = client.get("/api/ops/rules")
    assert r.status_code == 200, r.text
    return {x["notice_doc_number"]: x for x in r.json()}


def test_sync_table_has_each_source_with_health_from_source_run(client):
    r = client.get("/api/ops/sync").json()
    by = {s["id"]: s for s in r["sources"]}
    assert set(by) == {"usitc", "uk", "tedb", "federal_register"}
    assert all(s["health"] == "ok" and s["last_success_at"] for s in by.values())
    assert by["federal_register"]["publish"] == "needs_review" and by["usitc"]["publish"] == "automatic" and r["register_version"].startswith("r-")
    with make_engine().begin() as c:
        c.execute(text("UPDATE source_run SET finished_at = now() - interval '3 days' WHERE source = 'uk'"))
        c.execute(text("UPDATE source_run SET finished_at = now() - interval '8 days' WHERE source = 'tedb'"))
    by = {s["id"]: s for s in client.get("/api/ops/sync").json()["sources"]}
    assert by["uk"]["health"] == "stale_48h" and by["tedb"]["health"] == "paused_7d" and by["usitc"]["health"] == "ok"


def test_queue_lists_pending_with_quotes_blanks_and_affected_count(client):
    queue("T-1", **FULL)
    r = rules(client)["T-1"]
    assert r["status"] == "pending" and r["rate"] == {"value": "5", "quote": "an additional 5 percent"}
    assert r["valid_to"] == {"value": None, "quote": None} and r["model"] == "claude-haiku-5-5"
    assert r["products_affected"] == 1 and r["sellers_affected"] == 1  # the accepted UK-origin mug matches 6912 from GB
    assert "Fill" not in json.dumps(r) and r["notice_url"].endswith("/T-1")
    assert not any(x["notice_doc_number"].startswith("GOVUK") for x in client.get("/api/ops/rules").json())  # curated items are not queued


def test_approve_with_blank_required_fields_is_refused_and_lists_them(client):
    rid = queue("T-2", destination=q("US", "goods entered for consumption"), measure=q("additional_duty", "an additional duty"))
    r = client.post(f"/api/ops/rules/{rid}/approve")
    assert r.status_code == 422 and "Codes covered" in r.json()["detail"] and "Rate" in r.json()["detail"] and "Effective from" in r.json()["detail"]
    assert rules(client)["T-2"]["status"] == "pending"


def test_approve_writes_a_future_dated_row_and_radar_shows_it_with_days_and_impact(client):
    rid = rules(client)["T-1"]["id"]
    r = client.post(f"/api/ops/rules/{rid}/approve")
    assert r.status_code == 200 and r.json()["status"] == "approved"
    with make_engine().connect() as c:
        row = c.execute(text("SELECT * FROM rate_row WHERE source_url LIKE '%/T-1'")).mappings().one()
        assert (row["code"], row["origin_scope"], row["measure"], str(row["rate"]), row["valid_from"]) == ("6912", "GB", "additional_duty", "5.0000", date(2026, 12, 10))
        assert row["superseded_in_version"] is None
        acts = c.execute(text("SELECT action FROM audit_event WHERE entity_id = :i ORDER BY id"), {"i": rid}).scalars().all()
        assert acts == ["rule_proposed", "rule_approved"]
    alert = next(a for a in client.get("/api/radar").json() if a["source_url"].endswith("/T-1"))
    assert alert["status"] == "act" and alert["days_left"] == 39 and alert["impact_per_order"] == {"amount": "1.90", "currency": "USD"}
    assert alert["title"] == "Notice T-1" and alert["affected_product_ids"] == ["p_mug"]
    assert client.post(f"/api/ops/rules/{rid}/approve").status_code == 409  # decided once


def test_edit_fills_blanks_marks_them_edited_by_ops_and_publishes(client):
    rid = queue("T-3", destination=q("US", "goods entered for consumption"), measure=q("additional_duty", "an additional duty"),
                code_pattern=q("4202", "products of subheading 4202"), valid_from=q("2026-12-20", "on or after December 20, 2026"))
    r = client.post(f"/api/ops/rules/{rid}/edit", json={"origin_scope": "IN", "rate": "7.5"})
    assert r.status_code == 200 and r.json()["status"] == "edited"
    assert r.json()["rate"] == {"value": "7.5", "quote": "Edited by ops"} and r.json()["origin_scope"]["value"] == "IN"
    with make_engine().connect() as c:
        assert c.execute(text("SELECT rate FROM rate_row WHERE source_url LIKE '%/T-3'")).scalar_one() == 7.5
        assert "rule_edited" in c.execute(text("SELECT action FROM audit_event WHERE entity_id = :i"), {"i": rid}).scalars().all()


def test_a_rate_change_closes_the_old_row_and_old_versions_still_replay(client):
    with make_engine().connect() as c:
        before = repo.latest_version(c)
    rid = queue("T-4", destination=q("US", "x" * 20), code_pattern=q("*", "all products of the UK"), origin_scope=q("GB", "products of the United Kingdom"),
                measure=q("additional_duty", "an additional duty"), rate=q("15", "increased to 15 percent"), valid_from=q("2027-02-01", "on or after February 1, 2027"))
    assert client.post(f"/api/ops/rules/{rid}/approve").status_code == 200
    with make_engine().connect() as c:
        was = [r for r in repo.rows_visible(c, before, "US") if r["measure"] == "additional_duty" and r["origin_scope"] == "GB" and r["code"] == "*" and r["valid_to"] is None]
        assert [r["rate"] for r in was] == ["10"]  # as known before the approval: unchanged
        now = [r for r in repo.rows_visible(c, None, "US") if r["measure"] == "additional_duty" and r["origin_scope"] == "GB" and r["code"] == "*"]
        assert sorted((r["valid_from"], r["rate"], r["valid_to"]) for r in now if r["valid_from"] >= "2026-07-24") == [
            ("2026-07-24", "10", "2027-02-01"), ("2027-02-01", "15", None)]
    change = next(a for a in client.get("/api/radar").json() if a["effective_from"] == "2027-02-01" and a["destination"] == "US")
    assert change["impact_per_order"]["amount"] == "1.90"  # 5 more points on 38.00; the 10% before, 15% after


def test_reject_writes_no_row_and_is_audited(client):
    rid = queue("T-5", **FULL)
    r = client.post(f"/api/ops/rules/{rid}/reject")
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    with make_engine().connect() as c:
        assert c.execute(text("SELECT count(*) FROM rate_row WHERE source_url LIKE '%/T-5'")).scalar_one() == 0
        assert c.execute(text("SELECT count(*) FROM audit_event WHERE entity_id = :i AND action = 'rule_rejected'"), {"i": rid}).scalar_one() == 1
    assert client.post("/api/ops/rules/rp_nope/reject").status_code == 404
