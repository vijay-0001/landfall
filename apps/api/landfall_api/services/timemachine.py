"""Tariff Time Machine: what a buyer paid on any date, read from the register through the duty engine.

Valid date = the point's date; known version = the latest published (so history is corrected if we later learned better).
Series are built only from published register rows; a point that rests on an assumption is labelled illustrative.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from landfall_register import repo
from sqlalchemy import Connection

from .. import demo, destinations
from ..schemas import TimeMachineOption, TimeMachineOptions, TimeMachinePoint, TimeMachineSeries
from .pricing import cart_item, money, price_cart

SERIES_START = date(2025, 1, 1)
SERIES_END = date(2026, 12, 1)
ORIGINS = {"GB": ("United Kingdom", "GB"), "IN": ("India", "IN"), "EU": ("European Union", "PT"), "CN": ("China", "CN"), "VN": ("Vietnam", "VN"), "TR": ("Türkiye", "TR"),
           "TH": ("Thailand", "TH"), "ID": ("Indonesia", "ID"), "BD": ("Bangladesh", "BD"), "PK": ("Pakistan", "PK"), "JP": ("Japan", "JP"), "KR": ("South Korea", "KR")}  # EU priced as Portugal-origin goods
SYMBOL = {"USD": "$", "GBP": "£", "EUR": "€"}
SKIP_MEASURES = {"origin_coverage", "base_duty", "import_vat", "exclusion_review", "origin_exemption", "special_duty_review", "origin_review"}


def _the(name: str) -> str:
    return f"the {name}" if name in ("United Kingdom", "United States") else name


def options() -> TimeMachineOptions:
    return TimeMachineOptions(
        products=[TimeMachineOption(id=p["id"], label=p["tm_label"]) for p in demo.PRODUCTS if p.get("tm_label")],
        origins=[TimeMachineOption(id=k, label=v[0]) for k, v in ORIGINS.items()],
        destinations=[TimeMachineOption(id=k, label=demo.DEST_LABEL[k]) for k in destinations.AVAILABLE],
    )


def _change_dates(rows: list[dict], origin: str) -> dict[date, list[dict]]:
    """Dates when a rule starts or stops applying to this origin, with the rows involved."""
    out: dict[date, list[dict]] = {}
    for r in rows:
        if r["measure"] in SKIP_MEASURES or r["origin_scope"] not in ("ALL", origin, "EU" if origin in ("PT", "DE", "FR") else origin):
            continue
        for key in ("valid_from", "valid_to"):
            if r.get(key):
                d = date.fromisoformat(r[key])
                if SERIES_START < d <= SERIES_END:
                    out.setdefault(d, []).append({**r, "_edge": key})
    return out


def _label(rows: list[dict]) -> tuple[str, str | None, str | None, bool]:
    parts, ref, url, illus = [], None, None, False
    for r in rows:
        basis = (r.get("params") or {}).get("basis") or r["measure"].replace("_", " ")
        parts.append(f"{basis} {'begins' if r['_edge'] == 'valid_from' else 'ends'}")
        ref = ref or r["source_ref"][:220]
        url = url or r.get("source_url")
        illus = illus or "assumption" in (r.get("note") or "").lower()
    return "; ".join(dict.fromkeys(parts)), ref, url, illus


def series(conn: Connection, product_id: str, origin_id: str, destination: str, today: date | None = None) -> TimeMachineSeries | None:
    today = today or date.today()
    product = demo.BY_ID.get(product_id)
    if product is None or not product.get("tm_label") or origin_id not in ORIGINS or destination not in destinations.AVAILABLE:
        return None
    origin_label, origin_country = ORIGINS[origin_id]
    version = repo.latest_version(conn)
    if version is None:
        return None
    cur = demo.DEST_CURRENCY[destination]
    item_price = Decimal(product["prices"][cur])
    ship = Decimal(demo.SHIPPING[cur])
    all_rows = repo.rows_visible(conn, version, destination)
    dates: dict[date, list[dict]] = {}
    d = SERIES_START
    while d <= SERIES_END:
        dates.setdefault(d, [])
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    for cd, rows in _change_dates(all_rows, origin_country).items():
        dates.setdefault(cd, []).extend(rows)
    pts: list[TimeMachinePoint] = []
    for dt in sorted(dates):
        res = price_cart(conn, destination, [cart_item(product, destination, origin_country)], dt, version, window=0)
        if not res.supported:
            pts = []  # never draw across a gap: keep only the contiguous verified tail
            continue
        label, ref, url, illus = _label(dates[dt]) if dates[dt] else ("", None, None, False)
        total = item_price + ship + res.tax_total
        pts.append(TimeMachinePoint(date=dt, buyer_total=money(total, cur), duty_and_tax=money(res.tax_total, cur),  # type: ignore[arg-type]
                                    is_change_date=bool(dates[dt]), is_future=dt > today, illustrative=illus,
                                    label=label or None, source_ref=ref, source_url=url))
    if not pts:
        return None
    sym = SYMBOL[cur]
    return TimeMachineSeries(
        product_id=product_id, product_label=product["tm_label"], origin_id=origin_id, origin_label=origin_label, destination=destination,  # type: ignore[arg-type]
        destination_label=demo.DEST_LABEL[destination], item_price=money(item_price, cur), shipping=money(ship, cur),  # type: ignore[arg-type]
        headline=f"What a {sym}{item_price:.0f} {product['tm_label'].lower()} from {_the(origin_label)} cost a buyer in {_the(demo.DEST_LABEL[destination])}, month by month",
        points=pts, today=today, sources=["US tariff schedule (USITC)", "Federal Register", "EU VAT rates (TEDB)", "UK Trade Tariff"],
        has_illustrative=any(p.illustrative for p in pts), register_version=repo.version_label(conn, version),
    )
