"""Glue between the register and the duty engine. No model call anywhere in this module (HLD principle 2)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from landfall_engine import Result, price
from landfall_register import repo
from sqlalchemy import Connection

from .. import demo
from ..schemas import Money, TrailLine

# Origin groups the engine needs to expand a scope such as "EU" (27 member states, TEDB codes; Greece is EL).
EU27 = ["AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT",
        "NL", "PL", "PT", "RO", "SE", "SI", "SK"]
ORIGIN_ALIASES = {"GR": "EL"}


def money(amount: Decimal | str, currency: str) -> Money:
    return Money(amount=f"{Decimal(str(amount)):.2f}", currency=currency)  # type: ignore[arg-type]


def engine_input(dest: str, items: list[dict], on: date, shipping: str | None = None, state: str | None = None,
                 window: int = 5, seller_country: str = demo.SHOP["country"], ioss: bool = True) -> dict:
    cur = demo.DEST_CURRENCY[dest]
    d = {"destination": dest, "currency": cur, "seller_country": seller_country, "ioss_registered": ioss, "import_date": on.isoformat(),
         "shipping": shipping if shipping is not None else demo.SHIPPING[cur], "items": items, "change_window_days": window,
         "origin_groups": {"EU": EU27}}
    if dest == "EU":
        d["eu_member_state"] = state or demo.EU_DEFAULT_STATE
    return d


def price_cart(conn: Connection, dest: str, items: list[dict], on: date, version: int | None = None, **kw) -> Result:
    window = kw.get("window", 5)
    rows = repo.rows_for_pricing(conn, dest, on, version, window, codes=[i["code"] for i in items] or None)
    return price(engine_input(dest, items, on, **kw), rows)


def cart_item(product: dict, dest: str, origin: str | None = None, qty: int = 1) -> dict:
    cur = demo.DEST_CURRENCY[dest]
    return {"sku": product["id"], "code": product["codes"][dest], "origin": origin or product["origin"],
            "unit_price": product["prices"][cur], "quantity": qty}


def trail_lines(result: Result) -> list[TrailLine]:
    cur = result.currency
    out = []
    for t in result.trail:
        out.append(TrailLine(label=t.label, base=money(t.base, cur), rate=t.rate, amount=money(t.amount, cur),
                             source_ref=t.source_ref, source_url=t.source_url, row_id=int(t.row_id) if t.row_id and t.row_id.isdigit() else None))
    return out
