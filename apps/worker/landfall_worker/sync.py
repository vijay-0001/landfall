"""Nightly sync: fetch -> diff against the register -> validate -> publish a new register version, per official source.

Every source records a source_run row (ok or not, rows changed, future-dated). A source with no success for 48 hours shows
"rates last updated" at checkout; after 7 days duties-included pauses for its destination (see landfall_api.services.health).
Fetchers are injected so contract tests run on recorded payloads and never touch the network.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import httpx
from landfall_register import loaders, repo
from sqlalchemy import Connection, text

UA = "Mozilla/5.0 (compatible; landfall-sync/0.1; +https://example.invalid)"
TEDB_URL = "https://ec.europa.eu/taxation_customs/tedb/ws/"
TEDB_NS = "urn:ec.europa.eu:taxud:tedb:services:v1:IVatRetrievalService"
EU_STATES = ["AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT",
             "NL", "PL", "PT", "RO", "SE", "SI", "SK"]


@dataclass
class Report:
    source: str
    ok: bool = True
    added: int = 0
    changed: int = 0
    future_dated: int = 0
    publish: str = "automatic"
    detail: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def rows_changed(self) -> int:
        return self.added + self.changed


def record_run(conn: Connection, r: Report) -> None:
    conn.execute(text("""INSERT INTO source_run (source, finished_at, ok, rows_changed, future_dated, publish, detail)
                         VALUES (:s, now(), :ok, :n, :f, :p, :d)"""),
                 {"s": r.source, "ok": r.ok, "n": r.rows_changed, "f": r.future_dated, "p": r.publish, "d": r.detail})


def _next_label(conn: Connection) -> str:
    n = conn.execute(text("SELECT count(*) FROM register_version WHERE label LIKE :p"), {"p": f"r-{date.today().isoformat()}.%"}).scalar_one()
    return f"r-{date.today().isoformat()}.{n + 1}"


def _open_rows(conn: Connection, destination: str, measure: str) -> dict[tuple[str, str], dict]:
    return {(r["code"], r["variant"]): r for r in repo.rows_visible(conn, None, destination) if r["measure"] == measure and r["valid_to"] is None}


def _valid(row: dict) -> bool:
    return row["rate"] is not None and Decimal(row["rate"]) >= 0


# ---------------------------------------------------------------- US: USITC HTS
def sync_hts(conn: Connection, fetch_heading: Callable[[str], dict], today: date | None = None) -> Report:
    today = today or date.today()
    rep = Report("usitc")
    try:
        data = {h: fetch_heading(h) for h in _headings(conn)}
    except Exception as e:  # source down: record it, change nothing
        rep.ok, rep.detail = False, f"fetch failed: {str(e)[:160]}"
        return rep
    cur = _open_rows(conn, "US", "base_duty")
    seen: set[str] = set()
    adds, changes = [], []
    for payload in data.values():
        rows, skipped = loaders.hts_rows(payload, seen)
        rep.warnings += skipped
        for row in rows:
            if not _valid(row):
                rep.ok, rep.detail = False, f"validation failed: negative rate on {row['code']}"
                return rep
            old = cur.get((row["code"], ""))
            if old is None:
                adds.append({**row, "valid_from": today, "note": f"New line in the HTS export on {today.isoformat()}"})
            elif Decimal(old["rate"]) != Decimal(row["rate"]):
                changes.append((old, row))
    if not adds and not changes:
        rep.detail = f"No change. {len(rep.warnings)} lines skipped as not pure ad valorem."
        return rep
    v = repo.new_version(conn, _next_label(conn), "system", [{"source": "usitc"}])
    for row in adds:
        repo.add_row(conn, v, row)
    for old, row in changes:
        repo.change_rate(conn, int(old["id"]), v, row["rate"], today, row["source_ref"], row["source_url"])
    rep.added, rep.changed = len(adds), len(changes)
    rep.detail = f"Published {repo.version_label(conn, v)}"
    return rep


def _headings(conn: Connection | None = None) -> list[str]:
    """Headings to refresh: those of accepted products first, then every heading the register already holds (read on first use), then the core list."""
    from landfall_classifier.candidates import HEADINGS

    out: list[str] = []
    if conn is not None:
        try:
            out += [r[0] for r in conn.execute(text("SELECT DISTINCT substr(replace(code, '.', ''), 1, 4) FROM decision WHERE code ~ '^[0-9]'")).all()]
        except Exception:  # the app tables may not exist in a register-only database
            conn.rollback() if hasattr(conn, "rollback") else None
        out += [r[0] for r in conn.execute(text("SELECT DISTINCT substr(code, 1, 4) FROM rate_row WHERE destination = 'US' AND measure = 'base_duty' AND code ~ '^[0-9]{4}[.]'")).all()]
    return list(dict.fromkeys([*out, *HEADINGS]))


def fetch_hts_heading(h: str) -> dict:
    url = f"https://hts.usitc.gov/reststop/exportList?from={h}.00.00&to={h}.99.99&format=JSON&styles=false"
    r = httpx.get(url, headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    return {"fetched": date.today().isoformat(), "source": url, "rows": r.json()}


# ---------------------------------------------------------------- EU: TEDB VAT
def parse_tedb(xml: bytes) -> dict[str, Decimal]:
    from lxml import etree

    root = etree.fromstring(xml)
    ns = {"t": f"{TEDB_NS}:types"}
    out: dict[str, Decimal] = {}
    for res in root.iter(f"{{{ns['t']}}}vatRateResults"):
        if (res.findtext("t:type", namespaces=ns) or "") != "STANDARD":
            continue
        state = res.findtext("t:memberState", namespaces=ns)
        val = res.findtext("t:rate/t:value", namespaces=ns)
        if state and val:
            out[state] = Decimal(val)
    return out


def fetch_tedb(on: date | None = None) -> bytes:
    on = on or date.today()
    states = "".join(f"<ty:isoCode>{s}</ty:isoCode>" for s in EU_STATES)
    body = (f'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:t="{TEDB_NS}" xmlns:ty="{TEDB_NS}:types">'
            f"<soapenv:Body><t:retrieveVatRatesReqMsg><ty:memberStates>{states}</ty:memberStates><ty:situationOn>{on.isoformat()}</ty:situationOn>"
            "</t:retrieveVatRatesReqMsg></soapenv:Body></soapenv:Envelope>")
    r = httpx.post(TEDB_URL, content=body, timeout=60, headers={
        "Content-Type": "text/xml; charset=utf-8", "SOAPAction": f"{TEDB_NS.replace('IVatRetrievalService', 'VatRetrievalService')}/RetrieveVatRates", "User-Agent": UA})
    r.raise_for_status()
    return r.content


def sync_tedb(conn: Connection, fetch: Callable[[], bytes], today: date | None = None) -> Report:
    today = today or date.today()
    rep = Report("tedb")
    try:
        rates = parse_tedb(fetch())
    except Exception as e:
        rep.ok, rep.detail = False, f"fetch failed: {str(e)[:160]}"
        return rep
    if len(rates) < 27:
        rep.ok, rep.detail = False, f"validation failed: expected 27 standard rates, got {len(rates)}"
        return rep
    cur = _open_rows(conn, "EU", "import_vat")
    changes = [(cur[("*", s)], rate) for s, rate in rates.items() if ("*", s) in cur and Decimal(cur[("*", s)]["rate"]) != rate]
    if not changes:
        rep.detail = "No change in 27 standard rates"
        return rep
    v = repo.new_version(conn, _next_label(conn), "system", [{"source": "tedb"}])
    for old, rate in changes:
        repo.change_rate(conn, int(old["id"]), v, str(rate), today, f"EU TEDB standard VAT rate {old['variant']} {rate}%, situation on {today.isoformat()}")
    rep.changed = len(changes)
    rep.detail = f"Published {repo.version_label(conn, v)}"
    return rep


# ---------------------------------------------------------------- UK: Trade Tariff
def fetch_uk_commodity(code: str) -> dict:
    r = httpx.get(f"https://www.trade-tariff.service.gov.uk/api/v2/commodities/{code}", headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    time.sleep(0.3)  # stay under the rate limit
    return r.json()


def uk_third_country_rate(payload: dict) -> Decimal | None:
    inc = {(i["type"], i["id"]): i for i in payload["included"]}
    for m in payload["included"]:
        if m["type"] != "measure":
            continue
        mt = inc.get(("measure_type", m["relationships"]["measure_type"]["data"]["id"]), {}).get("attributes", {}).get("description")
        if mt == "Third country duty" and m["relationships"]["geographical_area"]["data"]["id"] == "1011":
            de = inc.get(("duty_expression", m["relationships"]["duty_expression"]["data"]["id"]), {}).get("attributes", {})
            return loaders.parse_general_rate((de.get("base") or "").replace(" ", ""))
    return None


def sync_uk(conn: Connection, fetch: Callable[[str], dict], today: date | None = None) -> Report:
    today = today or date.today()
    rep = Report("uk")
    cur = _open_rows(conn, "GB", "base_duty")
    changes = []
    try:
        for (code, _), row in cur.items():
            rate = uk_third_country_rate(fetch(code))
            if rate is not None and rate != Decimal(row["rate"]):
                changes.append((row, rate))
    except Exception as e:
        rep.ok, rep.detail = False, f"fetch failed: {str(e)[:160]}"
        return rep
    if not changes:
        rep.detail = f"No change across {len(cur)} commodities"
        return rep
    v = repo.new_version(conn, _next_label(conn), "system", [{"source": "uk"}])
    for old, rate in changes:
        repo.change_rate(conn, int(old["id"]), v, str(rate), today, f"UK Trade Tariff commodity {old['code']}, Third country duty {rate}%, read {today.isoformat()}")
    rep.changed = len(changes)
    rep.detail = f"Published {repo.version_label(conn, v)}"
    return rep


# ---------------------------------------------------------------- US: Federal Register notices -> rule proposals
LOOKBACK_DAYS = 30


def sync_federal_register(conn: Connection, list_recent: Callable[[date], list[dict]], fetch_text: Callable[[dict], str], llm,
                          today: date | None = None) -> Report:
    """New USTR, CBP and presidential trade notices -> Haiku drafts the rule form -> queued for ops. Nothing is published here.

    A notice is sent to the model once: it is either queued, or remembered as not relevant. A model failure on one notice
    leaves it unseen so the next night retries it.
    """
    from landfall_rules import federal_register as fr
    from landfall_rules import store
    from landfall_rules.draft import draft_rule

    today = today or date.today()
    rep = Report("federal_register", publish="needs_review")
    if llm is None:
        rep.ok, rep.detail = False, "ANTHROPIC_API_KEY is not configured, so notices cannot be drafted"
        return rep
    try:
        docs = list_recent(today - timedelta(days=LOOKBACK_DAYS))
    except Exception as e:
        rep.ok, rep.detail = False, f"fetch failed: {str(e)[:160]}"
        return rep
    seen = 0
    for doc in docs:
        n = doc["document_number"]
        if not fr.is_candidate(doc) or store.known(conn, n) or store.already_in_register(conn, n):
            continue
        seen += 1
        try:
            body = fetch_text(doc)
            draft = draft_rule(llm, doc["title"], body)
        except Exception as e:  # unusable reply or source hiccup: leave it unseen, retry tomorrow
            rep.warnings.append(f"{n}: {str(e)[:120]}")
            continue
        if not draft.relevant:
            store.mark_skipped(conn, doc)
            continue
        if store.insert_proposal(conn, doc, body, draft):
            rep.added += 1
            vf = (draft.fields.get("valid_from") or {}).get("value")
            rep.future_dated += bool(vf and date.fromisoformat(vf) > today)
    rep.detail = f"{len(docs)} notices listed, {seen} new to read, {rep.added} queued for review" + (f", {len(rep.warnings)} to retry" if rep.warnings else "")
    return rep


def _llm():
    from landfall_classifier.model import HaikuClient

    key = os.environ.get("ANTHROPIC_API_KEY")
    return HaikuClient(key) if key else None


def run_all(engine, today: date | None = None) -> list[Report]:
    """One nightly pass. Each source runs in its own transaction so one failure never blocks the others."""
    out: list[Report] = []
    from landfall_rules import federal_register as fr

    for fn in (lambda c: sync_hts(c, fetch_hts_heading, today), lambda c: sync_tedb(c, fetch_tedb, today), lambda c: sync_uk(c, fetch_uk_commodity, today),
               lambda c: sync_federal_register(c, fr.list_recent, fr.fetch_text, _llm(), today)):
        with engine.begin() as conn:
            rep = fn(conn)
            record_run(conn, rep)
            out.append(rep)
    print(json.dumps([{"source": r.source, "ok": r.ok, "changed": r.rows_changed, "detail": r.detail} for r in out]), flush=True)
    return out
