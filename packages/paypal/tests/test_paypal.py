"""Contract tests on the recorded sandbox order (spikes/d1_paypal/fixtures). No network."""
import json
import pathlib
from decimal import Decimal

import httpx
import pytest
from landfall_paypal.client import (
    OrderItem,
    PayPalClient,
    approve_url,
    build_order_request,
    summarise_capture,
)

FIX = pathlib.Path(__file__).resolve().parents[3] / "spikes" / "d1_paypal" / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_request_has_the_same_shape_as_the_order_that_was_captured_in_the_sandbox():
    rec = load("create_order_request.json")["purchase_units"][0]
    body = build_order_request(
        currency="USD", items=[OrderItem("Hand-thrown stoneware mug", "KILN-MUG-01", 1, Decimal("38.00"), Decimal("7.45"))],
        shipping=Decimal("14.00"), custom_id="landfall-spike-001", description=rec["description"],
        return_url="https://example.com/r", cancel_url="https://example.com/c", brand_name="Kiln & Co.")
    unit = body["purchase_units"][0]
    assert unit["amount"] == rec["amount"]  # 59.45 with item_total, shipping, tax_total
    assert unit["items"][0]["tax"] == rec["items"][0]["tax"]
    assert body["intent"] == "CAPTURE"


def test_demo_anchor_mug_total_is_59_60():
    body = build_order_request(
        currency="USD", items=[OrderItem("Hand-thrown stoneware mug", "KILN-MUG-01", 1, Decimal("38.00"), Decimal("7.60"))],
        shipping=Decimal("14.00"), custom_id="o1", description="d", return_url="r", cancel_url="c", brand_name="Kiln & Co.")
    a = body["purchase_units"][0]["amount"]
    assert a["breakdown"]["tax_total"]["value"] == "7.60" and a["value"] == "59.60"


@pytest.mark.parametrize("qty,tax", [(1, "7.60"), (2, "15.20"), (3, "11.41"), (7, "0.05")])
def test_per_item_tax_sums_to_tax_total_exactly(qty, tax):
    body = build_order_request(
        currency="USD", items=[OrderItem("x", "S", qty, Decimal("10.00"), Decimal(tax))],
        shipping=Decimal("1.00"), custom_id="o", description="d", return_url="r", cancel_url="c", brand_name="b")
    unit = body["purchase_units"][0]
    per_item = sum(Decimal(i["tax"]["value"]) * int(i["quantity"]) for i in unit["items"])
    br = unit["amount"]["breakdown"]
    assert per_item == Decimal(br["tax_total"]["value"]) == Decimal(tax)
    assert Decimal(unit["amount"]["value"]) == Decimal(br["item_total"]["value"]) + Decimal(br["shipping"]["value"]) + Decimal(tax)


def test_recorded_responses_parse():
    assert approve_url(load("create_order_response.json")).startswith("https://www.sandbox.paypal.com")
    s = summarise_capture(load("capture_response.json"))
    assert s["status"] == "COMPLETED" and s["tax_total"]["value"] == "7.45"
    # PayPal's fee is charged on the full amount including the duty (verified 30 Oct): the seller pricing screen shows this
    assert s["paypal_fee"]["value"] == "2.62" and s["gross"]["value"] == "59.45"


def test_client_flow_against_a_mock_transport():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path))
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t"})
        if req.url.path.endswith("/capture"):
            return httpx.Response(201, json=load("capture_response.json"))
        return httpx.Response(201, json=load("create_order_response.json"))

    c = PayPalClient("id", "secret", http=httpx.Client(transport=httpx.MockTransport(handler)))
    o = c.create_order({"x": 1}, "req-1")
    c.capture(o["id"], "req-2")
    assert [p for _, p in calls][0] == "/v1/oauth2/token" and calls[-1][1].endswith("/capture")


@pytest.mark.live
def test_live_sandbox_create_order():  # opt-in: pytest -m live
    import os

    from dotenv import dotenv_values  # noqa: F401  (only for live runs)

    cfg = dotenv_values(pathlib.Path(__file__).resolve().parents[3] / ".env")
    c = PayPalClient(cfg["PAYPAL_CLIENT_ID"], cfg["PAYPAL_CLIENT_SECRET"])
    body = build_order_request(currency="USD", items=[OrderItem("m", "S", 1, Decimal("38.00"), Decimal("7.60"))], shipping=Decimal("14.00"),
                               custom_id=os.urandom(4).hex(), description="live", return_url="https://example.com/r",
                               cancel_url="https://example.com/c", brand_name="Kiln & Co.")
    assert c.create_order(body, os.urandom(8).hex())["status"] in ("PAYER_ACTION_REQUIRED", "CREATED")


def test_seller_funded_discount_leaves_tax_total_and_item_tax_unchanged():
    """Absorb it: the seller covers part of the duty. The duty is still declared in full (tax_total and per-item tax);
    the buyer's total drops by a separate discount line that the seller funds."""
    body = build_order_request(
        currency="USD", items=[OrderItem("Hand-thrown stoneware mug", "KILN-MUG-01", 1, Decimal("38.00"), Decimal("9.50"))],
        shipping=Decimal("14.00"), custom_id="o1", description="d", return_url="r", cancel_url="c", brand_name="Kiln & Co.", discount=Decimal("1.90"))
    unit = body["purchase_units"][0]
    br = unit["amount"]["breakdown"]
    assert br["tax_total"]["value"] == "9.50" and unit["items"][0]["tax"]["value"] == "9.50"
    assert br["discount"] == {"currency_code": "USD", "value": "1.90"}
    assert unit["amount"]["value"] == "59.60"  # 38.00 + 14.00 + 9.50 - 1.90


def test_no_discount_means_no_discount_key():
    body = build_order_request(
        currency="USD", items=[OrderItem("x", "S", 1, Decimal("10.00"), Decimal("1.00"))], shipping=Decimal("1.00"),
        custom_id="o", description="d", return_url="r", cancel_url="c", brand_name="b")
    assert "discount" not in body["purchase_units"][0]["amount"]["breakdown"]
