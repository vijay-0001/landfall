"""What Landfall covers today and where its data comes from (GET /api/coverage). Only what IS covered is listed; everything else is left out on purpose and a
disclaimer says more is planned for a later phase.

Nothing here is invented at request time: the origins priced for US buyers are read from the register (origin_coverage rows, minus origins held back for review), the last
success of each source comes from source_run, the 48 h and 7 day rules are the constants the checkout uses, and the schedule is the worker's
(apps/worker/landfall_worker/main.py: one cron job at 02:00 UTC runs every automatic source in turn, plus one pass at start-up when the last good run is over 24 hours old).
Duty for the UK, the EU and Australia does not depend on where the goods were made, so every covered origin is covered for every covered destination.
"""
from __future__ import annotations

from datetime import UTC, datetime

from landfall_register import repo
from sqlalchemy import Connection, text

from .. import schemas as s
from .health import PAUSE, STALE, last_success

ORIGIN_NAMES = {"GB": "United Kingdom", "IN": "India", "EU": "European Union", "CN": "China", "VN": "Vietnam", "TR": "Türkiye", "TH": "Thailand", "ID": "Indonesia",
                "BD": "Bangladesh", "PK": "Pakistan", "JP": "Japan", "KR": "South Korea"}
DESTINATIONS = [
    ("US", "United States", None),
    ("GB", "United Kingdom", None),
    ("EU", "European Union (27 states)", None),
    ("AU", "Australia", "Rates are a hand-curated table, to be confirmed by a customs broker before real use."),
]
NIGHTLY = "Every night, 02:00 UTC"
# id, name, what it provides, refreshed
SOURCES = [
    ("usitc", "US tariff schedule (USITC)", "US duty rates per tariff line", NIGHTLY),
    ("uk", "UK Trade Tariff", "UK duty and VAT per commodity code", NIGHTLY),
    ("tedb", "EU VAT rates (TEDB)", "VAT for each of the 27 member states", NIGHTLY),
    ("federal_register", "Federal Register notices", "New US tariff notices. A person approves each proposed rule before it is used", NIGHTLY),
]
DISCLAIMER = ("Only what is covered today is listed. Other countries and some kinds of goods are not covered yet and are not shown; adding them is planned for a later phase. "
              "Duties are estimates from published rates for the expected import date, not customs advice.")


def covered_origin_codes(conn: Connection) -> list[str]:
    """The origins Landfall prices for US buyers, by country name: read from the register (coverage rows, minus origins held back for review)."""
    rows = repo.rows_visible(conn, None, "US")
    held = {r["origin_scope"] for r in rows if r["measure"] == "origin_review"}
    return sorted(({r["origin_scope"] for r in rows if r["measure"] == "origin_coverage"} - {"ALL", "*"} - held) & set(ORIGIN_NAMES), key=lambda c: ORIGIN_NAMES[c])


def coverage(conn: Connection, now: datetime | None = None) -> s.Coverage:
    now = now or datetime.now(UTC)
    codes = covered_origin_codes(conn)
    dest_ids = [d[0] for d in DESTINATIONS]
    sources = []
    for sid, name, provides, refreshed in SOURCES:
        ok_at = last_success(conn, sid)
        last = conn.execute(text("SELECT ok, detail FROM source_run WHERE source = :s ORDER BY id DESC LIMIT 1"), {"s": sid}).mappings().first()
        age = None if ok_at is None else now - ok_at
        status = "no_run_yet" if ok_at is None else "paused" if age >= PAUSE else "stale" if age >= STALE else "ok"
        detail = None if last is None else (last["detail"] if last["ok"] else f"Last run failed. {last['detail'] or ''}".strip())
        sources.append(s.CoverageSource(id=sid, name=name, provides=provides, refreshed=refreshed, last_success_at=ok_at, status=status, detail=detail))
    sources.append(s.CoverageSource(id="au_table", name="Australia (curated table)", provides="5% duty above AUD 1,000 and 10% GST", refreshed="By hand: not refreshed automatically",
                                    last_success_at=None, status="manual", detail=None))
    return s.Coverage(
        as_of=now, register_version=repo.version_label(conn, repo.latest_version(conn)),
        destinations=[s.CoverageDestination(id=i, name=n, note=note) for i, n, note in DESTINATIONS],
        origins=[s.CoverageOrigin(code=c, name=ORIGIN_NAMES[c], destinations=dest_ids) for c in codes],
        sources=sources,
        stale_rule=f"No good refresh for {int(STALE.total_seconds() // 3600)} hours: checkout shows 'rates last updated' for that destination.",
        pause_rule=f"No good refresh for {PAUSE.days} days: duties-included is paused for that destination.",
        disclaimer=DISCLAIMER)
