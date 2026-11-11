"""Source health fail-safes (FR-35): 48 h without a good sync shows "rates last updated" at checkout for that destination;
7 days pauses duties-included there. Reads source_run only; no network."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, text

STALE = timedelta(hours=48)
PAUSE = timedelta(days=7)
SOURCES_BY_DEST = {"US": ["usitc"], "GB": ["uk"], "EU": ["tedb"], "AU": [], "CA": []}  # AU and CA are curated tables with no feed to go stale
SOURCE_NAMES = {"usitc": "US tariff schedule (USITC)", "federal_register": "Federal Register notices", "tedb": "EU VAT rates (TEDB)",
                "uk": "UK Trade Tariff API", "taric": "EU TARIC daily file"}
DEST_NAME = {"US": "the United States", "GB": "the United Kingdom", "EU": "the European Union", "AU": "Australia", "CA": "Canada"}


@dataclass
class DestHealth:
    stale_note: str | None
    paused_reason: str | None


def last_success(conn: Connection, source: str) -> datetime | None:
    return conn.execute(text("SELECT max(finished_at) FROM source_run WHERE source = :s AND ok"), {"s": source}).scalar_one()


def destination_health(conn: Connection, dest: str, now: datetime | None = None) -> DestHealth:
    now = now or datetime.now(UTC)
    worst: timedelta | None = None
    if not SOURCES_BY_DEST[dest]:
        return DestHealth(None, None)
    for src in SOURCES_BY_DEST[dest]:
        last = last_success(conn, src)
        age = timedelta.max if last is None else now - last
        worst = age if worst is None or age > worst else worst
    if worst is None or worst >= PAUSE:
        return DestHealth(None, f"Duties-included is paused for {DEST_NAME[dest]} while we refresh rates. Duties may be due on delivery.")
    if worst >= STALE:
        return DestHealth(f"Rates last updated {int(worst.total_seconds() // 3600)} hours ago for {DEST_NAME[dest]}.", None)
    return DestHealth(None, None)


def seed_initial_runs(conn: Connection) -> None:
    """The first load of the register counts as a successful sync of each source, so a fresh install is not 'stale'."""
    if conn.execute(text("SELECT count(*) FROM source_run")).scalar_one():
        return
    for src in ("usitc", "uk", "tedb", "federal_register"):
        conn.execute(text("INSERT INTO source_run (source, finished_at, ok, rows_changed, publish, detail) VALUES (:s, now(), true, 0, 'automatic', 'Initial load from recorded official sources')"), {"s": src})
