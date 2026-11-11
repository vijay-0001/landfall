"""Signed quotes. Landfall signs what it quoted (shop, currency, totals and the duty per item) with a key only Landfall holds: no PayPal credential is involved.

The merchant's server, which holds its own PayPal credentials, fetches the order the buyer approved and asks Landfall to verify that the order carries exactly the
duty that was quoted, before it captures. A mismatch means: do not capture. The token is a base64url JSON payload and an HMAC-SHA256 signature.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from decimal import Decimal

from ..config import env

TTL_SECONDS = 30 * 60
_process_key = secrets.token_bytes(32)  # used only when LANDFALL_SIGNING_KEY is not set: tokens then stop working at restart (fine for development)


def now() -> int:  # tests replace this to pin the clock
    return int(time.time())


def _key() -> bytes:
    k = env("LANDFALL_SIGNING_KEY")
    return k.encode("utf-8") if k else _process_key


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return body + "." + _b64(hmac.new(_key(), body.encode("ascii"), hashlib.sha256).digest())


def read(token: str) -> dict:
    """The payload of a genuine, unexpired token. Raises ValueError with a plain reason."""
    try:
        body, sig = token.split(".")
        good = hmac.compare_digest(_b64(hmac.new(_key(), body.encode("ascii"), hashlib.sha256).digest()), sig)
        payload = json.loads(_unb64(body))
    except (ValueError, TypeError, UnicodeError):
        raise ValueError("The quote token is not valid") from None
    if not good:
        raise ValueError("The quote token is not valid")
    if payload.get("exp", 0) < now():
        raise ValueError("The quote has expired: ask for a new quote")
    return payload


def make(shop_id: str, currency: str, destination: str, ship_to_country: str | None, item_total: str, shipping: str, tax_total: str, total: str,
         items: list[dict]) -> tuple[str, int]:
    """items: [{"sku": ..., "quantity": n, "tax": "line duty total"}]. Returns the token and its expiry (unix seconds)."""
    exp = now() + TTL_SECONDS
    payload = {"v": 1, "shop": shop_id, "cur": currency, "dest": destination, "to": ship_to_country, "items_total": item_total, "ship": shipping,
               "tax": tax_total, "total": total, "items": items, "exp": exp, "nonce": secrets.token_hex(4)}
    return sign(payload), exp


def _d(x) -> Decimal | None:
    try:
        return Decimal(str(x))
    except Exception:  # noqa: BLE001
        return None


def check_order(payload: dict, order: dict) -> list[str]:
    """Compare a PayPal order (as PayPal returns it) with the signed quote. Returns plain reasons; an empty list means it matches."""
    reasons: list[str] = []
    try:
        unit = order["purchase_units"][0]
        amount = unit["amount"]
        br = amount.get("breakdown") or {}
    except (KeyError, IndexError, TypeError):
        return ["The order has no purchase unit to check"]
    if amount.get("currency_code") != payload["cur"]:
        reasons.append(f"currency differs: quoted {payload['cur']}, order has {amount.get('currency_code')}")
    for label, got, want in (("total", (amount or {}).get("value"), payload["total"]), ("tax_total", (br.get("tax_total") or {}).get("value"), payload["tax"]),
                             ("item_total", (br.get("item_total") or {}).get("value"), payload["items_total"]), ("shipping", (br.get("shipping") or {}).get("value"), payload["ship"])):
        if _d(got) != _d(want):
            reasons.append(f"{label} differs: quoted {want}, order has {got}")
    per_sku: dict[str, Decimal] = {}
    for it in unit.get("items") or []:
        t, q = _d((it.get("tax") or {}).get("value")), _d(it.get("quantity"))
        if t is None or q is None:
            reasons.append("an item has no tax or quantity")
            continue
        per_sku[str(it.get("sku"))] = per_sku.get(str(it.get("sku")), Decimal("0")) + t * q
    for it in payload["items"]:
        got = per_sku.pop(str(it["sku"]), None)
        if got is None or got != Decimal(it["tax"]):
            reasons.append(f"duty on {it['sku']} differs: quoted {it['tax']}, order has {'none' if got is None else f'{got:.2f}'}")
    if per_sku:
        reasons.append("the order has items that were not quoted: " + ", ".join(sorted(per_sku)))
    return reasons
