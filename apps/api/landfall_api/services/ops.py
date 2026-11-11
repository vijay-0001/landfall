"""Ops console: sync table from source_run, the rule queue. Reads and writes only through the register and landfall_rules."""
from __future__ import annotations

from datetime import UTC, datetime

from landfall_register import repo
from landfall_rules import store
from sqlalchemy import Connection, text

from .. import schemas as s
from . import radar, shipment
from .health import PAUSE, SOURCE_NAMES, STALE, last_success

SOURCE_ORDER = ["usitc", "uk", "tedb", "federal_register"]


def sync_status(conn: Connection, now: datetime | None = None) -> s.SyncStatus:
    now = now or datetime.now(UTC)
    out = []
    for src in SOURCE_ORDER:
        last = conn.execute(text("SELECT ok, rows_changed, future_dated, publish, detail FROM source_run WHERE source = :s ORDER BY id DESC LIMIT 1"),
                            {"s": src}).mappings().first()
        ok_at = last_success(conn, src)
        age = None if ok_at is None else now - ok_at
        health = "paused_7d" if age is None or age >= PAUSE else "stale_48h" if age >= STALE else "ok"
        detail = last["detail"] if last else "No run recorded yet"
        if last and not last["ok"]:
            detail = f"Last run failed. {detail}"
        out.append(s.SourceHealth(id=src, name=SOURCE_NAMES[src], last_success_at=ok_at, rows_changed=last["rows_changed"] if last else 0,
                                  future_dated=last["future_dated"] if last else 0,
                                  publish="needs_review" if src == "federal_register" else "automatic",  # notices always wait for a person
                                  health=health, detail=detail))
    return s.SyncStatus(register_version=repo.version_label(conn, repo.latest_version(conn)), sources=out, shipment_cross_check=shipment.cross_checks(conn))


def _view(conn: Connection, r: dict, accepted: list[dict]) -> s.RuleProposal:
    p = r["payload"]
    q = lambda n: s.QuotedField(value=(p.get(n) or {}).get("value"), quote=(p.get(n) or {}).get("quote"))  # noqa: E731
    dest, code, scope = ((p.get(n) or {}).get("value") for n in ("destination", "code_pattern", "origin_scope"))
    n = 0
    if dest and code and scope:
        n = sum(1 for a in accepted if radar.matches(a["decision"], store._code(code), scope))  # noqa: SLF001
    return s.RuleProposal(
        id=r["id"], notice_title=p["notice_title"], notice_doc_number=r["notice_doc_number"], notice_url=p["notice_url"],
        notice_published=p["notice_published"], notice_excerpt=p.get("notice_excerpt", ""), destination=q("destination"), code_pattern=q("code_pattern"),
        origin_scope=q("origin_scope"), measure=q("measure"), rate=q("rate"), valid_from=q("valid_from"), valid_to=q("valid_to"),
        products_affected=n, sellers_affected=1 if n else 0, status=r["status"], model=p.get("model", ""), prompt_version=p.get("prompt_version", ""))  # type: ignore[arg-type]


def rules(conn: Connection) -> list[s.RuleProposal]:
    accepted = radar.accepted_products(conn)
    return [_view(conn, r, accepted) for r in store.list_all(conn)]


def act(conn: Connection, rid: str, action: str, edits: dict | None = None) -> s.RuleProposal:
    if action == "reject":
        r = store.reject(conn, rid)
    else:
        r = store.approve(conn, rid, edits if action == "edit" else None)
    return _view(conn, r, radar.accepted_products(conn))
