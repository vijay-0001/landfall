"""Origin rows made from the recorded reading of HTS Chapter 99 note 52 (fixtures/hts99/country_rates.json)."""
import json

from landfall_register import loaders, origins, seed


def fx():
    return json.loads((loaders.FIXTURES / "hts99" / "country_rates.json").read_text(encoding="utf-8"))


def rows_for(iso, measure=None):
    return [r for r in origins.rows_from_fixture(fx()) if r["origin_scope"] == iso and (measure is None or r["measure"] == measure)]


def test_each_chosen_origin_has_the_rate_the_note_gives():
    expect = {"VN": "12.5", "TH": "12.5", "TR": "12.5", "ID": "10", "BD": "10", "PK": "10"}
    for iso, rate in expect.items():
        (row,) = rows_for(iso, "additional_duty")
        assert row["rate"] == rate and row["valid_from"] == "2026-07-24" and row["source_ref"]
        assert rows_for(iso, "origin_coverage")


def test_japan_and_korea_are_a_12_5_percent_floor_and_canada_mexico_are_not_priced():
    for iso in ("JP", "KR"):
        (row,) = rows_for(iso, "total_rate_floor")
        assert row["rate"] == "12.5"
    for iso in ("CA", "MX"):
        (row,) = rows_for(iso, "origin_review")
        assert row["params"]["reason"] == "usmca_claim"
        assert not rows_for(iso, "additional_duty")


def test_the_exemption_lists_cover_every_country_and_the_per_country_lists_are_kept():
    allrows = [r for r in origins.rows_from_fixture(fx()) if r["measure"] == "origin_exemption"]
    assert len([r for r in allrows if r["origin_scope"] == "ALL"]) > 1500
    for iso in ("BD", "ID", "GB", "EU"):
        assert any(r["origin_scope"] == iso for r in allrows), iso


def test_the_mug_and_wallet_lines_are_not_exempt_for_the_uk():
    codes = {r["code"] for r in origins.rows_from_fixture(fx()) if r["measure"] == "origin_exemption" and r["origin_scope"] in ("ALL", "GB")}
    assert "6912.00.44" not in codes and "4202.31.60" not in codes


def test_derived_rows_include_china_and_the_new_origins():
    rows = seed.derived_rows()
    scopes = {r["origin_scope"] for r in rows}
    assert {"CN", "VN", "JP", "CA", "ALL"} <= scopes
