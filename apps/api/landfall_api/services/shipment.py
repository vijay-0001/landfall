"""Shipment on capture: an Easyship delivered-duty-paid shipment (test mode, label never bought) and a duty cross-check.

Capture has already happened at PayPal when this runs, so nothing here may fail a capture: every outcome, including a failure,
is recorded on the order and in the audit log. The cross-check compares what Easyship's default 6-digit code would have charged
with what Landfall quoted the buyer; the shipment itself carries Landfall's full national code.
"""
from __future__ import annotations

import json
from decimal import Decimal

from landfall_shipping import (
    EasyshipClient,
    build_rates_request,
    build_shipment_request,
    duty_from_rate,
    parse_shipment,
)
from sqlalchemy import Connection, text

from .. import demo
from .. import schemas as s
from ..config import env
from . import catalogue as cat
from .pricing import money


def easyship_client() -> EasyshipClient | None:
    key = env("EASYSHIP_API_KEY")
    return EasyshipClient(key) if key else None


def _lines(conn: Connection, quote: dict) -> list[dict]:
    out = []
    for ln in quote["lines"]:
        if not ln.get("duties_included"):
            continue
        prod = cat.get_prod(conn, ln["product_id"])
        dec = cat._latest_decision(conn, ln["product_id"])  # noqa: SLF001
        out.append({"sku": prod["id"], "title": prod["title"], "hs_code": dec["code"], "origin": dec["origin"], "currency": ln["unit_price"]["currency"],
                    "unit_price": ln["unit_price"]["amount"], "weight_kg": demo.WEIGHT_KG.get(prod["id"], demo.DEFAULT_WEIGHT_KG), "quantity": ln["quantity"]})
    return out


def _cross_check(order: dict, default_quote: dict, ours_quote: dict | None, code: str) -> dict:
    ours = Decimal(str(order["duty_tax"]))
    theirs = Decimal(default_quote["duty"])
    base = (default_quote["lines"][0]["base_rate"] if default_quote["lines"] else None)
    pct = f"{round(base * 100)}%" if base is not None else "its own"
    return {"our_duty": f"{ours:.2f}", "easyship_default_code_duty": f"{theirs:.2f}", "easyship_our_code_duty": ours_quote["duty"] if ours_quote else None,
            "difference": f"{theirs - ours:.2f}", "currency": default_quote["currency"],
            "note": f"Easyship's default 6-digit code priced the {pct} line; Landfall used {code}."}


def create_for_order(conn: Connection, order: dict, client: EasyshipClient | None) -> dict:
    """Never raises. Returns the record stored on the order."""
    if order["destination"] != "US":
        return {"status": "not_attempted", "reason": "Shipments are created for the UK to US lane, which is the one proven with Easyship; other lanes are not created in this demo."}
    if client is None:
        return {"status": "not_attempted", "reason": "EASYSHIP_API_KEY is not configured."}
    try:
        lines = _lines(conn, order["quote"])
        if not lines:
            return {"status": "not_attempted", "reason": "No duties-included lines on this order."}
        dest = demo.SANDBOX_BUYER_ADDRESS["US"]
        rates = client.rates(build_rates_request(demo.SELLER_ADDRESS, dest, lines, hs_digits=6)).get("rates") or []
        if not rates:
            return {"status": "failed", "error": "Easyship returned no rates for this parcel."}
        default_quote = duty_from_rate(rates[0])
        svc = rates[0]["courier_service"]["id"]
        made = parse_shipment(client.create_shipment(build_shipment_request(demo.SELLER_ADDRESS, dest, lines, svc, order["currency"])), svc)
        out = {"status": "created", "id": made["id"], "courier": made["courier"], "incoterms": made["incoterms"], "label_state": made["label_state"],
               "cross_check": _cross_check(order, default_quote, made["easyship_quote"], lines[0]["hs_code"])}
        if made.get("warning"):
            out["warning"] = made["warning"]
        return out
    except Exception as e:  # noqa: BLE001  the capture is done; record, never raise
        return {"status": "failed", "error": str(e)[:240]}


def record(conn: Connection, order_id: str, result: dict) -> None:
    conn.execute(text("UPDATE app_order SET shipment = CAST(:s AS jsonb) WHERE id = :i"), {"s": json.dumps(result), "i": order_id})
    cat.audit(conn, "system", f"shipment_{result['status']}", "order", order_id, {k: v for k, v in result.items() if k != "cross_check"})


def cross_checks(conn: Connection, limit: int = 10) -> list[s.CrossCheck]:
    rows = conn.execute(text("SELECT id, shipment FROM app_order WHERE shipment -> 'cross_check' IS NOT NULL ORDER BY created_at DESC LIMIT :n"), {"n": limit}).mappings()
    out = []
    for r in rows:
        c = r["shipment"]["cross_check"]
        cur = c["currency"]
        out.append(s.CrossCheck(order_id=r["id"], our_duty=money(c["our_duty"], cur), easyship_duty=money(c["easyship_default_code_duty"], cur),  # type: ignore[arg-type]
                                difference=money(c["difference"], cur), note=c["note"]))  # type: ignore[arg-type]
    return out
