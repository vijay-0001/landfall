"""Loaders: turn recorded official-source payloads into register rows.

Every loader reads a fixture (recorded response) or a payload handed in by the nightly worker; none calls the
network itself, so contract tests run on fixtures. Each returns a LoadReport so the ops sync table can show
rows changed, future-dated rows and anything skipped (never silently).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import Connection

from . import repo

PKG = Path(__file__).resolve().parent.parent
FIXTURES = PKG / "fixtures"
DATA = PKG / "data"
SERIES_START = date(2025, 1, 1)
RATE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*%\s*$")


@dataclass
class LoadReport:
    source: str
    rows_added: int = 0
    future_dated: int = 0
    skipped: list[str] = field(default_factory=list)


def parse_general_rate(text: str | None) -> Decimal | None:
    """Pure ad valorem or Free only. Compound or specific rates (cents per kg, plus ...) return None: the engine
    refuses to price those codes (code_not_in_register) rather than under-charge."""
    if text is None:
        return None
    t = text.strip()
    if t.lower() == "free":
        return Decimal("0")
    m = RATE_RE.match(t)
    if not m:
        return None
    try:
        return Decimal(m.group(1))
    except InvalidOperation:
        return None


def hts_rows(data: dict, seen: set[str] | None = None) -> tuple[list[dict], list[str]]:
    """Pure: an HTS export payload ({"fetched", "rows"}) -> base_duty register rows and a list of what was skipped."""
    seen = seen if seen is not None else set()
    rows, skipped = [], []
    fetched = data.get("fetched", "")
    for r in data["rows"]:
        code = r["htsno"]
        if not code or "." not in code or r.get("general") in (None, "") or code in seen:
            continue
        rate = parse_general_rate(r.get("general"))
        if rate is None:
            skipped.append(f"{code}: rate '{r.get('general')}' is not a pure ad valorem rate")
            continue
        seen.add(code)
        rows.append({
            "destination": "US", "code": code, "origin_scope": "ALL", "measure": "base_duty", "rate_kind": "percent",
            "rate": str(rate), "currency": None, "params": {}, "valid_from": SERIES_START, "valid_to": None,
            "source_ref": f"HTS {code}: {(r['description'] or '')[:120]}. USITC HTS general column 1, recorded {fetched}",
            "source_url": f"https://hts.usitc.gov/search?query={code}",
            "note": "valid_from is the series start (Jan 2025); the general rate was unchanged across it.",
        })
    return rows, skipped


CORE_HEADINGS = ["4201", "4202", "4203", "4205", "6101", "6102", "6103", "6104", "6105", "6106", "6107", "6108", "6109", "6110", "6111", "6112", "6113", "6114", "6115", "6116", "6117", "6201", "6202", "6203", "6204", "6205", "6206", "6207", "6208", "6209", "6210", "6211", "6212", "6213", "6214", "6215", "6216", "6217", "6301", "6302", "6303", "6304", "6305", "6307", "6907", "6911", "6912", "6913", "6914"]


def load_usitc_headings(conn: Connection, version: int, files: list[Path] | None = None) -> LoadReport:
    """The initial load covers the core headings only; every other heading of the tariff is read on first use (us_ondemand)."""
    rep = LoadReport("US tariff schedule (USITC)")
    seen: set[str] = set()
    core = [FIXTURES / "usitc" / f"hts_{h}.json" for h in CORE_HEADINGS]
    for f in sorted(files or [c for c in core if c.exists()]):
        rows, skipped = hts_rows(json.loads(f.read_text(encoding="utf-8")), seen)
        rep.skipped += skipped
        for row in rows:
            repo.add_row(conn, version, row)
            rep.rows_added += 1
    return rep


def load_uk_commodities(conn: Connection, version: int, files: list[Path] | None = None) -> LoadReport:
    docs = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(files or (FIXTURES / "uk_tariff").glob("commodity_*.json"))]
    return load_uk_commodity_docs(conn, version, docs)


def load_uk_commodity_docs(conn: Connection, version: int, docs: list[dict], with_vat: bool = True, note: str | None = None) -> LoadReport:
    """Rows from UK Trade Tariff commodity documents (recorded files or a live read). `with_vat=False` skips the UK VAT row."""
    rep = LoadReport("UK Trade Tariff API")
    vat_loaded = not with_vat
    for d in docs:
        inc = {(i["type"], i["id"]): i for i in d["included"]}
        code = d["data"]["attributes"]["goods_nomenclature_item_id"]
        for m in d["included"]:
            if m["type"] != "measure":
                continue
            mt = inc.get(("measure_type", m["relationships"]["measure_type"]["data"]["id"]), {}).get("attributes", {}).get("description", "")
            geo = m["relationships"]["geographical_area"]["data"]["id"]
            de = inc.get(("duty_expression", m["relationships"].get("duty_expression", {}).get("data", {}).get("id")), {}).get("attributes", {})
            base = (de.get("base") or "").replace(" ", "")
            start = date.fromisoformat(m["attributes"]["effective_start_date"][:10])
            if mt == "Third country duty" and geo == "1011":
                rate = parse_general_rate(base)
                if rate is None:
                    rep.skipped.append(f"{code}: third-country duty '{base}' not parsed")
                    continue
                repo.add_row(conn, version, {
                    "destination": "GB", "code": code, "origin_scope": "ALL", "measure": "base_duty", "rate_kind": "percent",
                    "rate": str(rate), "currency": None, "params": {"include_shipping_in_customs_value": True},
                    "valid_from": start, "valid_to": None,
                    "source_ref": f"UK Trade Tariff commodity {code}, Third country duty {base}, measure {m['id']}",
                    "source_url": f"https://www.trade-tariff.service.gov.uk/commodities/{code}",
                    "note": note or "Preferential rates by origin are not modelled; duty relief under 135 pounds applies first.",
                })
                rep.rows_added += 1
                rep.future_dated += start > date.today()
            elif mt == "Value added tax" and not vat_loaded:
                repo.add_row(conn, version, {
                    "destination": "GB", "code": "*", "origin_scope": "ALL", "measure": "import_vat", "rate_kind": "percent",
                    "rate": str(parse_general_rate(base)), "currency": None, "params": {"base": "goods plus shipping charged, plus duty"},
                    "valid_from": start, "valid_to": None,
                    "source_ref": f"UK Trade Tariff Value added tax standard rate {base}, measure {m['id']}",
                    "source_url": "https://www.gov.uk/guidance/vat-and-overseas-goods-sold-directly-to-customers-in-the-uk", "note": None,
                })
                vat_loaded = True
                rep.rows_added += 1
    return rep


def load_tedb_vat(conn: Connection, version: int, path: Path | None = None) -> LoadReport:
    rep = LoadReport("EU VAT rates (TEDB)")
    d = json.loads((path or (PKG.parent.parent / "spikes/d6_tedb/eu_vat_standard.json")).read_text(encoding="utf-8"))
    for state, rate in sorted(d["standard"].items()):
        repo.add_row(conn, version, {
            "destination": "EU", "code": "*", "origin_scope": "ALL", "measure": "import_vat", "rate_kind": "percent",
            "rate": str(rate), "currency": None, "params": {"member_state": state, "base": "goods plus shipping charged"},
            "valid_from": SERIES_START, "valid_to": None,
            "source_ref": f"EU TEDB standard VAT rate {state} {rate}%, situation on {d['situationOn']}",
            "source_url": "https://ec.europa.eu/taxation_customs/tedb/#/vat-search",
            "note": "VAT base excludes the flat duty (IOSS charges VAT on the sale price): pending broker check.",
        })
        rep.rows_added += 1
    return rep


def load_curated(conn: Connection, version: int, path: Path) -> LoadReport:
    """Hand-curated rows (Chapter 99, Section 301, low-value regimes), each with its citation, from a JSON data file."""
    rep = LoadReport(f"Curated rows ({path.name})")
    for r in json.loads(path.read_text(encoding="utf-8")):
        vt = date.fromisoformat(r["valid_to"]) if r.get("valid_to") else None
        vf = date.fromisoformat(r["valid_from"])
        repo.add_row(conn, version, {**r, "valid_from": vf, "valid_to": vt})
        rep.rows_added += 1
        rep.future_dated += vf > date.today()
    return rep
