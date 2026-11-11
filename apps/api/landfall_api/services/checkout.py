"""Checkout: quote (register read, no model call), PayPal order with duty as tax, capture, locked register version, stamps."""
from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from landfall_paypal.client import (
    OrderItem,
    PayPalClient,
    PayPalError,
    approve_url,
    build_order_request,
    build_purchase_unit,
    summarise_capture,
)
from landfall_register import repo
from sqlalchemy import Connection, text

from .. import demo, destinations
from .. import schemas as s
from ..config import env
from . import catalogue as cat
from . import quote_token, shipment
from .health import destination_health
from .pricing import money, price_cart, trail_lines

TRANSIT_DAYS = {"US": 5, "GB": 3, "EU": 4, "AU": 6, "CA": 5}  # expected import date = today + transit; the engine straddles change dates
OLD_WAY = {"US": "Duty {tax} plus a carrier fee you only learn when the parcel arrives. Refuse it, and it goes back.",
           "GB": "VAT {tax} collected by the carrier at the door, often with a handling fee.",
           "EU": "Duty and VAT {tax} collected by the carrier at the door, often with a handling fee.",
           "AU": "Duty and GST {tax} collected by the carrier at the door, often with a handling fee.",
           "CA": "Duty, GST or HST {tax} collected by the carrier at the door, often with a brokerage fee."}
SYMBOL = {"USD": "$", "GBP": "£", "EUR": "€", "AUD": "A$", "CAD": "C$"}
DDP_NOTE = "Delivered duty paid. Customs is paid by the seller's shipping partner (simulated in this demo)."


def _eligible(conn: Connection, product_id: str) -> tuple[dict, dict | None]:
    prod = cat.get_prod(conn, product_id)
    return prod, cat._latest_decision(conn, product_id)  # noqa: SLF001


def _codes(conn: Connection, dest: str, decision: dict, version: int) -> str | None:
    if dest in ("US", "EU", "AU", "CA"):
        return decision["code"]
    return cat.gb_code(conn, version, decision["code"].replace(".", "")[:6])


def seller_absorbed(conn: Connection, dest: str, items: list[dict], on: date, version: int, state: str | None, shop: dict | None = None) -> Decimal:
    """Duty the seller chose to cover on Rule Radar (Absorb it): the sum of the absorbed steps.

    Each absorbed change in effect by the import date is priced as its own step: the duty on its effective date minus the duty on the
    day before, for the products it affects, with the same cart. A later rise the seller did not absorb is never included, so the
    buyer pays what they paid before an absorbed change, plus anything the seller did not choose to cover. The duty itself is still
    declared in full. Pass it on adds nothing."""
    total = Decimal("0.00")
    rows = conn.execute(text("SELECT scheduled FROM radar_choice WHERE shop_id = :s AND choice = 'absorb'"), {"s": (shop or demo.SHOP)["id"]}).scalars()
    for sch in rows:
        eff = date.fromisoformat(sch["effective_from"])
        if sch.get("destination") != dest or eff > on:
            continue
        mine = [i for i in items if i["sku"] in sch["products"]]
        if not mine:
            continue
        after = price_cart(conn, dest, mine, eff, version, state=state, window=0)
        prior = price_cart(conn, dest, mine, eff - timedelta(days=1), version, state=state, window=0)
        if not (after.supported and prior.supported):
            continue
        was = {ln.sku: ln.duty_and_tax for ln in prior.lines}
        total += sum((max(ln.duty_and_tax - was.get(ln.sku, ln.duty_and_tax), Decimal("0")) for ln in after.lines), Decimal("0.00"))
    return total


def _resolve_ship_to(body: s.QuoteIn) -> tuple[str, str | None, str | None]:
    """(destination, region, country label). A ship-to country wins over the destination field; the EU member state and the province follow from it."""
    if body.ship_to_country:
        c = destinations.resolve(body.ship_to_country)
        if c is None:
            raise ValueError(f"Landfall does not ship to {body.ship_to_country[:40]} yet")
        return c["destination"], body.eu_member_state or body.region or c["region"], c["name"]
    dest = body.destination
    if dest is None:
        raise ValueError("Give ship_to_country (or a destination)")
    return dest, body.eu_member_state or body.region, destinations.DEST_LABEL[dest]


def _resolve(conn: Connection, items: list[s.QuoteItemIn], shop: dict) -> list[s.QuoteItemIn]:
    """Name every item by Landfall's product id. A SKU is looked up in the merchant's own products; a product id must be the merchant's own."""
    out = []
    for i in items:
        if i.sku is not None:
            row = conn.execute(text("SELECT id FROM product WHERE shop_id = :s AND sku = :k"), {"s": shop["id"], "k": i.sku}).first()
            if row is None:
                raise ValueError(f"No product with SKU {i.sku} in this shop: import your catalogue first")
            out.append(s.QuoteItemIn(product_id=row[0], quantity=i.quantity))
        else:
            cat.owns_product(conn, i.product_id, shop)
            out.append(i)
    return out


def _merge(items: list[s.QuoteItemIn]) -> list[tuple[str, int]]:
    merged: dict[str, int] = {}
    for i in items:
        merged[i.product_id] = merged.get(i.product_id, 0) + i.quantity
    if any(q > 99 for q in merged.values()):
        raise ValueError("At most 99 of one product per order")
    return list(merged.items())


def _due(reason: str) -> str:
    """'Duties may be due on delivery: ...' with the reason read as a clause (a refusal that starts with its own sentence is kept as it is)."""
    return "Duties may be due on delivery. " + reason if reason.startswith("Landfall will not price") else "Duties may be due on delivery: " + reason[0].lower() + reason[1:]


def quote(conn: Connection, body: s.QuoteIn, shop: dict | None = None) -> s.Quote:
    shop = shop or demo.SHOP
    dest, state, ship_label = _resolve_ship_to(body)
    cur = destinations.DEST_CURRENCY[dest]
    if body.currency is not None and body.currency != cur:
        raise ValueError(f"Prices for {dest} are set in {cur}; Landfall never converts currency")
    version = repo.latest_version(conn)
    on = body.import_date or (date.today() + timedelta(days=TRANSIT_DAYS[dest]))
    health = destination_health(conn, dest)
    prods = []
    for pid, qty in _merge(_resolve(conn, body.items, shop)):
        prod, dec = _eligible(conn, pid)
        if not prod.get("active", True):
            raise ValueError(f"{prod['title']} is no longer sold: it has been removed from the shop's product feed")
        if cur not in prod["prices"]:
            raise ValueError(f"{prod['title']} is not sold in {cur} yet, so it cannot be shipped to {ship_label}")
        prods.append((prod, dec, qty))
    item_total = sum((Decimal(p["prices"][cur]) * q for p, _, q in prods), Decimal("0.00"))
    ship = Decimal(destinations.SHIPPING[cur])
    reasons: dict[str, str] = {}
    items: list[dict] = []
    for p, d, q in prods:
        if health.paused_reason:
            reasons[p["id"]] = health.paused_reason
        elif d is None:
            rec = cat._latest_rec(conn, p["id"])  # noqa: SLF001
            refusal = ((rec or {}).get("payload", {}).get("decision", {}) or {}).get("paused_reason") if rec else None
            if refusal and refusal.startswith("Landfall will not price this"):
                raise ValueError(f"{p['title']} cannot be sold through this checkout. {refusal}")
            reasons[p["id"]] = refusal or ("The listing changed after the seller's decision, so it has to be reviewed again." if cat.listing_changed(conn, p["id"])
                                           else "This product has not been reviewed by the seller yet.")
        else:
            code = _codes(conn, dest, d, version)
            if code is None:
                reasons[p["id"]] = "No priced line for this product in " + ship_label + " yet."
            else:
                items.append({"sku": p["id"], "code": code, "origin": d["origin"], "unit_price": p["prices"][cur], "quantity": q})
    seller = {"seller_country": shop["country"], "ioss": bool(shop["ioss_registered"])}
    res = price_cart(conn, dest, items, on, version, state=state, **seller) if items else None
    if res is not None and not res.supported:
        good = []  # one product that cannot be priced must not take the others down with it
        for it in items:
            one = price_cart(conn, dest, [it], on, version, state=state, **seller)
            if one.supported:
                good.append(it)
            else:
                reasons[it["sku"]] = cat.UNSUPPORTED.get(one.unsupported_reason or "", "Not priced yet") + "."
        res = price_cart(conn, dest, good, on, version, state=state, **seller) if good else None
        if res is not None and not res.supported:
            why = cat.UNSUPPORTED.get(res.unsupported_reason or "", "Duties-included is not available for this order") + "."
            for it in good:
                reasons[it["sku"]] = why
            res = None
    by = {ln.sku: ln for ln in res.lines} if res is not None else {}
    discount = seller_absorbed(conn, dest, [i for i in items if i["sku"] in by], on, version, state, shop) if by else Decimal("0.00")
    tax_total = res.tax_total if res is not None else Decimal("0.00")
    lines: list[s.QuoteLine] = []
    for p, d, q in prods:
        ln = by.get(p["id"])
        lines.append(s.QuoteLine(
            product_id=p["id"], sku=p.get("sku"), title=p["title"], quantity=q, unit_price=money(p["prices"][cur], cur),  # type: ignore[arg-type]
            duty_and_tax=money(ln.duty_and_tax if ln else 0, cur), duties_included=ln is not None,  # type: ignore[arg-type]
            trail=trail_lines(res) if ln and res is not None else [], unpriced_reason=None if ln else reasons.get(p["id"], "Not priced."),
            origin=d["origin"] if d else None, code=d["code"] if d else None))
    included = bool(by)
    paused = health.paused_reason or (None if included else _due(next(iter(reasons.values()), "not priced.")))
    total = item_total + ship + (tax_total if included else Decimal("0.00")) - (discount if included else Decimal("0.00"))
    unit = build_purchase_unit(
        currency=cur, shipping=ship, discount=discount if included else Decimal("0.00"),
        items=[OrderItem(name=ln.title, sku=ln.sku or ln.product_id, quantity=ln.quantity, unit_amount=Decimal(ln.unit_price.amount), tax_total=Decimal(ln.duty_and_tax.amount)) for ln in lines])
    token, expires = quote_token.make(
        shop["id"], cur, dest, body.ship_to_country, f"{item_total:.2f}", f"{ship:.2f}", unit["amount"]["breakdown"]["tax_total"]["value"], unit["amount"]["value"],
        [{"sku": ln.sku or ln.product_id, "quantity": ln.quantity, "tax": f"{Decimal(ln.duty_and_tax.amount):.2f}"} for ln in lines])
    return s.Quote(
        paypal_purchase_unit=unit, quote_token=token, quote_expires_at=expires,
        destination=dest, ship_to_label=ship_label, ship_to_country=body.ship_to_country, currency=cur, lines=lines,  # type: ignore[arg-type]
        item_total=money(item_total, cur), shipping=money(ship, cur), tax_total=money(tax_total, cur),  # type: ignore[arg-type]
        seller_discount=money(discount if included else 0, cur), total=money(total, cur), duties_included=included,  # type: ignore[arg-type]
        old_way_note=OLD_WAY[dest].format(tax=f"{SYMBOL[cur]}{tax_total:.2f}"), rates_as_of=on, register_version=repo.version_label(conn, version),
        stale_note=health.stale_note, paused_reason=paused, delivered_duty_paid_note=DDP_NOTE)


def paypal_client() -> PayPalClient:
    cid, sec = env("PAYPAL_CLIENT_ID"), env("PAYPAL_CLIENT_SECRET")
    if not cid or not sec:
        raise RuntimeError("PayPal sandbox credentials are not configured")
    return PayPalClient(cid, sec)


def create_order(conn: Connection, body: s.OrderCreateIn, client: PayPalClient | None = None, shop: dict | None = None) -> s.OrderCreated:
    shop = shop or demo.SHOP
    q = quote(conn, body.quote, shop)
    oid = cat.new_id("ord")
    cur = q.currency
    items = [OrderItem(name=ln.title, sku=ln.sku or ln.product_id, quantity=ln.quantity, unit_amount=Decimal(ln.unit_price.amount),
                       tax_total=Decimal(ln.duty_and_tax.amount) if q.duties_included else Decimal("0.00")) for ln in q.lines]
    sep = "&" if "?" in body.return_url else "?"
    req = build_order_request(
        currency=cur, items=items, shipping=Decimal(q.shipping.amount), custom_id=oid,
        description=f"{shop['name']} order" + (", import duties and taxes included" if q.duties_included else ""),
        return_url=f"{body.return_url}{sep}order_id={oid}", cancel_url=body.cancel_url, brand_name=shop["name"],
        discount=Decimal(q.seller_discount.amount))
    try:
        pp = (client or paypal_client()).create_order(req, request_id=oid)
    except PayPalError as e:  # buyer sees PayPal's error; no order row is written
        raise RuntimeError(f"PayPal could not create the order: {e}") from e
    version = repo.latest_version(conn)
    conn.execute(text("""INSERT INTO app_order (id, shop_id, paypal_order_id, destination, currency, item_total, shipping, duty_tax, register_version,
                         import_date, status, quote) VALUES (:id, :shop, :pp, :d, :c, :it, :sh, :tax, :v, :on, 'CREATED', CAST(:q AS jsonb))"""),
                 {"id": oid, "shop": shop["id"], "pp": pp["id"], "d": q.destination, "c": cur, "it": q.item_total.amount, "sh": q.shipping.amount,
                  "tax": q.tax_total.amount, "v": version, "on": q.rates_as_of, "q": q.model_dump_json()})
    cat.audit(conn, "buyer", "order_created", "order", oid, {"paypal_order_id": pp["id"], "register_version": version, "total": q.total.amount})
    return s.OrderCreated(order_id=oid, paypal_order_id=pp["id"], approve_url=approve_url(pp), register_version=repo.version_label(conn, version),
                          total=q.total, paypal_purchase_unit=req["purchase_units"][0])


def capture_order(conn: Connection, order_id: str, client: PayPalClient | None = None, shipper=None, shop: dict | None = None) -> s.OrderCaptured:
    o = conn.execute(text("SELECT * FROM app_order WHERE id = :i"), {"i": order_id}).mappings().first()
    if o is None or o["shop_id"] != (shop or demo.SHOP)["id"]:
        raise LookupError(order_id)
    o = dict(o)
    label = repo.version_label(conn, o["register_version"])
    if o["status"] == "CAPTURED":  # idempotent
        cap = o["capture"]
        return s.OrderCaptured(order_id=order_id, paypal_order_id=o["paypal_order_id"], capture_id=cap["capture_id"], status="COMPLETED",
                               tax_total=money(cap["tax_total"]["value"], o["currency"]), register_version=label, shipment_id=(o["shipment"] or {}).get("id"))
    try:
        raw = (client or paypal_client()).capture(o["paypal_order_id"], request_id=f"cap-{order_id}")
    except PayPalError as e:
        raise RuntimeError(f"PayPal could not capture the order: {e}") from e
    summ = summarise_capture(raw)
    if summ["status"] != "COMPLETED":
        raise RuntimeError(f"PayPal returned status {summ['status']}")
    conn.execute(text("UPDATE app_order SET status = 'CAPTURED', capture_id = :c, capture = CAST(:cap AS jsonb) WHERE id = :i"),
                 {"c": summ["capture_id"], "cap": json.dumps(summ), "i": order_id})
    minted = None
    quote_json = o["quote"]
    if quote_json.get("duties_included"):
        ins = conn.execute(text("INSERT INTO stamp (shop_id, destination, first_order_id) VALUES (:s, :d, :o) ON CONFLICT DO NOTHING"),
                           {"s": o["shop_id"], "d": o["destination"], "o": order_id}).rowcount
        minted = o["destination"] if ins else None
    cat.audit(conn, "buyer", "order_captured", "order", order_id, {"capture_id": summ["capture_id"], "tax_total": summ["tax_total"], "stamp_minted": minted})
    ship = shipment.create_for_order(conn, {**o, "status": "CAPTURED"}, shipper if shipper is not None else shipment.easyship_client())  # never raises
    shipment.record(conn, order_id, ship)
    return s.OrderCaptured(order_id=order_id, paypal_order_id=o["paypal_order_id"], capture_id=summ["capture_id"], status="COMPLETED",
                           tax_total=money(summ["tax_total"]["value"], o["currency"]), register_version=label, shipment_id=ship.get("id"),
                           stamp_minted=minted)  # type: ignore[arg-type]
