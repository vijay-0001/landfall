"""Rule proposals in the database: queue, approve, edit, reject, every step audited.

Approving writes one future-dated (or current) row into the register in a new register version. Rows already in the register
are never edited: a rate change closes the old row and starts the new one (repo.change_rate). Rule Radar reads the register,
so an approved rule appears there with no extra step.
"""
from __future__ import annotations

import json
import secrets
from datetime import date

from landfall_register import repo
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from .draft import FIELD_NAMES, Draft

DEST_CURRENCY = {"US": "USD", "GB": "GBP", "EU": "EUR"}
RATE_MEASURES = {"additional_duty", "base_duty", "total_rate_floor", "low_value_relief"}
REQUIRED = ["destination", "code_pattern", "origin_scope", "measure", "valid_from"]
LABELS = {"destination": "Destination", "code_pattern": "Codes covered", "origin_scope": "Origins", "measure": "Change", "rate": "Rate",
          "valid_from": "Effective from", "valid_to": "Effective to"}
OPS = "ops:reviewer"


def audit(conn: Connection, actor: str, action: str, entity_id: str, payload: dict | None = None) -> None:
    conn.execute(text("INSERT INTO audit_event (actor, action, entity, entity_id, payload) VALUES (:a, :ac, 'rule_proposal', :i, CAST(:p AS jsonb))"),
                 {"a": actor, "ac": action, "i": entity_id, "p": json.dumps(payload or {})})


def already_in_register(conn: Connection, doc_number: str) -> bool:
    """True when a register row already cites this notice, so the poller does not queue it again."""
    pat = f"%{doc_number}%"
    return conn.execute(text("SELECT 1 FROM rate_row WHERE source_url LIKE :p OR source_ref LIKE :p LIMIT 1"), {"p": pat}).first() is not None


def known(conn: Connection, doc_number: str) -> bool:
    return conn.execute(text("SELECT 1 FROM rule_proposal WHERE notice_doc_number = :d"), {"d": doc_number}).first() is not None


def insert_proposal(conn: Connection, doc: dict, text_body: str, draft: Draft) -> str | None:
    """Queue a drafted rule. Returns the id, or None if this notice is already queued."""
    pid = "rp_" + secrets.token_hex(5)
    excerpt = _excerpt(text_body, draft)
    payload = {
        "notice_title": doc["title"], "notice_url": doc["html_url"], "notice_published": doc["publication_date"], "notice_excerpt": excerpt,
        **{n: draft.fields.get(n, {"value": None, "quote": None}) for n in FIELD_NAMES},
        "model": draft.model, "prompt_version": draft.prompt_version, "dropped": draft.dropped, "short_title": draft.title,
    }
    n = conn.execute(text("""INSERT INTO rule_proposal (id, payload, notice_doc_number) VALUES (:i, CAST(:p AS jsonb), :d)
                             ON CONFLICT (notice_doc_number) DO NOTHING"""), {"i": pid, "p": json.dumps(payload), "d": doc["document_number"]}).rowcount
    if n:
        audit(conn, "worker:federal_register", "rule_proposed", pid, {"notice": doc["document_number"], "model": draft.model, "dropped": draft.dropped})
        return pid
    return None


def mark_skipped(conn: Connection, doc: dict) -> None:
    """Remember a notice the model judged not relevant, so it is never sent to the model again. Hidden from ops."""
    payload = {"notice_title": doc["title"], "notice_url": doc["html_url"], "notice_published": doc["publication_date"]}
    conn.execute(text("INSERT INTO rule_proposal (id, payload, status, notice_doc_number) VALUES (:i, CAST(:p AS jsonb), 'skipped', :d) "
                      "ON CONFLICT (notice_doc_number) DO NOTHING"), {"i": "rp_" + secrets.token_hex(5), "p": json.dumps(payload), "d": doc["document_number"]})


def _excerpt(body: str, draft: Draft) -> str:
    """The sentence the model quoted for the effective date or the measure, else the start of the notice's summary."""
    for name in ("valid_from", "measure", "rate", "destination"):
        q = (draft.fields.get(name) or {}).get("quote")
        if q:
            return q
    flat = " ".join(body.split())
    i = flat.find("SUMMARY:")
    return (flat[i + 8:i + 520] if i >= 0 else flat[:500]).strip()


def get(conn: Connection, rid: str) -> dict:
    r = conn.execute(text("SELECT * FROM rule_proposal WHERE id = :i"), {"i": rid}).mappings().first()
    if r is None:
        raise LookupError(rid)
    return dict(r)


def list_all(conn: Connection) -> list[dict]:
    rows = conn.execute(text("SELECT * FROM rule_proposal WHERE reviewer IS DISTINCT FROM 'curated' AND status <> 'skipped' ORDER BY (status = 'pending') DESC, created_at DESC, id")).mappings()
    return [dict(r) for r in rows]


def missing(payload: dict) -> list[str]:
    need = list(REQUIRED) + (["rate"] if (payload.get("measure") or {}).get("value") in RATE_MEASURES else [])
    return [LABELS[n] for n in need if not (payload.get(n) or {}).get("value")]


def _code(pattern: str) -> str:
    return "*" if pattern.strip() == "*" else pattern.replace(".*", "").rstrip(".").strip()


def _row_from(payload: dict, rid: str, doc: str) -> dict:
    v = lambda n: (payload.get(n) or {}).get("value")  # noqa: E731
    dest, measure = v("destination"), v("measure")
    kind = "none" if measure == "process_requirement" else "fixed" if measure == "low_value_relief" else "percent"
    when = (payload.get("valid_from") or {}).get("quote") or ""
    return {
        "destination": dest, "code": _code(v("code_pattern")), "origin_scope": v("origin_scope"), "measure": measure,
        "rate_kind": kind, "rate": None if kind == "none" else v("rate"), "currency": DEST_CURRENCY[dest] if kind == "fixed" else None,
        "params": {"title": payload["notice_title"], "proposal": rid, **({"stacks_on_base": True} if measure == "additional_duty" else {})},
        "valid_from": date.fromisoformat(v("valid_from")), "valid_to": date.fromisoformat(v("valid_to")) if v("valid_to") else None,
        "source_ref": f"{payload['notice_title']} (FR {doc}). Approved by ops. Source sentence: {when}"[:900],
        "source_url": payload["notice_url"], "note": f"Proposed by {payload.get('model')} ({payload.get('prompt_version')}), approved by ops",
    }


def _open_row(conn: Connection, row: dict) -> dict | None:
    """An open row for the same key that is already valid when the new one starts: the change is a new rate, not a new rule."""
    for r in repo.rows_visible(conn, None, row["destination"]):
        same = (r["code"], r["origin_scope"], r["measure"]) == (row["code"], row["origin_scope"], row["measure"])
        if same and r["valid_to"] is None and date.fromisoformat(r["valid_from"]) < row["valid_from"]:
            return r
    return None


def approve(conn: Connection, rid: str, edits: dict | None = None, actor: str = OPS) -> dict:
    p = get(conn, rid)
    if p["status"] != "pending":
        raise PermissionError(f"This rule is already {p['status']}")
    payload = p["payload"]
    for n, val in (edits or {}).items():
        if n in FIELD_NAMES and val not in (None, ""):
            payload[n] = {"value": str(val).strip(), "quote": "Edited by ops"}
    blanks = missing(payload)
    if blanks:
        raise ValueError("Fill these before approving: " + ", ".join(blanks))
    row = _row_from(payload, rid, p["notice_doc_number"])
    v = repo.new_version(conn, f"r-{date.today().isoformat()}.rule-{p['notice_doc_number']}", actor, [{"source": "rule_proposal", "id": rid}],
                         note=f"Approved rule from {p['notice_doc_number']}")
    try:
        with conn.begin_nested():
            old = _open_row(conn, row) if row["rate_kind"] == "percent" else None
            if old is not None:
                row_id = repo.change_rate(conn, int(old["id"]), v, row["rate"], row["valid_from"], row["source_ref"], row["source_url"])
            else:
                row_id = repo.add_row(conn, v, row)
    except IntegrityError as e:
        raise ValueError("This rule overlaps a row that is already in the register for the same codes and origins") from e
    status = "edited" if edits else "approved"
    conn.execute(text("UPDATE rule_proposal SET status = :s, reviewer = :r, decided_at = now(), payload = CAST(:p AS jsonb) WHERE id = :i"),
                 {"s": status, "r": actor, "p": json.dumps(payload), "i": rid})
    audit(conn, actor, f"rule_{status}", rid, {"register_version": v, "row_id": row_id, "edits": list((edits or {}).keys())})
    return get(conn, rid)


def reject(conn: Connection, rid: str, actor: str = OPS) -> dict:
    p = get(conn, rid)
    if p["status"] != "pending":
        raise PermissionError(f"This rule is already {p['status']}")
    conn.execute(text("UPDATE rule_proposal SET status = 'rejected', reviewer = :r, decided_at = now() WHERE id = :i"), {"r": actor, "i": rid})
    audit(conn, actor, "rule_rejected", rid, {})
    return get(conn, rid)
