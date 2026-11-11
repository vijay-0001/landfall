"""How it works (home page copy) is served by the API, with the live register version and the sources actually synced."""
import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_register import repo
from landfall_register.db import make_engine
from sqlalchemy import text


@pytest.fixture(scope="module")
def client():
    eng = make_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    main.cat.llm_client = lambda: None
    with TestClient(main.app) as c:
        yield c


def test_how_it_works_has_five_steps_the_real_sources_and_the_live_register_version(client):
    d = client.get("/api/how-it-works").json()
    assert [s["n"].split(" · ")[0] for s in d["steps"]] == ["01", "02", "03", "04", "05"]
    with make_engine().connect() as c:
        assert d["sample_register_version"] == repo.version_label(c, repo.latest_version(c))
    assert d["sources"] == ["US tariff schedule (USITC)", "UK Trade Tariff API", "EU VAT rates (TEDB)", "Federal Register notices"]
    assert d["powers"] == ["Duties at checkout", "Tariff Time Machine", "Rule Radar", "Passport stamps"]


def test_the_copy_keeps_the_product_rules(client):
    d = client.get("/api/how-it-works").json()
    blob = " ".join([d["ai_note"], d["scope_note"], *(s["title"] + " " + s["body"] for s in d["steps"])]).lower()
    assert "recommends" in d["ai_note"] and "carries no" in d["ai_note"]
    assert "ruling" not in blob and "determination" not in blob  # the AI recommends, never rules
    assert "simulated" in blob  # duty remittance is labelled as simulated
    assert "convert" not in blob or "never convert" in blob  # no currency conversion by us
