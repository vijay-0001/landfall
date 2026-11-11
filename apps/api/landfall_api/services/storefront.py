"""Buyer storefront: what a shopper sees, and the receipt after PayPal captures the payment. No model call anywhere in this module."""
from __future__ import annotations

from sqlalchemy import Connection, text

from .. import demo, destinations
from .. import schemas as s
from . import catalogue as cat
from .checkout import DDP_NOTE


def storefront(conn: Connection, shop: dict | None = None) -> s.Storefront:
    shop = shop or demo.SHOP
    rows = [dict(r) for r in conn.execute(text("SELECT * FROM product WHERE shop_id = :s AND active ORDER BY created_at, id"), {"s": shop["id"]}).mappings()]
    products = []
    for r in rows:
        dec = cat._latest_decision(conn, r["id"])  # noqa: SLF001
        rec = cat._latest_rec(conn, r["id"])  # noqa: SLF001
        if dec:
            included, note, origin = True, None, dec["origin"]
        else:
            included, origin = False, None
            paused = (rec or {}).get("payload", {}).get("decision", {}).get("paused_reason") if rec else None
            note = paused or ("Duties may be due on delivery: this listing changed and the seller has not reviewed the new wording yet." if cat.listing_changed(conn, r["id"])
                              else "Duties may be due on delivery: the seller has not accepted a customs recommendation for this product yet.")
        if not r["prices"]:
            continue
        blocked = bool(note and note.startswith("Landfall will not price this"))
        products.append(s.ShopProduct(id=r["id"], title=r["title"], description=r["description"], category=r["category"] or "Other goods", origin=origin,
                                      prices=r["prices"], photo_url=r["photo_url"], duties_included=included, note=note, blocked=blocked))
    return s.Storefront(shop=s.Shop(**{k: shop[k] for k in ("id", "name", "country", "city", "ioss_registered")}), countries=[s.ShipToCountry(**c) for c in destinations.countries()], products=products)


def receipt(conn: Connection, order_id: str, shop: dict | None = None) -> s.OrderReceipt:
    from landfall_register import repo

    o = conn.execute(text("SELECT * FROM app_order WHERE id = :i"), {"i": order_id}).mappings().first()
    if o is None or o["shop_id"] != (shop or demo.SHOP)["id"]:
        raise LookupError(order_id)
    o = dict(o)
    q = s.Quote.model_validate(o["quote"])
    lines = [s.ReceiptLine(title=ln.title, quantity=ln.quantity, unit_price=ln.unit_price, duty_and_tax=ln.duty_and_tax, duties_included=ln.duties_included,
                           unpriced_reason=ln.unpriced_reason) for ln in q.lines]
    return s.OrderReceipt(
        order_id=order_id, paypal_order_id=o["paypal_order_id"], status=o["status"], capture_id=o["capture_id"], ship_to_label=q.ship_to_label, lines=lines,
        item_total=q.item_total, shipping=q.shipping, tax_total=q.tax_total, seller_discount=q.seller_discount, total=q.total, duties_included=q.duties_included,
        register_version=repo.version_label(conn, o["register_version"]), rates_as_of=o["import_date"], shipment_id=(o["shipment"] or {}).get("id"),
        delivered_duty_paid_note=DDP_NOTE)
