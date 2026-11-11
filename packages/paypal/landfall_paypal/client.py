"""PayPal Orders v2 adapter. Duty and import tax go in amount.breakdown.tax_total and per-item tax.

Why: the Orders API has no duty field; tax shows on the buyer receipt (HLD ADR-04). Verified on a real sandbox
order (spikes/d1_paypal/fixtures). No currency conversion here: PayPal converts for the seller (ADR-05).
Sandbox only for the hackathon; webhooks are verified by signature before any state change.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from decimal import Decimal

import httpx

SANDBOX = "https://api-m.sandbox.paypal.com"
CENT = Decimal("0.01")


@dataclass
class OrderItem:
    name: str
    sku: str
    quantity: int
    unit_amount: Decimal
    tax_total: Decimal  # duty and import tax for the whole line, as a tax amount


def _money(currency: str, x: Decimal) -> dict:
    return {"currency_code": currency, "value": f"{x.quantize(CENT):.2f}"}


def build_purchase_unit(*, currency: str, items: list[OrderItem], shipping: Decimal, discount: Decimal = Decimal("0"),
                        custom_id: str | None = None, description: str | None = None, ship_to: dict | None = None) -> dict:
    """Pure: the PayPal purchase unit for a cart: amount (with its breakdown) and items. item_total + shipping + tax_total must equal the amount;
    tax per item sums to tax_total. A merchant with its own PayPal integration puts this into its own create-order call.

    PayPal wants a per-unit tax; where a line's duty does not divide evenly by quantity we send quantity 1 lines
    per unit with the remainder on the last unit, so the arithmetic is exact to the cent.
    """
    lines: list[dict] = []
    for it in items:
        if it.quantity == 1:
            units = [(it.unit_amount, it.tax_total)]
        else:
            per = (it.tax_total / it.quantity).quantize(CENT, rounding="ROUND_FLOOR")
            units = [(it.unit_amount, per)] * (it.quantity - 1)
            units.append((it.unit_amount, it.tax_total - per * (it.quantity - 1)))
        # collapse equal units back into one line to keep the receipt tidy
        grouped: list[list] = []
        for amt, tax in units:
            if grouped and grouped[-1][0] == amt and grouped[-1][1] == tax:
                grouped[-1][2] += 1
            else:
                grouped.append([amt, tax, 1])
        for amt, tax, qty in grouped:
            lines.append({"name": it.name, "sku": it.sku, "category": "PHYSICAL_GOODS", "quantity": str(qty),
                          "unit_amount": _money(currency, amt), "tax": _money(currency, tax)})
    item_total = sum((Decimal(x["unit_amount"]["value"]) * int(x["quantity"]) for x in lines), Decimal("0"))
    tax_total = sum((Decimal(x["tax"]["value"]) * int(x["quantity"]) for x in lines), Decimal("0"))
    total = item_total + shipping + tax_total - discount
    breakdown = {"item_total": _money(currency, item_total), "shipping": _money(currency, shipping), "tax_total": _money(currency, tax_total)}
    if discount:  # seller-funded: the duty is still declared in full in tax_total and per-item tax
        breakdown["discount"] = _money(currency, discount)
    unit: dict = {"amount": {"currency_code": currency, "value": f"{total:.2f}", "breakdown": breakdown}, "items": lines}
    if custom_id:
        unit["reference_id"] = custom_id
        unit["custom_id"] = custom_id
    if description:
        unit["description"] = description
    if ship_to:
        unit["shipping"] = ship_to
    return unit


def build_order_request(*, currency: str, items: list[OrderItem], shipping: Decimal, custom_id: str, description: str,
                        return_url: str, cancel_url: str, brand_name: str, ship_to: dict | None = None,
                        discount: Decimal = Decimal("0")) -> dict:
    """Pure: builds the create-order body around the purchase unit."""
    unit = build_purchase_unit(currency=currency, items=items, shipping=shipping, discount=discount, custom_id=custom_id, description=description, ship_to=ship_to)
    return {
        "intent": "CAPTURE",
        "purchase_units": [unit],
        "payment_source": {"paypal": {"experience_context": {
            "brand_name": brand_name, "shipping_preference": "SET_PROVIDED_ADDRESS" if ship_to else "GET_FROM_FILE",
            "user_action": "PAY_NOW", "return_url": return_url, "cancel_url": cancel_url}}},
    }


class PayPalError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"PayPal HTTP {status}: {body[:300]}")
        self.status = status


class PayPalClient:
    def __init__(self, client_id: str, client_secret: str, base: str = SANDBOX, http: httpx.Client | None = None):
        self._id, self._secret, self._base = client_id, client_secret, base
        self._http = http or httpx.Client(timeout=30)
        self._token: str | None = None

    def _auth(self) -> str:
        if self._token is None:
            basic = base64.b64encode(f"{self._id}:{self._secret}".encode()).decode()
            r = self._http.post(f"{self._base}/v1/oauth2/token", headers={"Authorization": f"Basic {basic}"},
                                data={"grant_type": "client_credentials"})
            if r.status_code != 200:
                raise PayPalError(r.status_code, r.text)
            self._token = r.json()["access_token"]
        return self._token

    def _call(self, method: str, path: str, body: dict | None = None, request_id: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self._auth()}", "Content-Type": "application/json", "Prefer": "return=representation"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        r = self._http.request(method, f"{self._base}{path}", headers=headers, json=body)
        if r.status_code >= 400:
            raise PayPalError(r.status_code, r.text)
        return r.json() if r.content else {}

    def create_order(self, body: dict, request_id: str) -> dict:
        return self._call("POST", "/v2/checkout/orders", body, request_id)

    def capture(self, paypal_order_id: str, request_id: str) -> dict:
        return self._call("POST", f"/v2/checkout/orders/{paypal_order_id}/capture", {}, request_id)

    def get_order(self, paypal_order_id: str) -> dict:
        return self._call("GET", f"/v2/checkout/orders/{paypal_order_id}")


def approve_url(order: dict) -> str:
    return next(link["href"] for link in order["links"] if link["rel"] in ("payer-action", "approve"))


def summarise_capture(cap: dict) -> dict:
    """Pull what Landfall stores from a capture response: ids, status, tax line, PayPal's fee on the full amount."""
    unit = cap["purchase_units"][0]
    c = unit["payments"]["captures"][0]
    rb = c.get("seller_receivable_breakdown", {})
    return {
        "capture_id": c["id"], "status": cap["status"], "capture_status": c["status"],
        "tax_total": unit["amount"]["breakdown"]["tax_total"], "gross": rb.get("gross_amount"),
        "paypal_fee": rb.get("paypal_fee"), "net": rb.get("net_amount"), "receivable": rb.get("receivable_amount"),
        "custom_id": c.get("custom_id"),
    }
