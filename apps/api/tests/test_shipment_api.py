"""Shipment on capture: Easyship DDP shipment (never a label), the duty cross-check shown in ops, and failures that never undo a capture.

Easyship is replaced by a fake that returns the responses recorded in spikes/d9_easyship. No network.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_api.services import checkout, shipment
from landfall_register.db import make_engine
from landfall_shipping import ShippingError
from sqlalchemy import text

FIX = Path(__file__).resolve().parents[3] / "packages" / "shipping" / "tests" / "fixtures"
RATES = json.loads((FIX / "mug_gb_to_us.json").read_text(encoding="utf-8"))
SHIPMENT = json.loads((FIX / "shipment_create.json").read_text(encoding="utf-8"))
CLASSIFY = {"hs6": "6912.00", "reason": "stoneware mug", "origin": "GB", "origin_reason": "thrown in the studio",
            "signals": [{"kind": "listing_text", "text": "Thrown by hand in our Stoke studio", "points_to": "GB"}]}


class FakeLLM:
    def complete(self, system, user, max_tokens=600):
        if "national tariff line" in system:
            return json.dumps({"code": "6912.00.44.00", "reason": "Mugs and other steins"})
        return json.dumps(CLASSIFY)


_PP_IDS = iter(range(1, 10_000))


class FakePayPal:
    def __init__(self):
        self.created = []

    def create_order(self, body, request_id):
        self.created.append(body)
        return {"id": f"PP-{next(_PP_IDS)}", "status": "PAYER_ACTION_REQUIRED", "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=PP"}]}

    def capture(self, paypal_order_id, request_id):
        unit = self.created[-1]["purchase_units"][0]
        return {"status": "COMPLETED", "purchase_units": [{"amount": unit["amount"], "payments": {"captures": [{
            "id": "CAP-1", "status": "COMPLETED", "custom_id": unit["custom_id"],
            "seller_receivable_breakdown": {"gross_amount": unit["amount"], "paypal_fee": {"currency_code": "USD", "value": "2.62"}, "net_amount": unit["amount"]}}]}}]}


class FakeEasyship:
    def __init__(self, fail=False):
        self.rate_calls, self.ship_calls, self.fail = [], [], fail

    def rates(self, body):
        self.rate_calls.append(body)
        if self.fail:
            raise ShippingError("Easyship said 503: unavailable")
        return RATES

    def create_shipment(self, body):
        self.ship_calls.append(body)
        return SHIPMENT


@pytest.fixture(scope="module")
def client():
    eng = make_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    main.cat.llm_client = lambda: FakeLLM()
    with TestClient(main.app) as c:
        yield c


def place(client, monkeypatch, dest="US", cur="USD"):
    pp = FakePayPal()
    monkeypatch.setattr(checkout, "paypal_client", lambda: pp)
    body = {"quote": {"shop_id": "shop_kiln", "destination": dest, "currency": cur, "items": [{"product_id": "p_mug", "quantity": 1}]},
            "return_url": "https://x.test/checkout", "cancel_url": "https://x.test/c"}
    return client.post("/api/orders", json=body).json()["order_id"]


def test_capture_creates_a_ddp_shipment_with_the_full_code_and_records_the_cross_check(client, monkeypatch):
    es = FakeEasyship()
    monkeypatch.setattr(shipment, "easyship_client", lambda: es)
    oid = place(client, monkeypatch)
    cap = client.post(f"/api/orders/{oid}/capture").json()
    assert cap["status"] == "COMPLETED" and cap["shipment_id"] == "ESGB369020643"
    # what we asked Easyship: the default 6-digit quote (their usual line) and a DDP shipment with the national code, no label
    assert es.rate_calls[0]["parcels"][0]["items"][0]["hs_code"] == "691200" and es.rate_calls[0]["incoterms"] == "DDP"
    sh = es.ship_calls[0]
    assert sh["incoterms"] == "DDP" and sh["parcels"][0]["items"][0]["hs_code"] == "6912004400" and sh["parcels"][0]["items"][0]["declared_customs_value"] == 38.0
    assert sh["shipping_settings"]["buy_label"] is False and sh["origin_address"]["country_alpha2"] == "GB"
    with make_engine().connect() as c:
        rec = c.execute(text("SELECT shipment FROM app_order WHERE id = :i"), {"i": oid}).scalar_one()
        assert rec["status"] == "created" and rec["label_state"] == "not_created" and rec["incoterms"] == "DDP"
        assert rec["cross_check"] == {"our_duty": "7.60", "easyship_default_code_duty": "14.44", "easyship_our_code_duty": rec["cross_check"]["easyship_our_code_duty"],
                                      "difference": "6.84", "currency": "USD",
                                      "note": "Easyship's default 6-digit code priced the 28% line; Landfall used 6912.00.44.00."}
        assert c.execute(text("SELECT count(*) FROM audit_event WHERE action = 'shipment_created'")).scalar_one() == 1


def test_ops_shows_the_cross_check(client):
    cc = client.get("/api/ops/sync").json()["shipment_cross_check"]
    assert len(cc) == 1 and cc[0]["our_duty"] == {"amount": "7.60", "currency": "USD"}
    assert cc[0]["easyship_duty"] == {"amount": "14.44", "currency": "USD"} and cc[0]["difference"] == {"amount": "6.84", "currency": "USD"}
    assert "28%" in cc[0]["note"]


def test_capture_is_idempotent_and_does_not_create_a_second_shipment(client, monkeypatch):
    es = FakeEasyship()
    monkeypatch.setattr(shipment, "easyship_client", lambda: es)
    with make_engine().connect() as c:
        oid = c.execute(text("SELECT id FROM app_order WHERE status = 'CAPTURED' LIMIT 1")).scalar_one()
    again = client.post(f"/api/orders/{oid}/capture").json()
    assert again["shipment_id"] == "ESGB369020643" and es.ship_calls == [] and es.rate_calls == []


def test_easyship_failure_never_undoes_a_capture(client, monkeypatch):
    monkeypatch.setattr(shipment, "easyship_client", lambda: FakeEasyship(fail=True))
    oid = place(client, monkeypatch)
    r = client.post(f"/api/orders/{oid}/capture")
    assert r.status_code == 200 and r.json()["status"] == "COMPLETED" and r.json()["shipment_id"] is None
    with make_engine().connect() as c:
        rec = c.execute(text("SELECT shipment, status FROM app_order WHERE id = :i"), {"i": oid}).mappings().one()
        assert rec["status"] == "CAPTURED" and rec["shipment"]["status"] == "failed" and "503" in rec["shipment"]["error"]


def test_no_key_and_other_lanes_are_recorded_as_not_attempted(client, monkeypatch):
    oid = place(client, monkeypatch)  # the autouse fixture switched Easyship off
    client.post(f"/api/orders/{oid}/capture")
    es = FakeEasyship()
    monkeypatch.setattr(shipment, "easyship_client", lambda: es)
    eu = place(client, monkeypatch, "EU", "EUR")
    client.post(f"/api/orders/{eu}/capture")
    with make_engine().connect() as c:
        no_key = c.execute(text("SELECT shipment FROM app_order WHERE id = :i"), {"i": oid}).scalar_one()
        eu_rec = c.execute(text("SELECT shipment FROM app_order WHERE id = :i"), {"i": eu}).scalar_one()
    assert no_key["status"] == "not_attempted" and "EASYSHIP_API_KEY" in no_key["reason"]
    assert eu_rec["status"] == "not_attempted" and "UK to US" in eu_rec["reason"] and es.ship_calls == []
