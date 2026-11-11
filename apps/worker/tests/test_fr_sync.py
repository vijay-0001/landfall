"""Federal Register poller: queue AI-drafted rules for review, remember what it has seen, fail safe. Recorded payloads, no network."""
import json
from datetime import date
from pathlib import Path

import pytest
from landfall_api.db import migrate_all
from landfall_register import repo
from landfall_register.db import make_engine
from landfall_worker import sync
from sqlalchemy import text

FIX = Path(__file__).resolve().parents[3] / "packages" / "rules" / "tests" / "fixtures"
DOCS = json.loads((FIX / "fr_list_cbp.json").read_text(encoding="utf-8"))["results"]
TEXT_21600 = (FIX / "2026-21600.txt").read_text(encoding="utf-8")
TODAY = date(2026, 11, 1)
DATE_Q = "The compliance date for 19 CFR 145.12(a)(2)(v) and (vi) is January 20, 2027."


class FakeLLM:
    def __init__(self, relevant_doc="2026-21600", fail_on=None):
        self.relevant_doc, self.fail_on, self.calls = relevant_doc, fail_on, []

    def complete(self, system, user, max_tokens=600):
        title = user.split("\n")[0]
        self.calls.append(title)
        if self.fail_on and self.fail_on in title:
            raise RuntimeError("model unavailable")
        if "Indefinite Suspension" in title:
            blank = {n: {"value": None, "quote": None} for n in ["destination", "code_pattern", "origin_scope", "measure", "rate", "valid_from", "valid_to"]}
            blank["valid_from"] = {"value": "2027-01-20", "quote": DATE_Q}
            blank["measure"] = {"value": "process_requirement", "quote": "mandating the formal entry of merchandise arriving through the international postal network"}
            return json.dumps({"relevant": True, "title": "Formal entry for postal parcels", "fields": blank})
        return json.dumps({"relevant": False})


@pytest.fixture()
def conn():
    eng = make_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    migrate_all()
    with eng.begin() as c:
        repo.new_version(c, "r-seed")
    with eng.connect() as c:
        yield c
        c.rollback()


def list_all(_since):
    return DOCS


def fetch_text(doc):
    return TEXT_21600 if doc["document_number"] == "2026-21600" else "Some other notice text about accreditation."


def run(conn, llm, lister=list_all, fetcher=fetch_text):
    return sync.sync_federal_register(conn, lister, fetcher, llm, TODAY)


def test_relevant_notice_is_queued_with_its_quoted_fields(conn):
    llm = FakeLLM()
    rep = run(conn, llm)
    assert rep.ok and rep.source == "federal_register" and rep.publish == "needs_review" and rep.added == 1 and rep.future_dated == 1
    row = conn.execute(text("SELECT status, payload FROM rule_proposal WHERE notice_doc_number = '2026-21600'")).mappings().one()
    assert row["status"] == "pending" and row["payload"]["valid_from"]["value"] == "2027-01-20"
    assert row["payload"]["valid_from"]["quote"] == DATE_Q and row["payload"]["model"] == "claude-haiku-5-5"
    assert conn.execute(text("SELECT count(*) FROM audit_event WHERE action = 'rule_proposed'")).scalar_one() == 1
    assert not any("accreditation" in c.lower() for c in llm.calls)  # prefilter kept the noise away from the model


def test_second_night_sends_nothing_to_the_model_again(conn):
    run(conn, FakeLLM())
    again = FakeLLM()
    rep = run(conn, again)
    assert again.calls == [] and rep.added == 0 and rep.ok
    assert conn.execute(text("SELECT count(*) FROM rule_proposal WHERE status = 'pending'")).scalar_one() == 1


def test_not_relevant_notices_are_remembered_but_hidden(conn):
    run(conn, FakeLLM())
    skipped = conn.execute(text("SELECT notice_doc_number FROM rule_proposal WHERE status = 'skipped'")).scalars().all()
    assert "2026-21570" in skipped and "2026-21600" not in skipped


def test_notice_already_cited_by_the_register_is_not_queued(conn):
    with make_engine().begin() as c:
        v = repo.new_version(c, "r-cited")
        repo.add_row(c, v, {"destination": "US", "code": "*", "origin_scope": "ALL", "measure": "process_requirement", "rate_kind": "none",
                            "valid_from": date(2027, 1, 20), "source_ref": "FR 2026-21600", "source_url": "https://www.federalregister.gov/d/2026-21600"})
    llm = FakeLLM()
    rep = run(conn, llm)
    assert rep.added == 0
    assert not any("Indefinite Suspension" in c for c in llm.calls)


def test_model_failure_on_one_notice_is_retried_next_night_and_does_not_hide_it(conn):
    rep = run(conn, FakeLLM(fail_on="Indefinite Suspension"))
    assert rep.ok and rep.added == 0 and any("2026-21600" in w for w in rep.warnings)
    assert conn.execute(text("SELECT count(*) FROM rule_proposal WHERE notice_doc_number = '2026-21600'")).scalar_one() == 0
    assert run(conn, FakeLLM()).added == 1


def test_source_down_is_recorded_and_changes_nothing(conn):
    def boom(_):
        raise ConnectionError("federalregister.gov unreachable")
    rep = run(conn, FakeLLM(), lister=boom)
    assert not rep.ok and "fetch failed" in rep.detail
    assert conn.execute(text("SELECT count(*) FROM rule_proposal")).scalar_one() == 0


def test_no_model_key_is_reported_not_silently_skipped(conn):
    rep = run(conn, None)
    assert not rep.ok and "ANTHROPIC_API_KEY" in rep.detail
    sync.record_run(conn, rep)
    assert conn.execute(text("SELECT ok FROM source_run WHERE source = 'federal_register'")).scalar_one() is False
