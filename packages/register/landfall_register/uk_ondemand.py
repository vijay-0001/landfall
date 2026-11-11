"""UK commodities on demand.

The register starts with a few hand-loaded UK commodities. When a product lands in a 6-digit subheading the UK side has no
rate for, the UK Trade Tariff is read (the heading, then each 10-digit commodity under the subheading) and one commodity
is appended to the register as a new version, with its source. This is only done when every commodity under the subheading
carries the same third-country rate, so which of them applies does not matter. If they differ, or the read fails, nothing is
stored and the UK column stays "No priced line yet": never a guess.

`get(path)` returns the Trade Tariff JSON for e.g. "headings/6109" or "commodities/6109100010" (injectable: tests use recordings).
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

from . import loaders, repo

API = "https://www.trade-tariff.service.gov.uk/api/v2/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"  # the API rejects bare clients
MAX_LEAVES = 12


@dataclass
class Outcome:
    loaded: bool
    reason: str = ""
    code: str | None = None
    rate: str | None = None


def live_get(path: str) -> dict:
    req = urllib.request.Request(API + path, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def has_rate(conn: Connection, hs6: str) -> bool:
    digits = hs6.replace(".", "")
    v = repo.latest_version(conn)
    return any(r["measure"] == "base_duty" and r["code"].startswith(digits) for r in repo.rows_visible(conn, v, "GB", prefix=digits))


def read_subheading(hs6: str, get=live_get) -> tuple[list[dict] | None, str]:
    """The commodity documents under a 6-digit subheading, or (None, why not). Network only; touches no database."""
    digits = hs6.replace(".", "")
    try:
        heading = get(f"headings/{digits[:4]}")
        leaves = sorted({i["attributes"]["goods_nomenclature_item_id"] for i in heading["included"]
                         if i["type"] == "commodity" and i["attributes"].get("leaf") and i["attributes"]["goods_nomenclature_item_id"].startswith(digits)})
        if not leaves:
            return None, f"the UK Trade Tariff lists no commodity under {hs6}"
        if len(leaves) > MAX_LEAVES:
            return None, f"{len(leaves)} commodities under {hs6}: too many to compare"
        return [get(f"commodities/{c}") for c in leaves], ""
    except Exception as e:  # a read that fails leaves the register untouched
        return None, f"the UK Trade Tariff could not be read ({str(e)[:80]})"


def _third_country(doc: dict) -> set[Decimal]:
    """The current third-country rates of one commodity document (a set: more than one means more than one open measure)."""
    inc = {(i["type"], i["id"]): i for i in doc["included"]}
    out: set[Decimal] = set()
    for m in doc["included"]:
        if m["type"] != "measure" or m["attributes"].get("effective_end_date"):
            continue
        mt = inc.get(("measure_type", m["relationships"]["measure_type"]["data"]["id"]), {}).get("attributes", {}).get("description", "")
        geo = m["relationships"]["geographical_area"]["data"]["id"]
        if mt == "Third country duty" and geo == "1011":
            de = inc.get(("duty_expression", m["relationships"].get("duty_expression", {}).get("data", {}).get("id")), {}).get("attributes", {})
            rate = loaders.parse_general_rate((de.get("base") or "").replace(" ", ""))
            out.add(rate if rate is not None else Decimal("-1"))  # -1: not a pure percentage, which never counts as agreement
    return out


def store(conn: Connection, hs6: str, docs: list[dict]) -> Outcome:
    rates = [_third_country(d) for d in docs]
    flat = set().union(*rates) if rates else set()
    if any(len(r) != 1 for r in rates) or len(flat) != 1 or Decimal("-1") in flat:
        return Outcome(False, f"the commodities under {hs6} differ in rate or are not a plain percentage, so no single UK rate applies")
    code = docs[0]["data"]["attributes"]["goods_nomenclature_item_id"]
    note = (f"All {len(docs)} commodity code(s) under {hs6} carry the same third-country rate; {code} is the representative. "
            "Preferential rates by origin are not modelled; duty relief under 135 pounds applies first.")
    today = date.today().isoformat()
    n = conn.execute(text("SELECT count(*) FROM register_version WHERE label LIKE :p"), {"p": f"r-{today}.%"}).scalar_one() + 1
    v = repo.new_version(conn, f"r-{today}.{n}", "system:uk-ondemand", note=f"UK Trade Tariff commodity {docs[0]['data']['attributes']['goods_nomenclature_item_id']} read on demand for {hs6}")
    loaders.load_uk_commodity_docs(conn, v, [docs[0]], with_vat=False, note=note)
    return Outcome(True, "", code, str(flat.pop()))


def ensure(conn: Connection, hs6: str, get=live_get) -> Outcome:
    if has_rate(conn, hs6):
        return Outcome(False, "already in the register")
    docs, why = read_subheading(hs6, get)
    if docs is None:
        return Outcome(False, why)
    return store(conn, hs6, docs)


def ensure_many(conn: Connection, hs6s: list[str], get=live_get) -> dict[str, Outcome]:
    """`ensure` for several subheadings: the network reads run side by side, the register writes one after another."""
    from concurrent.futures import ThreadPoolExecutor

    todo = [h for h in dict.fromkeys(hs6s) if h and h != "none" and not has_rate(conn, h)]
    out: dict[str, Outcome] = {}
    if todo:
        with ThreadPoolExecutor(min(4, len(todo))) as ex:
            read = dict(zip(todo, ex.map(lambda h: read_subheading(h, get), todo), strict=True))
        for h, (docs, why) in read.items():
            out[h] = store(conn, h, docs) if docs is not None else Outcome(False, why)
    return out
