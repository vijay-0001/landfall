"""UK commodities on demand: a subheading with no UK rate yet is read from the UK Trade Tariff (recorded fixtures here) and appended
to the register as a new version, only when every 10-digit commodity under the subheading carries the same third-country rate."""
import json
from decimal import Decimal
from pathlib import Path

from landfall_register import loaders, repo, uk_ondemand

FIX = Path(loaders.FIXTURES) / "uk_tariff" / "ondemand"


def recorded(mutate=None):
    """A fake Trade Tariff: serves the recorded heading and commodity responses; `mutate` can change one commodity."""
    calls = []

    def get(path: str) -> dict:
        calls.append(path)
        kind, ident = path.split("/")
        d = json.loads((FIX / f"{'heading' if kind == 'headings' else 'commodity'}_{ident}.json").read_text(encoding="utf-8"))
        if mutate:
            mutate(ident, d)
        return d

    get.calls = calls  # type: ignore[attr-defined]
    return get


def gb_rows(conn, prefix):
    v = repo.latest_version(conn)
    return [r for r in repo.rows_visible(conn, v, "GB") if r["measure"] == "base_duty" and r["code"].startswith(prefix)]


def test_unanimous_subheading_is_loaded_as_a_new_version(conn):
    v0 = repo.new_version(conn, "base", "test")
    loaders.load_uk_commodities(conn, v0)  # the four hand-loaded codes plus the UK VAT row
    assert gb_rows(conn, "610910") == []
    get = recorded()
    out = uk_ondemand.ensure(conn, "6109.10", get)
    assert out.loaded and out.code == "6109100010" and Decimal(out.rate) == 12
    rows = gb_rows(conn, "610910")
    assert len(rows) == 1 and rows[0]["code"] == "6109100010" and float(rows[0]["rate"]) == 12.0
    assert repo.latest_version(conn) > v0  # appended as a new version; nothing was changed in place
    assert "Third country duty" in rows[0]["source_ref"] and rows[0]["source_url"].endswith("/commodities/6109100010")
    assert "same third-country rate" in rows[0]["note"]
    label = repo.version_label(conn, repo.latest_version(conn))
    assert label.startswith("r-") and label.count("-") == 3 and "on-demand" not in label  # the usual r-YYYY-MM-DD.N form buyers see in the fine print
    n = len(get.calls)
    again = uk_ondemand.ensure(conn, "6109.10", get)  # already there: no calls, no new version
    assert not again.loaded and len(get.calls) == n


def test_a_subheading_whose_commodities_differ_in_rate_is_left_unpriced(conn):
    repo.new_version(conn, "base", "test")

    def mutate(ident, d):
        if ident == "6109100090":
            for i in d["included"]:
                if i["type"] == "duty_expression" and "12.00" in (i["attributes"].get("base") or ""):
                    i["attributes"]["base"] = "8.00 %"

    out = uk_ondemand.ensure(conn, "6109.10", recorded(mutate))
    assert not out.loaded and "differ" in out.reason
    assert gb_rows(conn, "610910") == []


def test_a_failed_fetch_changes_nothing(conn):
    v = repo.new_version(conn, "base", "test")

    def boom(path):
        raise OSError("network down")

    out = uk_ondemand.ensure(conn, "6109.10", boom)
    assert not out.loaded and "network down" in out.reason
    assert repo.latest_version(conn) == v
