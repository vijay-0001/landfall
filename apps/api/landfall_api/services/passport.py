"""Passport stamps and levels (HLD section 9, EF-02).

A stamp is minted at capture of the first duties-included order to a destination (see checkout.capture_order). Levels count
products reviewed and duty-paid orders. `score` takes three counts and nothing else: it has no input for the amount of duty or
for whether a product was accepted or overridden, so neither can change a level. `counts` is written the same way: a product
counts once however many decisions it has, and an order counts once whatever its duty.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import Connection, text

from .. import demo
from .. import schemas as s

# name, products reviewed, stamps, duty-paid orders needed to reach the level
LEVELS = [("Newcomer", 0, 0, 0), ("Explorer", 3, 1, 0), ("Navigator", 5, 2, 10), ("Captain", 10, 3, 50)]
STAMP_LABEL = {"US": "UNITED STATES", "GB": "UNITED KINGDOM", "EU": "EUROPEAN UNION", "AU": "AUSTRALIA"}
STAMP_NOTE = {"EU": "27 COUNTRIES · IOSS"}
STAMP_COUNTRIES = {"US": 1, "GB": 1, "EU": 27, "AU": 1}
LATER = [("CA", "CANADA")]  # not priced yet; every destination Landfall does price can be stamped


@dataclass
class Score:
    level: int
    name: str
    progress_pct: int
    requirements: list[s.LevelRequirement] = field(default_factory=list)


def score(products_reviewed: int, stamps: int, duty_paid_orders: int) -> Score:
    have = (products_reviewed, stamps, duty_paid_orders)
    level = max(i for i, (_, *need) in enumerate(LEVELS) if all(h >= n for h, n in zip(have, need, strict=True)))
    if level == len(LEVELS) - 1:
        return Score(level + 1, LEVELS[level][0], 100)
    _, *need = LEVELS[level + 1]
    texts = [f"Review {need[0]} products", f"Earn {need[1]} stamps" if need[1] != 1 else "Earn 1 stamp", f"Ship {need[2]} duties-included orders"]
    reqs = [s.LevelRequirement(text=t, done=h >= n) for t, h, n in zip(texts, have, need, strict=True) if n > 0]
    ratios = [min(1.0, h / n) for h, n in zip(have, need, strict=True) if n > 0]
    return Score(level + 1, LEVELS[level][0], round(sum(ratios) / len(ratios) * 100), reqs)


def counts(conn: Connection, shop_: dict | None = None) -> dict[str, int]:
    shop = {"s": (shop_ or demo.SHOP)["id"]}
    return {
        "products_reviewed": conn.execute(text("SELECT count(DISTINCT d.product_id) FROM decision d JOIN product p ON p.id = d.product_id WHERE p.shop_id = :s"), shop).scalar_one(),
        "stamps": conn.execute(text("SELECT count(*) FROM stamp WHERE shop_id = :s"), shop).scalar_one(),
        "duty_paid_orders": conn.execute(text("SELECT count(*) FROM app_order WHERE shop_id = :s AND status = 'CAPTURED' AND quote ->> 'duties_included' = 'true'"), shop).scalar_one()
        + conn.execute(text("SELECT count(DISTINCT entity_id) FROM audit_event WHERE action = 'order_verified' AND payload ->> 'shop' = :s"), shop).scalar_one(),
    }


def _stamp_products(conn: Connection, dest: str, shop_id: str = demo.SHOP["id"]) -> int:
    rows = conn.execute(text("SELECT quote FROM app_order WHERE shop_id = :s AND destination = :d AND status = 'CAPTURED' AND quote ->> 'duties_included' = 'true'"),
                        {"s": shop_id, "d": dest}).scalars()
    skus = {ln["product_id"] for q in rows for ln in q.get("lines", [])}
    seen = conn.execute(text("SELECT payload -> 'skus' FROM audit_event WHERE action = 'order_verified' AND payload ->> 'shop' = :s AND payload ->> 'dest' = :d"), {"s": shop_id, "d": dest}).scalars()
    return len(skus | {k for ks in seen for k in (ks or [])})


def record_verified(conn: Connection, shop: dict, token_payload: dict, paypal_order_id: str | None) -> bool:
    """The widget flow: Landfall never sees the capture, but it does see the order the buyer approved when the merchant's server verifies it against the signed quote.
    A verified order with duties included earns the destination's stamp (the merchant captures right after; a verified order that is never captured is the merchant's to explain).
    Returns True when this call earned a new stamp. Repeated verification of one order changes nothing."""
    if not paypal_order_id or Decimal(str(token_payload.get("tax", "0"))) <= 0:
        return False
    already = conn.execute(text("SELECT 1 FROM audit_event WHERE action = 'order_verified' AND entity_id = :o AND payload ->> 'shop' = :s LIMIT 1"), {"o": paypal_order_id, "s": shop["id"]}).first()
    if not already:
        conn.execute(text("INSERT INTO audit_event (actor, action, entity, entity_id, payload) VALUES (:a, 'order_verified', 'order', :o, CAST(:p AS jsonb))"),
                     {"a": f"merchant:{shop['id']}", "o": paypal_order_id, "p": json.dumps({"shop": shop["id"], "dest": token_payload["dest"], "skus": [i["sku"] for i in token_payload.get("items", []) if Decimal(i["tax"]) > 0]})})
    minted = conn.execute(text("INSERT INTO stamp (shop_id, destination, first_order_id) VALUES (:s, :d, :o) ON CONFLICT DO NOTHING"),
                          {"s": shop["id"], "d": token_payload["dest"], "o": paypal_order_id}).rowcount
    return bool(minted)


def passport(conn: Connection, shop: dict | None = None) -> s.Passport:
    shop = shop or demo.SHOP
    c = counts(conn, shop)
    sc = score(c["products_reviewed"], c["stamps"], c["duty_paid_orders"])
    earned = conn.execute(text("SELECT destination, earned_at::date AS d FROM stamp WHERE shop_id = :s ORDER BY earned_at, destination"), {"s": shop["id"]}).mappings().all()
    got = {r["destination"] for r in earned}
    stamps = [s.Stamp(destination=r["destination"], label=STAMP_LABEL[r["destination"]], earned_on=r["d"], product_count=_stamp_products(conn, r["destination"], shop["id"]),
                      note=STAMP_NOTE.get(r["destination"]), earned=True) for r in earned]
    nxt = [s.Stamp(destination=d, label=STAMP_LABEL[d], earned_on=None, note="Your first duties-included sale there earns it", earned=False)
           for d in ("US", "GB", "EU", "AU") if d not in got and d != shop["country"]]
    nxt += [s.Stamp(destination=code, label=name, earned_on=None, note="After the hackathon", earned=False) for code, name in LATER]
    countries = sum(STAMP_COUNTRIES[d] for d in got)
    name = shop["name"]
    headline = f"{name} ships duty-paid to {countries} {'country' if countries == 1 else 'countries'}" if countries else f"{name} is getting ready to ship duty-paid"
    return s.Passport(level=sc.level, level_name=sc.name, next_level_progress_pct=sc.progress_pct, stamps=stamps, next_stamps=nxt, requirements=sc.requirements,
                      badge_headline=headline, badge_subline="No surprise bills at the door for our customers.",
                      badge_image_url=f"/api/passport/badge.png?shop={shop['id']}", share_url=f"/share/passport?shop={shop['id']}")
