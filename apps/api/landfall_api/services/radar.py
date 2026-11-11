"""Rule Radar (HLD section 9). Announced changes are rows in the register with a future date, or ops-approved rules with
no date yet. Each alert is matched to the seller's accepted products and priced on both sides of the date with the duty
engine (no model call). Absorb or Pass it on is stored with a scheduled price change; neither choice has any path into
the duty that is declared, so Radar can never reward declaring less.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal

from landfall_register import repo
from sqlalchemy import Connection, text

from .. import demo
from .. import schemas as s
from . import catalogue as cat
from .checkout import _codes  # noqa: PLC2701
from .coverage import ORIGIN_NAMES
from .pricing import EU27, ORIGIN_ALIASES, money, price_cart

SKIP_MEASURES = {"origin_coverage", "import_vat", "exclusion_review", "origin_exemption", "special_duty_review", "origin_review"}  # a review flag is not a price change
MEASURE_TITLE = {
    "additional_duty": "Additional duty", "base_duty": "Duty rate", "low_value_relief": "Low-value relief",
    "total_rate_floor": "Minimum total duty rate", "flat_per_item_category": "Temporary flat duty per item", "process_requirement": "New filing requirement",
}


def today() -> date:  # tests replace this to pin the date
    return date.today()


def _key(*parts: str) -> str:
    return "ra_" + hashlib.sha1("|".join(parts).encode()).hexdigest()[:10]


def _fmt(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def _digits(code: str) -> str:
    return "".join(c for c in code if c.isdigit())


def _origin_ok(scope: str, origin: str) -> bool:
    origin = ORIGIN_ALIASES.get(origin, origin)
    return scope == "ALL" or scope == origin or (scope == "EU" and origin in EU27)


def matches(dec: dict, code: str, scope: str) -> bool:
    """Does an accepted product (its decision: code and origin) fall under a rule's code prefix and origin scope?"""
    if code != "*" and not _digits(dec["code"]).startswith(_digits(code)):
        return False
    return _origin_ok(scope, dec["origin"])


def accepted_products(conn: Connection, shop: dict | None = None) -> list[dict]:
    return _accepted(conn, shop)


def _accepted(conn: Connection, shop: dict | None = None) -> list[dict]:
    out = []
    for r in conn.execute(text("SELECT id FROM product WHERE shop_id = :s ORDER BY created_at, id"), {"s": (shop or demo.SHOP)["id"]}).mappings():
        prod = cat.get_prod(conn, r["id"])
        dec = cat._latest_decision(conn, r["id"])  # noqa: SLF001
        if dec is not None:
            out.append({"prod": prod, "decision": dec})
    return out


def _duty(conn: Connection, dest: str, p: dict, version: int, on: date) -> Decimal | None:
    """Duty and tax for one unit of the product on a date, no straddle window. None when the register cannot price it."""
    cur = demo.DEST_CURRENCY[dest]
    if cur not in p["prod"]["prices"]:
        return None
    code = _codes(conn, dest, p["decision"], version)
    if code is None:
        return None
    item = {"sku": p["prod"]["id"], "code": code, "origin": p["decision"]["origin"], "unit_price": p["prod"]["prices"][cur], "quantity": 1}
    res = price_cart(conn, dest, [item], on, version, window=0)
    return res.tax_total if res.supported else None


def _events(conn: Connection, version: int, on: date) -> list[dict]:
    """Future starts and ends of register rows. A close and an open of the same key on one day is one 'change'."""
    rows = [r for r in repo.rows_visible(conn, version) if r["measure"] not in SKIP_MEASURES]
    key = lambda r: (r["destination"], r["code"], r["origin_scope"], r["measure"], r.get("variant") or "")  # noqa: E731
    starts = {(key(r), date.fromisoformat(r["valid_from"])): r for r in rows if date.fromisoformat(r["valid_from"]) > on}
    ends = {(key(r), date.fromisoformat(r["valid_to"])): r for r in rows if r["valid_to"] and date.fromisoformat(r["valid_to"]) > on}
    out = []
    for (k, d), r in starts.items():
        out.append({"kind": "change" if (k, d) in ends else "start", "date": d, "row": r, "old": ends.get((k, d))})
    for (k, d), r in ends.items():
        if (k, d) not in starts:
            out.append({"kind": "end", "date": d, "row": r, "old": None})
    return sorted(out, key=lambda e: (e["date"], e["row"]["id"]))


RECENT_DAYS = 120


def _recent(conn: Connection, version: int, on: date) -> list[dict]:
    """Rows whose start date passed in the last 120 days: what already reached today's prices. Informational only."""
    out = []
    for r in repo.rows_visible(conn, version):
        d = date.fromisoformat(r["valid_from"])
        if r["measure"] not in SKIP_MEASURES and on - timedelta(days=RECENT_DAYS) < d <= on:
            out.append({"kind": "took_effect", "date": d, "row": r, "old": None})
    return sorted(out, key=lambda e: (-e["date"].toordinal(), e["row"]["id"]))


def _scope_label(scope: str) -> str:
    name = "European Union" if scope == "EU" else demo.ORIGIN_LABEL.get(scope) or ORIGIN_NAMES.get(scope, scope)
    return f"the {name}" if scope in ("EU", "GB", "US", "NL") else name


def _row_alert(conn: Connection, ev: dict, accepted: list[dict], version: int, on: date, choices: dict) -> s.RadarAlert:
    r, d, kind = ev["row"], ev["date"], ev["kind"]
    dest = r["destination"]
    aid = _key(dest, r["code"], r["origin_scope"], r["measure"], r.get("variant") or "", kind, d.isoformat())
    params = r.get("params") or {}
    affected, impacts, unpriced = [], [], False
    if r["measure"] != "process_requirement":
        for p in accepted:
            dec = p["decision"]
            if not matches(dec, r["code"], r["origin_scope"]):
                continue
            before = _duty(conn, dest, p, version, d - timedelta(days=1))
            after = _duty(conn, dest, p, version, d)
            if before is None:
                continue
            if after is None:
                unpriced = True
                affected.append(p["prod"]["id"])
                continue
            if after != before:
                affected.append(p["prod"]["id"])
                impacts.append(after - before)
    cur = demo.DEST_CURRENCY[dest]
    impact = max(impacts, key=abs) if impacts else None
    past = kind == "took_effect"
    label = f"{demo.DEST_LABEL[dest].upper()} · " + (f"TOOK EFFECT {_fmt(d).upper()}" if past else f"ENDS {_fmt(d).upper()}" if kind == "end" else f"FROM {_fmt(d).upper()}" if kind == "start" else _fmt(d).upper())
    if past and not params.get("title"):
        what = MEASURE_TITLE.get(r["measure"], r["measure"])
        title = what if r["origin_scope"] == "ALL" else f"{what} on goods from {_scope_label(r['origin_scope'])}"
    elif kind == "end":
        title = params.get("title") or f"{MEASURE_TITLE.get(r['measure'], r['measure'])} ends"
    else:
        title = params.get("title") or f"{MEASURE_TITLE.get(r['measure'], r['measure'])} changes"
    if params.get("summary"):
        summary = params["summary"]
    elif past:
        basis = f"{params['basis']}. " if params.get("basis") else ""
        summary = basis + (f"Already in the prices buyers see: about {money(abs(impact), cur).amount} {cur} {'more' if impact > 0 else 'less'} per order on {len(affected)} of your products."
                           if impact else "Already included in the prices buyers see.")
    elif impact is not None:
        n = len(affected)
        summary = f"Affects {n} of your product{'s' if n != 1 else ''}. Duty and tax on each order {'rises' if impact > 0 else 'falls'} by up to {money(abs(impact), cur).amount} {cur}."
    elif unpriced:
        summary = "This rule ends on that date and the register has no replacement yet. Landfall will price these orders again as soon as the next rule is published."
    else:
        summary = "No change to the duty on your current products."
    ch = choices.get(aid)
    status: str = "in_effect" if past else "act" if impact is not None and impact != 0 else "further_out"
    return s.RadarAlert(
        id=aid, destination=dest, effective_from=d, effective_label=label, days_left=None if past else (d - on).days, title=title, summary=summary,
        affected_product_ids=affected, impact_per_order=money(impact, cur) if impact is not None else None, source_url=r.get("source_url"),
        status=status, choice=ch["choice"] if ch else None, scheduled_price_change=(ch["scheduled"] or {}).get("text") if ch else None)  # type: ignore[arg-type]


def _watch_alerts(conn: Connection) -> list[s.RadarAlert]:
    """Approved rules with no date yet (for example 'by October 2028 at the latest'). Shown as Watching, never priced."""
    out = []
    rows = conn.execute(text("SELECT id, payload FROM rule_proposal WHERE status IN ('approved', 'edited') ORDER BY created_at, id")).mappings()
    for r in rows:
        p = r["payload"]
        if (p.get("valid_from") or {}).get("value"):
            continue  # dated rules live in the register and are listed from there
        dest = (p.get("destination") or {}).get("value")
        if dest not in demo.DEST_LABEL:
            continue
        label = f"{demo.DEST_LABEL[dest].upper()} · {p.get('timing_label', 'DATE TO BE CONFIRMED').upper()}"
        out.append(s.RadarAlert(id=_key("rp", r["id"]), destination=dest, effective_from=None, effective_label=label, days_left=None,
                                title=p["notice_title"], summary=p.get("watch_summary") or p.get("notice_excerpt", ""), affected_product_ids=[],
                                impact_per_order=None, source_url=p.get("notice_url"), status="watching"))  # type: ignore[arg-type]
    return out


def _choices(conn: Connection, shop: dict | None = None) -> dict:
    rows = conn.execute(text("SELECT alert_key, choice, scheduled FROM radar_choice WHERE shop_id = :s"), {"s": (shop or demo.SHOP)["id"]}).mappings()
    return {r["alert_key"]: dict(r) for r in rows}


def alerts(conn: Connection, shop: dict | None = None) -> list[s.RadarAlert]:
    on = today()
    version = repo.latest_version(conn)
    accepted = _accepted(conn, shop)
    choices = _choices(conn, shop)
    rows = [_row_alert(conn, ev, accepted, version, on, choices) for ev in _events(conn, version, on)]
    rank = {"act": 0, "further_out": 1, "watching": 2}
    recent = [_row_alert(conn, ev, accepted, version, on, choices) for ev in _recent(conn, version, on)]
    return sorted(rows, key=lambda a: (rank[a.status], a.effective_from or date.max)) + _watch_alerts(conn) + recent


def choose(conn: Connection, alert_id: str, choice: str, user: str = cat.SELLER, shop: dict | None = None) -> s.RadarAlert:
    a = next((x for x in alerts(conn, shop) if x.id == alert_id), None)
    if a is None:
        raise LookupError(alert_id)
    if a.status != "act" or a.impact_per_order is None or a.effective_from is None:
        raise ValueError("There is no price change to decide on for this item")
    amt, cur = a.impact_per_order.amount, a.impact_per_order.currency
    sym = {"USD": "$", "GBP": "£", "EUR": "€"}[cur]
    when = _fmt(a.effective_from)
    if choice == "pass_on":
        text_ = f"Buyer price rises by {sym}{amt.lstrip('-')} from {when}" if Decimal(amt) > 0 else f"Buyer price falls by {sym}{amt.lstrip('-')} from {when}"
    else:
        text_ = f"You cover {sym}{amt.lstrip('-')} per order from {when}; the buyer price is unchanged"
    scheduled = {"kind": choice, "destination": a.destination, "effective_from": a.effective_from.isoformat(), "per_order": amt, "currency": cur,
                 "products": a.affected_product_ids, "text": text_}
    conn.execute(text("""INSERT INTO radar_choice (shop_id, alert_key, choice, scheduled) VALUES (:s, :k, :c, CAST(:j AS jsonb))
                         ON CONFLICT (shop_id, alert_key) DO UPDATE SET choice = :c, scheduled = CAST(:j AS jsonb), at = now()"""),
                 {"s": (shop or demo.SHOP)["id"], "k": alert_id, "c": choice, "j": json.dumps(scheduled)})
    cat.audit(conn, user, "radar_choice", "radar_alert", alert_id, scheduled)
    return next(x for x in alerts(conn, shop) if x.id == alert_id)


def seed_watch_items(conn: Connection) -> None:
    """Curated, cited items that have no date yet. Same shape as an ops-approved proposal; idempotent."""
    quote = lambda v, q: {"value": v, "quote": q}  # noqa: E731
    items = [{
        "doc": "GOVUK-2026-06-23-low-value",
        "payload": {
            "notice_title": "UK ends the £135 customs duty relief on low-value imports",
            "notice_url": "https://www.gov.uk/government/news/government-backs-high-street-with-acceleration-of-cheap-import-reforms-and-crackdown-on-dodgy-online-sellers",
            "notice_published": "2026-06-23",
            "notice_excerpt": "The government has since listened to industry and chosen to accelerate delivery of the reforms by six months to October 2028.",
            "watch_summary": "Matters if you start selling into the UK from abroad. The relief ends on a day set by regulations, by October 2028 at the latest. Landfall will add the date as soon as it is set.",
            "timing_label": "BY OCT 2028 AT THE LATEST",
            "destination": quote("GB", None),
            "code_pattern": quote("*", None), "origin_scope": quote("ALL", None), "measure": quote("low_value_relief", None),
            "rate": quote(None, None), "valid_from": quote(None, None),
            "valid_to": quote(None, "The government has since listened to industry and chosen to accelerate delivery of the reforms by six months to October 2028."),
            "model": "curated", "prompt_version": "-", "products_affected": 0, "sellers_affected": 0,
        }}]
    for it in items:
        conn.execute(text("""INSERT INTO rule_proposal (id, payload, status, reviewer, decided_at, notice_doc_number)
                             VALUES (:id, CAST(:p AS jsonb), 'approved', 'curated', now(), :doc) ON CONFLICT (notice_doc_number) DO NOTHING"""),
                     {"id": cat.new_id("rp"), "p": json.dumps(it["payload"]), "doc": it["doc"]})
