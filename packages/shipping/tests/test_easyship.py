"""Easyship adapter on the recorded D9 responses and a mock transport. No network. It must never buy a label."""
import json
from pathlib import Path

import httpx
import pytest
from landfall_shipping import (
    EasyshipClient,
    LabelPurchaseRefused,
    ShippingError,
    build_rates_request,
    build_shipment_request,
    duty_from_rate,
    parse_shipment,
)

FIX = Path(__file__).parent / "fixtures"
ORIGIN = {"line_1": "1 Potteries Way", "city": "Stoke-on-Trent", "state": "Staffordshire", "postal_code": "ST1 1AA", "country_alpha2": "GB",
          "company_name": "Kiln & Co.", "contact_name": "Kiln Co", "contact_phone": "+441782000000", "contact_email": "shop@example.com"}
DEST = {"line_1": "1 Main St", "city": "New York", "state": "NY", "postal_code": "10001", "country_alpha2": "US", "contact_name": "Sandbox Buyer",
        "contact_phone": "+12125550100", "contact_email": "buyer@example.com"}
MUG = [{"sku": "p_mug", "title": "Hand-thrown stoneware mug", "hs_code": "6912.00.44.00", "origin": "GB", "currency": "USD", "unit_price": "38.00",
        "weight_kg": 0.4, "quantity": 1}]


def test_rates_request_with_six_digits_reproduces_the_marketplace_default():
    b = build_rates_request(ORIGIN, DEST, MUG, hs_digits=6)
    assert b["incoterms"] == "DDP" and b["parcels"][0]["items"][0]["hs_code"] == "691200"
    assert b["parcels"][0]["total_actual_weight"] == 0.6  # 0.4 kg mug plus 0.2 kg packaging
    assert "contact_email" not in b["origin_address"]  # only what a quote needs


def test_shipment_request_is_ddp_with_the_full_national_code_and_never_buys_a_label():
    b = build_shipment_request(ORIGIN, DEST, MUG, "svc-1", "USD")
    assert b["incoterms"] == "DDP" and b["parcels"][0]["items"][0]["hs_code"] == "6912004400"
    assert b["shipping_settings"]["buy_label"] is False and b["shipping_settings"]["buy_label_synchronous"] is False
    assert b["parcels"][0]["items"][0]["declared_customs_value"] == 38.0 and b["courier_settings"]["courier_service_id"] == "svc-1"


def test_the_client_refuses_to_send_a_request_that_buys_a_label():
    called = []
    http = httpx.Client(transport=httpx.MockTransport(lambda r: called.append(r) or httpx.Response(200, json={})))
    body = build_shipment_request(ORIGIN, DEST, MUG, "svc-1", "USD")
    body["shipping_settings"]["buy_label"] = True
    with pytest.raises(LabelPurchaseRefused):
        EasyshipClient("k", http).create_shipment(body)
    body["shipping_settings"].update(buy_label=False, buy_label_synchronous=True)
    with pytest.raises(LabelPurchaseRefused):
        EasyshipClient("k", http).create_shipment(body)
    assert called == []  # nothing left the building


def test_every_call_carries_a_user_agent_and_bearer_key_and_errors_are_explained():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(403, text="error code: 1010") if len(seen) == 2 else httpx.Response(200, json={"rates": []})

    c = EasyshipClient("secret-key", httpx.Client(transport=httpx.MockTransport(handler)))
    c.rates({"x": 1})
    assert seen[0].headers["user-agent"].startswith("landfall-pay/") and seen[0].headers["authorization"] == "Bearer secret-key"
    assert seen[0].url.path == "/2024-09/rates"
    with pytest.raises(ShippingError, match="403"):
        c.rates({"x": 1})


def test_recorded_default_code_quote_shows_the_28_percent_line():
    rate = json.loads((FIX / "mug_gb_to_us.json").read_text(encoding="utf-8"))["rates"][0]
    d = duty_from_rate(rate)
    assert d["duty"] == "14.44" and d["currency"] == "USD"
    assert d["lines"][0]["base_rate"] == 0.28 and d["lines"][0]["extra"][0]["rate"] == 0.1  # 28% general plus 10% Section 301


def test_recorded_shipment_is_ddp_and_has_no_label():
    out = parse_shipment(json.loads((FIX / "shipment_create.json").read_text(encoding="utf-8")), "e4e0b246-3bc3-4263-96a3-c7ba812b2d95")
    assert out["id"] == "ESGB369020643" and out["incoterms"] == "DDP" and out["label_state"] == "not_created" and "warning" not in out
    assert out["courier"].startswith("FedEx") and out["easyship_quote"]["currency"] == "USD"


def test_an_unexpected_label_state_is_surfaced():
    resp = json.loads((FIX / "shipment_create.json").read_text(encoding="utf-8"))
    resp["shipment"]["label_state"] = "generated"
    assert "may have been created" in parse_shipment(resp)["warning"]
