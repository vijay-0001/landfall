"""Landfall duty engine: a pure, deterministic function. No I/O, no clock, no model call, no currency conversion.

price(input, rows) takes the cart, the destination and the register rows visible to the caller (already
filtered to one register version) and returns duty, import VAT and a calculation trail.

Rules implemented (docs/hld.md section 7):
 1. Rows are used only if valid on the import date.
 2. Low-value rules first: UK 135 pound duty relief (duty only), EU flat duty per item category for
    consignments up to the limit; the US has no de minimis.
 3. Base duty, then additional duties in the order the law stacks them; a "total rate floor" row means
    the total ad valorem rate is the higher of the base rate and the floor (US note 52 for the EU).
 4. Import VAT where the destination charges it at sale (UK, EU via IOSS).
 5. If the import date is within `change_window_days` before a change date, price both sides and use the
    higher.
 6. Round half up to the cent per component; return a trail of every row used.
The engine refuses (supported=False) rather than guessing: unknown code, uncovered origin, currency that
does not match the destination, no valid rule on the date.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")
DEST_CURRENCY = {"US": "USD", "GB": "GBP", "EU": "EUR", "AU": "AUD"}


def _q(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _d(x: Any) -> Decimal:
    return Decimal(str(x))


def _digits(code: str) -> str:
    return "".join(ch for ch in code if ch.isdigit())


def _date(x: Any) -> date | None:
    if x is None or isinstance(x, date):
        return x
    return date.fromisoformat(x)


@dataclass
class TrailEntry:
    label: str
    base: Decimal
    rate: str
    amount: Decimal
    row_id: str | None
    source_ref: str
    source_url: str | None = None


@dataclass
class LineResult:
    sku: str
    duty: Decimal
    vat: Decimal
    trail: list[TrailEntry] = field(default_factory=list)

    @property
    def duty_and_tax(self) -> Decimal:
        return self.duty + self.vat


@dataclass
class Result:
    supported: bool
    destination: str
    currency: str
    unsupported_reason: str | None = None
    duty_total: Decimal = Decimal("0.00")
    vat_total: Decimal = Decimal("0.00")
    lines: list[LineResult] = field(default_factory=list)
    trail: list[TrailEntry] = field(default_factory=list)
    straddle_applied: bool = False
    home_market: bool = False
    priced_on: date | None = None
    rule_summary: str = ""

    @property
    def tax_total(self) -> Decimal:
        return self.duty_total + self.vat_total


def _no(inp: dict, reason: str) -> Result:
    return Result(False, inp["destination"], inp["currency"], unsupported_reason=reason)


def _valid(row: dict, on: date) -> bool:
    vf, vt = _date(row["valid_from"]), _date(row.get("valid_to"))
    return vf <= on and (vt is None or on < vt)


def _origin_matches(row: dict, origin: str, groups: dict[str, list[str]]) -> bool:
    scope = row["origin_scope"]
    return scope == "ALL" or scope == origin or origin in groups.get(scope, [])


def _code_matches(row: dict, code: str) -> bool:
    rc = row["code"]
    return rc == "*" or _digits(code).startswith(_digits(rc))


def _best_base(rows: list[dict], code: str) -> dict | None:
    cands = [r for r in rows if r["measure"] == "base_duty" and r["code"] != "*" and _code_matches(r, code)]
    return max(cands, key=lambda r: len(_digits(r["code"])), default=None)


def _country_rate(row: dict) -> bool:
    """True for a row made by the country-rate headings 9903.05.20 to 9903.05.84 (U.S. note 52): the rows the note's exemption lists switch off."""
    p = row.get("params") or {}
    heads = [p["hts_heading"]] if p.get("hts_heading") else list(p.get("hts_headings") or [])
    return any("9903.05.20" <= h <= "9903.05.84" for h in heads)


def _entry(label: str, base: Decimal, row: dict, amount: Decimal, rate: str | None = None) -> TrailEntry:
    if rate is None:
        rate = f"{row['rate']}%" if row.get("rate_kind") == "percent" else f"{row.get('rate')} {row.get('currency') or ''}".strip()
    return TrailEntry(label, base, rate, amount, row["id"], row["source_ref"], row.get("source_url"))


def _allocate(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Split a cent amount in proportion to weights; remainder cents go to the largest remainders."""
    w = sum(weights)
    if w == 0:
        return [Decimal("0.00")] * len(weights)
    raw = [total * x / w for x in weights]
    floor = [r.quantize(CENT, rounding="ROUND_FLOOR") for r in raw]
    left = int(((total - sum(floor)) / CENT).to_integral_value())
    order = sorted(range(len(weights)), key=lambda i: (raw[i] - floor[i], -i), reverse=True)
    for i in order[:left]:
        floor[i] += CENT
    return floor


def _line_values(inp: dict) -> list[Decimal]:
    return [_d(i["unit_price"]) * int(i["quantity"]) for i in inp["items"]]


def _is_home(inp: dict) -> bool:
    seller, dest = inp["seller_country"], inp["destination"]
    return seller == dest or (dest == "EU" and seller in inp.get("origin_groups", {}).get("EU", []))


# ------------------------------------------------------------------ US
def _price_us(inp: dict, rows: list[dict], on: date) -> Result:
    groups = inp.get("origin_groups", {})
    res = Result(True, "US", inp["currency"], priced_on=on, rule_summary="Product duty plus extra duties tied to the country of origin; no duty-free allowance for small parcels")
    relief = next((r for r in rows if r["measure"] == "low_value_relief"), None)
    if relief is not None and sum(_line_values(inp), Decimal("0.00")) <= _d(relief["rate"]):
        # A period when the US admitted low-value parcels duty-free (history only; suspended since 2025).
        res.rule_summary = "Low-value parcels entered duty-free in this period"
        res.lines = [LineResult(i["sku"], Decimal("0.00"), Decimal("0.00")) for i in inp["items"]]
        res.trail = [_entry("Duty-free low-value entry", sum(_line_values(inp), Decimal("0.00")), relief, Decimal("0.00"),
                            f"<= {relief['rate']} USD")]
        return res
    for item, value in zip(inp["items"], _line_values(inp), strict=True):
        origin = item["origin"]
        if not any(r["measure"] == "origin_coverage" and _origin_matches(r, origin, groups) for r in rows):
            return _no(inp, "origin_not_covered")
        if any(r["measure"] == "exclusion_review" and _origin_matches(r, origin, groups) and _code_matches(r, item["code"]) for r in rows):
            return _no(inp, "exclusion_review")  # a product exclusion on this line may apply; never priced by guess
        if any(r["measure"] == "special_duty_review" and _origin_matches(r, origin, groups) and _code_matches(r, item["code"]) for r in rows):
            return _no(inp, "special_duty_review")  # Section 232 or similar duties may stack here and are not priced
        review = next((r for r in rows if r["measure"] == "origin_review" and _origin_matches(r, origin, groups) and _code_matches(r, item["code"])), None)
        if review is not None:
            return _no(inp, (review.get("params") or {}).get("reason", "origin_review"))
        base = _best_base(rows, item["code"])
        if base is None:
            return _no(inp, "code_not_in_register")
        exempt = any(r["measure"] == "origin_exemption" and _origin_matches(r, origin, groups) and _code_matches(r, item["code"]) for r in rows)
        line = LineResult(item["sku"], Decimal("0.00"), Decimal("0.00"))
        rate = _d(base["rate"])
        base_amt = _q(value * rate / 100)
        line.trail.append(_entry("Product duty (general rate)", value, base, base_amt))
        line.duty += base_amt
        for r in rows:
            if not (_origin_matches(r, origin, groups) and _code_matches(r, item["code"])):
                continue
            if exempt and _country_rate(r) and r["measure"] in ("additional_duty", "total_rate_floor"):
                line.trail.append(_entry("Exempt from the country duty (U.S. note 52 list)", value, r, Decimal("0.00"), "0%"))
                continue
            if r["measure"] == "additional_duty":
                amt = _q(value * _d(r["rate"]) / 100)
                line.trail.append(_entry("Additional duty (origin-specific)", value, r, amt))
                line.duty += amt
            elif r["measure"] == "total_rate_floor" and rate < _d(r["rate"]):
                total = _q(value * _d(r["rate"]) / 100)
                extra = total - base_amt
                line.trail.append(_entry("Top-up to the higher-of rate", value, r, extra, f"{r['rate']}% total"))
                line.duty += extra
        res.lines.append(line)
    res.duty_total = sum((ln.duty for ln in res.lines), Decimal("0.00"))
    res.trail = [t for ln in res.lines for t in ln.trail]
    return res


# ------------------------------------------------------------------ UK
def _price_gb(inp: dict, rows: list[dict], on: date) -> Result:
    values = _line_values(inp)
    goods = sum(values, Decimal("0.00"))
    ship = _d(inp["shipping"])
    res = Result(True, "GB", inp["currency"], priced_on=on)
    relief = next((r for r in rows if r["measure"] == "low_value_relief"), None)
    vat_row = next((r for r in rows if r["measure"] == "import_vat" and r["code"] == "*"), None)
    if vat_row is None:
        return _no(inp, "vat_rate_not_in_register")
    duty_alloc = [Decimal("0.00")] * len(values)
    if relief is not None and goods <= _d(relief["rate"]):
        res.rule_summary = "Goods up to 135 pounds: duty relieved, VAT charged at sale"
        res.trail.append(_entry("Customs duty relieved (low-value relief)", goods, relief, Decimal("0.00"), f"<= {relief['rate']} GBP"))
        vat_base = goods + ship
    else:
        bases = []
        for item in inp["items"]:
            b = _best_base(rows, item["code"])
            if b is None:
                return _no(inp, "code_not_in_register")
            bases.append(b)
        incl_ship = any(b["params"].get("include_shipping_in_customs_value") for b in bases)
        ship_alloc = _allocate(ship, values) if incl_ship else [Decimal("0.00")] * len(values)
        duty_alloc = []
        for b, v, s in zip(bases, values, ship_alloc, strict=True):
            amt = _q((v + s) * _d(b["rate"]) / 100)
            duty_alloc.append(amt)
            res.trail.append(_entry("Customs duty (third-country rate)", v + s, b, amt))
        res.rule_summary = "Goods over 135 pounds: duty and VAT"
        vat_base = goods + ship + sum(duty_alloc, Decimal("0.00"))
    vat = _q(vat_base * _d(vat_row["rate"]) / 100)
    res.trail.append(_entry("Import VAT", vat_base, vat_row, vat))
    vat_alloc = _allocate(vat, values)
    for item, d, v in zip(inp["items"], duty_alloc, vat_alloc, strict=True):
        res.lines.append(LineResult(item["sku"], d, v))
    res.duty_total = sum(duty_alloc, Decimal("0.00"))
    res.vat_total = vat
    return res


# ------------------------------------------------------------------ EU
def _price_eu(inp: dict, rows: list[dict], on: date) -> Result:
    if not inp.get("ioss_registered"):
        return _no(inp, "seller_not_ioss")
    flat = next((r for r in rows if r["measure"] == "flat_per_item_category"), None)
    if flat is None:
        return _no(inp, "no_rule_valid_on_date")
    values = _line_values(inp)
    goods = sum(values, Decimal("0.00"))
    if goods > _d(flat["params"]["limit"]):
        return _no(inp, "over_low_value_limit")
    state = inp.get("eu_member_state")
    if not state:
        return _no(inp, "member_state_required")
    vat_row = next((r for r in rows if r["measure"] == "import_vat" and r["params"].get("member_state") == state), None)
    if vat_row is None:
        return _no(inp, "vat_rate_not_in_register")
    res = Result(True, "EU", inp["currency"], priced_on=on, rule_summary="A flat duty per item category, plus VAT at the buyer's country rate, both collected at checkout")
    unit = _d(flat["rate"])
    seen: set[str] = set()
    duty_by_line = []
    for item in inp["items"]:
        cat = _digits(item["code"])[:6]
        if cat in seen:
            duty_by_line.append(Decimal("0.00"))
        else:
            seen.add(cat)
            duty_by_line.append(unit)
            res.trail.append(_entry(f"Flat duty, item category {cat[:4]}.{cat[4:]}", unit, flat, unit))
    vat_base = goods + _d(inp["shipping"])
    vat = _q(vat_base * _d(vat_row["rate"]) / 100)
    res.trail.append(_entry(f"Import VAT ({state})", vat_base, vat_row, vat))
    for item, d, v in zip(inp["items"], duty_by_line, _allocate(vat, values), strict=True):
        res.lines.append(LineResult(item["sku"], d, v))
    res.duty_total = sum(duty_by_line, Decimal("0.00"))
    res.vat_total = vat
    return res


# ------------------------------------------------------------------ Australia
def _price_au(inp: dict, rows: list[dict], on: date) -> Result:
    """Customs duty (one general-rate row for most goods) applies only above the low-value threshold; GST is charged at sale on low-value goods and at
    the border above it. GST base: goods plus shipping plus any duty."""
    values = _line_values(inp)
    goods = sum(values, Decimal("0.00"))
    ship = _d(inp["shipping"])
    for item in inp["items"]:
        if any(r["measure"] == "special_duty_review" and _code_matches(r, item["code"]) for r in rows):
            return _no(inp, "special_duty_review")  # alcohol and tobacco are taxed at the border whatever the value
    gst = next((r for r in rows if r["measure"] == "import_vat" and r["code"] == "*"), None)
    if gst is None:
        return _no(inp, "vat_rate_not_in_register")
    relief = next((r for r in rows if r["measure"] == "low_value_relief"), None)
    base = next((r for r in rows if r["measure"] == "base_duty" and r["code"] == "*"), None)
    res = Result(True, "AU", inp["currency"], priced_on=on)
    duty_alloc = [Decimal("0.00")] * len(values)
    if relief is not None and goods <= _d(relief["rate"]):
        res.rule_summary = "Goods up to AUD 1,000: no customs duty; GST charged at sale"
        res.trail.append(_entry("Customs duty relieved (low-value threshold)", goods, relief, Decimal("0.00"), f"<= {relief['rate']} AUD"))
        gst_base = goods + ship
    else:
        if base is None:
            return _no(inp, "code_not_in_register")
        duty_alloc = [_q(v * _d(base["rate"]) / 100) for v in values]
        res.trail.append(_entry("Customs duty (general rate)", goods, base, sum(duty_alloc, Decimal("0.00"))))
        res.rule_summary = "Goods over AUD 1,000: customs duty and GST at the border"
        gst_base = goods + ship + sum(duty_alloc, Decimal("0.00"))
    tax = _q(gst_base * _d(gst["rate"]) / 100)
    res.trail.append(_entry("GST", gst_base, gst, tax))
    for item, d, v in zip(inp["items"], duty_alloc, _allocate(tax, values), strict=True):
        res.lines.append(LineResult(item["sku"], d, v))
    res.duty_total = sum(duty_alloc, Decimal("0.00"))
    res.vat_total = tax
    return res


_PRICERS = {"US": _price_us, "GB": _price_gb, "EU": _price_eu, "AU": _price_au}


def _price_at(inp: dict, rows: list[dict], on: date) -> Result:
    live = [r for r in rows if r["destination"] == inp["destination"] and _valid(r, on)]
    return _PRICERS[inp["destination"]](inp, live, on)


def change_dates(rows: list[dict], destination: str) -> list[date]:
    out: set[date] = set()
    for r in rows:
        if r["destination"] != destination or r["measure"] == "origin_coverage":
            continue
        for k in ("valid_from", "valid_to"):
            if r.get(k):
                out.add(_date(r[k]))
    return sorted(out)


def price(inp: dict, rows: list[dict]) -> Result:
    dest = inp["destination"]
    if dest not in DEST_CURRENCY:
        return _no(inp, "destination_not_supported")
    if inp["currency"] != DEST_CURRENCY[dest]:
        return _no(inp, "currency_mismatch")
    on = _date(inp["import_date"])
    if _is_home(inp):
        r = Result(True, dest, inp["currency"], home_market=True, priced_on=on, rule_summary="Home market: no import duty or import tax")
        r.lines = [LineResult(i["sku"], Decimal("0.00"), Decimal("0.00")) for i in inp["items"]]
        r.trail = [TrailEntry("Home market", Decimal("0.00"), "0%", Decimal("0.00"), None, "Seller and buyer are in the same market")]
        return r
    best = _price_at(inp, rows, on)
    if not best.supported:
        return best
    window = int(inp.get("change_window_days", 5))
    for c in change_dates(rows, dest):
        if on < c <= on + timedelta(days=window):
            other = _price_at(inp, rows, c)
            if other.supported and other.tax_total > best.tax_total:
                other.straddle_applied = True
                other.priced_on = c
                best = other
    return best
