"""Seed the register from recorded official-source data. Idempotent: does nothing if a version already exists."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import Connection, text

from . import china, loaders, origins, repo
from .db import make_engine, migrate


def derived_rows() -> list[dict]:
    """Rows built from the recorded Chapter 99 readings (China lists and exclusions, the country duties and exemption lists of note 52). They are not stored
    as data files: the readings are the source, the rows are made from them."""
    out: list[dict] = []
    f = loaders.FIXTURES / "hts99" / "china_s301.json"
    if f.exists():
        out += china.rows_from_fixture(json.loads(f.read_text(encoding="utf-8")))
    f = loaders.FIXTURES / "hts99" / "country_rates.json"
    if f.exists():
        out += origins.rows_from_fixture(json.loads(f.read_text(encoding="utf-8")))
    return out


def _key(r: dict) -> tuple:
    return (r["destination"], r["code"], r["origin_scope"], r["measure"], str(r["valid_from"]))


def seed_register(conn: Connection, label: str | None = None, extra_curated: list[Path] | None = None) -> tuple[int, list[loaders.LoadReport]]:
    if repo.latest_version(conn) is not None:
        return repo.latest_version(conn), []
    label = label or f"r-{date.today().isoformat()}.1"
    v = repo.new_version(conn, label, "system", note="Initial load from recorded official sources")
    reports = [
        loaders.load_usitc_headings(conn, v),
        loaders.load_uk_commodities(conn, v),
        loaders.load_tedb_vat(conn, v),
        loaders.load_curated(conn, v, loaders.DATA / "curated_rows.json"),
    ]
    for p in [*(extra_curated or []), *sorted(loaders.DATA.glob("us_*.json")), loaders.DATA / "au_rows.json"]:
        reports.append(loaders.load_curated(conn, v, p))
    rows = derived_rows()
    repo.add_rows(conn, v, rows)
    reports.append(loaders.LoadReport("Chapter 99 readings (China, country duties, exemptions)", rows_added=len(rows)))
    return v, reports


def ensure_rows(conn: Connection, rows: list[dict], note: str, label: str | None = None) -> int:
    """Add rows that are not in the register yet, in one new register version. Returns rows added.

    Safe to run on every start: a row already present (same key, same valid_from, still open) is skipped, and no version is created when nothing is
    missing. Nothing existing is ever changed.
    """
    if not rows:
        return 0
    have = {(d, c, o, m, str(vf)) for d, c, o, m, vf in conn.execute(
        text("SELECT destination, code, origin_scope, measure, valid_from FROM rate_row WHERE superseded_in_version IS NULL AND destination = ANY(CAST(:ds AS text[]))"),
        {"ds": sorted({r["destination"] for r in rows})}).all()}
    missing = [r for r in rows if _key(r) not in have]
    if not missing:
        return 0
    if label is None:
        n = conn.execute(text("SELECT count(*) FROM register_version WHERE label LIKE :p"), {"p": f"r-{date.today().isoformat()}.%"}).scalar_one()
        label = f"r-{date.today().isoformat()}.{n + 1}"
    v = repo.new_version(conn, label, "system", note=note)
    return repo.add_rows(conn, v, missing)


def ensure_curated(conn: Connection, path: Path, label: str | None = None) -> int:
    """Curated rows from a data file that are not in the register yet (see ensure_rows)."""
    return ensure_rows(conn, json.loads(path.read_text(encoding="utf-8")), f"Curated rows from {path.name}", label)


def ensure_derived(conn: Connection) -> int:
    """The China and country-duty rows made from the recorded Chapter 99 readings, for registers seeded before they existed."""
    return ensure_rows(conn, derived_rows(), "Rows from the Chapter 99 readings (China, country duties, exemptions)")


def main() -> None:
    migrate()
    eng = make_engine()
    with eng.begin() as conn:
        v, reports = seed_register(conn)
    print(f"register version {v}")
    for r in reports:
        print(f"  {r.source}: {r.rows_added} rows, {len(r.skipped)} skipped")
    sys.exit(0)


if __name__ == "__main__":
    main()
