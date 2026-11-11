"""Easyship public API, version 2024-09. Facts proven in spikes/d9_easyship (GATE_LOG D9, D9b):
 - a User-Agent header is required (Cloudflare error 1010 without it);
 - the 6-digit code is not enough: Easyship then picks its own default line (28% for 6912), so we send the full national code;
 - a DDP shipment is created with buy_label false; a label is never bought here (it would need paid billing).
"""
from __future__ import annotations

import re
from decimal import Decimal

import httpx

BASE = "https://public-api.easyship.com"
UA = "landfall-pay/0.1 (+https://example.invalid; hackathon demo, test mode)"


class ShippingError(RuntimeError):
    pass


class LabelPurchaseRefused(ShippingError):
    """Raised before any network call when a request would buy a label."""


class EasyshipClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None):
        self._http = http or httpx.Client(timeout=60)
        self._h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": UA, "Accept": "application/json"}

    def _post(self, path: str, body: dict) -> dict:
        ss = body.get("shipping_settings") or {}
        if ss.get("buy_label") or ss.get("buy_label_synchronous"):
            raise LabelPurchaseRefused("Landfall never buys a label")
        try:
            r = self._http.post(BASE + path, json=body, headers=self._h)
        except httpx.HTTPError as e:
            raise ShippingError(f"Easyship is not reachable: {e}") from e
        if r.status_code >= 400:
            raise ShippingError(f"Easyship said {r.status_code}: {r.text[:300]}")
        return r.json()

    def rates(self, body: dict) -> dict:
        return self._post("/2024-09/rates", body)

    def create_shipment(self, body: dict) -> dict:
        return self._post("/2024-09/shipments", body)


def _addr(a: dict) -> dict:
    return {k: v for k, v in a.items() if v is not None}


def _digits(code: str) -> str:
    return re.sub(r"\D", "", code)


def _items(lines: list[dict]) -> list[dict]:
    return [{"description": ln["title"], "category": "home_decor", "hs_code": ln["hs_code"], "origin_country_alpha2": ln["origin"], "declared_currency": ln["currency"],
             "declared_customs_value": float(ln["unit_price"]), "actual_weight": ln["weight_kg"], "quantity": ln["quantity"], "sku": ln["sku"]} for ln in lines]


def _parcel(lines: list[dict]) -> dict:
    weight = round(sum(ln["weight_kg"] * ln["quantity"] for ln in lines) + 0.2, 2)  # 0.2 kg of packaging
    return {"total_actual_weight": weight, "box": {"length": 20, "width": 15, "height": 12}, "items": _items(lines)}


def build_rates_request(origin: dict, destination: dict, lines: list[dict], hs_digits: int = 6) -> dict:
    """A DDP rate quote. `hs_digits=6` reproduces what a marketplace sends by default; Easyship then applies its own line."""
    cut = [{**ln, "hs_code": _digits(ln["hs_code"])[:hs_digits]} for ln in lines]
    return {"origin_address": _addr({k: origin[k] for k in ("country_alpha2", "postal_code", "city", "state", "line_1")}),
            "destination_address": _addr({k: destination[k] for k in ("country_alpha2", "postal_code", "city", "state", "line_1")}),
            "incoterms": "DDP", "parcels": [_parcel(cut)]}


def build_shipment_request(origin: dict, destination: dict, lines: list[dict], courier_service_id: str, currency: str) -> dict:
    """A DDP shipment with the full national code. buy_label is false, always."""
    full = [{**ln, "hs_code": _digits(ln["hs_code"])} for ln in lines]
    return {"incoterms": "DDP", "set_as_residential": True, "buyer_regulatory_identifiers": {},
            "origin_address": _addr(origin), "sender_address": _addr(origin), "destination_address": _addr(destination),
            "courier_settings": {"courier_service_id": courier_service_id, "apply_shipping_rules": False},
            "shipping_settings": {"units": {"weight": "kg", "dimensions": "cm"}, "output_currency": currency, "buy_label": False, "buy_label_synchronous": False,
                                  "printing_options": {"format": "pdf", "label": "4x6", "commercial_invoice": "A4", "packing_slip": "none"}},
            "parcels": [_parcel(full)]}


def duty_from_rate(rate: dict) -> dict:
    """The duty Easyship says it will collect, per line, from one rate. Money as strings."""
    lines = [{"hs_code_applied": d.get("hs_code_applied"), "base_rate": d.get("base_duty_rate"), "duty": f"{Decimal(str(d.get('line_item_total_duty', 0))):.2f}",
              "extra": [{"description": a.get("description"), "rate": a.get("rate")} for a in d.get("additional_rates", [])]}
             for d in rate.get("import_duty_details", [])]
    return {"duty": f"{Decimal(str(rate.get('import_duty_charge', 0))):.2f}", "tax": f"{Decimal(str(rate.get('import_tax_charge', 0))):.2f}",
            "ddp_handling_fee": f"{Decimal(str(rate.get('ddp_handling_fee', 0))):.2f}", "currency": rate.get("currency"), "lines": lines}


def parse_shipment(resp: dict, courier_service_id: str | None = None) -> dict:
    """What we keep of a created shipment. `label_state` must stay `not_created`; anything else is surfaced loudly."""
    sh = resp.get("shipment", resp)
    rates = sh.get("rates") or []
    rate = next((r for r in rates if (r.get("courier_service") or {}).get("id") == courier_service_id), rates[0] if rates else None)
    out = {"id": sh.get("easyship_shipment_id"), "incoterms": sh.get("incoterms"), "label_state": sh.get("label_state"),
           "courier": (sh.get("courier_service") or {}).get("name"), "shipment_state": sh.get("shipment_state"),
           "easyship_quote": duty_from_rate(rate) if rate else None}
    if out["label_state"] != "not_created":
        out["warning"] = f"Label state is {out['label_state']}: a label may have been created. Check the Easyship account."
    return out
