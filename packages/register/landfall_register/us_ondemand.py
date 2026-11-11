"""US tariff headings on demand.

The register starts with the core headings. When a product lands in any other heading of the Harmonized Tariff, that heading's
lines are read (from the recorded export if present, else live from the USITC) and every plain-percentage or Free general rate is appended
to the register as one new version, with its source and date. Compound and specific rates are never stored, so those codes stay
"not priced" (never a guess). `fetch(heading)` returns the USITC export rows for a heading (injectable for tests).
"""
from __future__ import annotations

import datetime
import json
import os
import urllib.request

from sqlalchemy import Connection, text

from . import loaders, repo

EXPORT = "https://hts.usitc.gov/reststop/exportList?from={h}.00.00&to={h}.99.99&format=JSON&styles=false"
UA = "landfall-pay/0.1 (tariff reader)"


def live_fetch(heading: str) -> dict:
    req = urllib.request.Request(EXPORT.format(h=heading), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.loads(r.read())
    return {"fetched": datetime.date.today().isoformat(), "source": EXPORT.format(h=heading), "rows": rows}


def recorded_or_live(heading: str) -> dict:
    f = loaders.FIXTURES / "usitc" / f"hts_{heading}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    if os.environ.get("LANDFALL_US_ONDEMAND", "").lower() == "off":
        raise OSError("the on-demand US tariff read is switched off")
    return live_fetch(heading)


def loaded(conn: Connection, heading: str) -> bool:
    return conn.execute(text("SELECT 1 FROM rate_row WHERE destination = 'US' AND measure = 'base_duty' AND code LIKE :p LIMIT 1"), {"p": f"{heading}.%"}).first() is not None


def ensure_headings(conn: Connection, headings: list[str], fetch=recorded_or_live) -> list[str]:
    """Load the given 4-digit headings that the register does not hold yet, in one new version. Returns the headings that were loaded.
    A heading that cannot be read is skipped (the product stays "not priced" for it)."""
    todo = [h for h in dict.fromkeys(headings) if h and not loaded(conn, h)]
    batches: list[tuple[str, list[dict]]] = []
    for h in todo:
        try:
            rows, _ = loaders.hts_rows(fetch(h))
        except Exception:
            continue
        if rows:
            batches.append((h, rows))
    if not batches:
        return []
    n = conn.execute(text("SELECT count(*) FROM register_version WHERE label LIKE :p"), {"p": f"r-{datetime.date.today().isoformat()}.%"}).scalar_one()
    v = repo.new_version(conn, f"r-{datetime.date.today().isoformat()}.{n + 1}", "system", note=f"US tariff read on first use: {', '.join(h for h, _ in batches)}")
    for _, rows in batches:
        for row in rows:
            repo.add_row(conn, v, row)
    return [h for h, _ in batches]
