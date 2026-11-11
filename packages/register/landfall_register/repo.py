"""Register repository: the only place that reads or writes rate rows.

Reading rules (docs/hld.md section 5):
 - Checkout reads with valid date = expected import date and known version = latest published.
 - Time Machine reads valid date = the slider date, known version = latest.
 - Replay reads with the known version locked on the order, so it reproduces what the buyer was charged.
 - A future-dated row is just a row with valid_from in the future.
Rows are never updated in place; a correction closes the old row and adds a new one in a new version.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

ROW_COLUMNS = (
    "id, destination, code, origin_scope, measure, variant, rate_kind, rate, currency, params, valid_from, valid_to, "
    "recorded_in_version, superseded_in_version, source_ref, source_url, note"
)


def _variant(row: dict) -> str:
    p = row.get("params") or {}
    return row.get("variant") or p.get("member_state") or ""


def new_version(conn: Connection, label: str, published_by: str = "system", source_runs: list | None = None, note: str | None = None) -> int:
    return conn.execute(
        text("INSERT INTO register_version (label, published_by, source_runs, note) VALUES (:l, :p, CAST(:s AS jsonb), :n) RETURNING id"),
        {"l": label, "p": published_by, "s": json.dumps(source_runs or []), "n": note},
    ).scalar_one()


def add_row(conn: Connection, version_id: int, row: dict) -> int:
    """Insert one row recorded in `version_id`. Raises if it would overlap validity for the same key."""
    return conn.execute(
        text(
            """
            INSERT INTO rate_row (destination, code, origin_scope, measure, variant, rate_kind, rate, currency, params,
                                  valid_from, valid_to, recorded_in_version, source_ref, source_url, note)
            VALUES (:destination, :code, :origin_scope, :measure, :variant, :rate_kind, :rate, :currency, CAST(:params AS jsonb),
                    :valid_from, :valid_to, :v, :source_ref, :source_url, :note)
            RETURNING id
            """
        ),
        {
            "destination": row["destination"], "code": row["code"], "origin_scope": row["origin_scope"], "measure": row["measure"],
            "variant": _variant(row), "rate_kind": row["rate_kind"], "rate": row.get("rate"), "currency": row.get("currency"),
            "params": json.dumps(row.get("params") or {}), "valid_from": row["valid_from"], "valid_to": row.get("valid_to"),
            "v": version_id, "source_ref": row["source_ref"], "source_url": row.get("source_url"), "note": row.get("note"),
        },
    ).scalar_one()


def add_rows(conn: Connection, version_id: int, rows: list[dict]) -> int:
    """Insert many rows recorded in `version_id` with one statement (a few thousand rows in well under a second)."""
    if not rows:
        return 0
    payload = [{
        "destination": r["destination"], "code": r["code"], "origin_scope": r["origin_scope"], "measure": r["measure"], "variant": _variant(r),
        "rate_kind": r["rate_kind"], "rate": None if r.get("rate") is None else str(r["rate"]), "currency": r.get("currency"), "params": r.get("params") or {},
        "valid_from": r["valid_from"].isoformat() if hasattr(r["valid_from"], "isoformat") else r["valid_from"],
        "valid_to": (r["valid_to"].isoformat() if hasattr(r["valid_to"], "isoformat") else r["valid_to"]) if r.get("valid_to") else None,
        "source_ref": r["source_ref"], "source_url": r.get("source_url"), "note": r.get("note"),
    } for r in rows]
    conn.execute(text("""
        INSERT INTO rate_row (destination, code, origin_scope, measure, variant, rate_kind, rate, currency, params,
                              valid_from, valid_to, recorded_in_version, source_ref, source_url, note)
        SELECT x.destination, x.code, x.origin_scope, x.measure, x.variant, x.rate_kind, x.rate, x.currency, x.params,
               x.valid_from, x.valid_to, :v, x.source_ref, x.source_url, x.note
        FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS x(destination text, code text, origin_scope text, measure text, variant text, rate_kind text,
             rate numeric, currency text, params jsonb, valid_from date, valid_to date, source_ref text, source_url text, note text)
    """), {"v": version_id, "rows": json.dumps(payload)})
    return len(rows)


def supersede(conn: Connection, row_id: int, version_id: int) -> None:
    """Close a row as of `version_id`. The only permitted change to an existing row."""
    n = conn.execute(
        text("UPDATE rate_row SET superseded_in_version = :v, superseded_at = now() WHERE id = :id AND superseded_in_version IS NULL"),
        {"v": version_id, "id": row_id},
    ).rowcount
    if n != 1:
        raise ValueError(f"row {row_id} is not open")


def correct(conn: Connection, row_id: int, version_id: int, **changes: Any) -> int:
    """Correct a row: close the old one and add a replacement carrying the changes. Returns the new row id."""
    old = conn.execute(text(f"SELECT {ROW_COLUMNS} FROM rate_row WHERE id = :id"), {"id": row_id}).mappings().one()
    new = {k: old[k] for k in old.keys() if k not in ("id", "recorded_in_version", "superseded_in_version")}
    new.update(changes)
    supersede(conn, row_id, version_id)
    return add_row(conn, version_id, new)


def latest_version(conn: Connection) -> int | None:
    return conn.execute(text("SELECT max(id) FROM register_version")).scalar_one()


def version_label(conn: Connection, version_id: int) -> str:
    return conn.execute(text("SELECT label FROM register_version WHERE id = :v"), {"v": version_id}).scalar_one()


def version_at(conn: Connection, known_at: datetime) -> int | None:
    """The register version that was current at a moment in time."""
    return conn.execute(text("SELECT max(id) FROM register_version WHERE published_at <= :t"), {"t": known_at}).scalar_one()


def _to_engine(r: dict) -> dict:
    out = dict(r)
    out["id"] = str(r["id"])
    out["rate"] = None if r["rate"] is None else format(Decimal(r["rate"]).normalize(), "f")
    out["valid_from"] = r["valid_from"].isoformat()
    out["valid_to"] = r["valid_to"].isoformat() if r["valid_to"] else None
    return out


def rows_visible(conn: Connection, version: int | None = None, destination: str | None = None,
                 valid_from_le: date | None = None, valid_to_gt: date | None = None, codes: list[str] | None = None,
                 prefix: str | None = None) -> list[dict]:
    """Rows in the register as it stood at `version`, optionally limited to a destination and a validity window."""
    v = version if version is not None else latest_version(conn)
    if v is None:
        return []
    sql = f"""
        SELECT {ROW_COLUMNS} FROM rate_row
        WHERE recorded_in_version <= :v AND (superseded_in_version IS NULL OR superseded_in_version > :v)
          AND (CAST(:dest AS text) IS NULL OR destination = :dest)
          AND (CAST(:le AS date) IS NULL OR valid_from <= :le)
          AND (CAST(:gt AS date) IS NULL OR valid_to IS NULL OR valid_to > :gt)
          AND (CAST(:prefix AS text) IS NULL OR replace(code, '.', '') LIKE CAST(:prefix AS text) || '%')
          AND (CAST(:codes AS text[]) IS NULL OR code = '*' OR EXISTS (SELECT 1 FROM unnest(CAST(:codes AS text[])) AS c(d) WHERE c.d LIKE replace(code, '.', '') || '%'))
        ORDER BY id
    """
    digits = None if codes is None else ["".join(ch for ch in c if ch.isdigit()) for c in codes]
    res = conn.execute(text(sql), {"v": v, "dest": destination, "le": valid_from_le, "gt": valid_to_gt, "codes": digits, "prefix": prefix}).mappings().all()
    return [_to_engine(dict(r)) for r in res]


def rows_for_pricing(conn: Connection, destination: str, import_date: date, version: int | None = None, window_days: int = 5,
                     codes: list[str] | None = None) -> list[dict]:
    """Everything the engine needs for one import date: rows valid on the date plus rows that start inside the straddle window.
    With `codes`, only the rows that can apply to those codes (a prefix of one of them, or the code-less "*" rows) are read."""
    return rows_visible(conn, version, destination, valid_from_le=import_date + timedelta(days=window_days), valid_to_gt=import_date, codes=codes)


def rate_lookup(conn: Connection, destination: str, code: str, origin: str, valid_on: date, version: int | None = None) -> list[dict]:
    """GET /register/rate: rows matching a code (prefix match) and origin on a date, as of a version."""
    digits = "".join(c for c in code if c.isdigit())
    out = []
    for r in rows_visible(conn, version, destination, valid_from_le=valid_on, valid_to_gt=valid_on):
        rc = "".join(c for c in r["code"] if c.isdigit())
        if (r["code"] == "*" or digits.startswith(rc)) and r["origin_scope"] in ("ALL", origin):
            out.append(r)
    return out


def change_rate(conn: Connection, row_id: int, version_id: int, new_rate: str, effective: date, source_ref: str, source_url: str | None = None) -> int:
    """A real change in the law: keep the old rate's history up to `effective` and start the new rate from it.

    Both halves are recorded in `version_id`; the old row is closed (superseded) rather than edited, so replaying an
    earlier version still shows exactly what we knew then.
    """
    old = conn.execute(text(f"SELECT {ROW_COLUMNS} FROM rate_row WHERE id = :id"), {"id": row_id}).mappings().one()
    base = {k: old[k] for k in old.keys() if k not in ("id", "recorded_in_version", "superseded_in_version")}
    supersede(conn, row_id, version_id)
    if old["valid_from"] < effective:
        add_row(conn, version_id, {**base, "valid_to": effective})
    return add_row(conn, version_id, {**base, "rate": new_rate, "valid_from": effective, "valid_to": None,
                                      "source_ref": source_ref, "source_url": source_url or base["source_url"],
                                      "note": f"Rate changed on {effective.isoformat()}"})
