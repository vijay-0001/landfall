"""China origin rows: built from the recorded reading of the official HTS Chapter 99 (note 20 lists, note 52 exemptions)."""
import json

from landfall_register import china, loaders

SMALL = {
    "source": "HTS Revision 22 (2026), Chapter 99", "source_url": "https://hts.usitc.gov/reststop/file?release=currentRelease&filename=Chapter%2099",
    "legacy_section_301": {
        "list3": {"hts_heading": "9903.88.03", "rate": "25", "note": "(f)", "codes": ["4202.31.60"]},
        "list4a": {"hts_heading": "9903.88.15", "rate": "7.5", "note": "(s)(i)", "codes": ["6912.00.44"]},
    },
    "exclusions_in_force": {"vvv": {"hts_heading": "9903.88.69", "valid_to": "2026-11-10", "codes": ["4202.92.3120", "4202.92.3131"]},
                            "www": {"hts_heading": "9903.88.70", "valid_to": None, "codes": ["6110.20.20"]}},
    "section_301_12_5": {"hts_heading": "9903.05.31", "rate": "12.5", "effective": "2026-07-24", "federal_register": "2026-15181", "exempt_lines_in_our_headings": []},
}


def by(rows, **kw):
    return [r for r in rows if all(r.get(k) == v for k, v in kw.items())]


def test_rows_are_built_with_sources_and_the_right_rates():
    rows = china.rows_from_fixture(SMALL)
    cov = by(rows, measure="origin_coverage")
    assert len(cov) == 1 and cov[0]["origin_scope"] == "CN" and cov[0]["valid_from"] == "2026-02-24"
    l3 = by(rows, measure="additional_duty", code="4202.31.60")[0]
    assert l3["rate"] == "25" and l3["origin_scope"] == "CN" and l3["params"]["hts_heading"] == "9903.88.03" and "note 20(f)" in l3["source_ref"]
    l4 = by(rows, measure="additional_duty", code="6912.00.44")[0]
    assert l4["rate"] == "7.5" and l4["params"]["hts_heading"] == "9903.88.15"
    new = by(rows, measure="additional_duty", code="*")[0]
    assert new["rate"] == "12.5" and new["valid_from"] == "2026-07-24" and "9903.05.31" in new["source_ref"] and new["source_url"].endswith("2026-15181")
    # one review row per 8-digit line that has an exclusion on a statistical suffix, ending when the exclusion does
    ex = by(rows, measure="exclusion_review")
    assert {r["code"] for r in ex} == {"4202.92.31", "6110.20.20"}
    assert by(ex, code="4202.92.31")[0]["valid_to"] == "2026-11-10" and by(ex, code="6110.20.20")[0]["valid_to"] is None
    assert all(r["source_ref"] and r["destination"] == "US" and r["origin_scope"] == "CN" for r in rows)
    assert len({r["id"] for r in rows}) == len(rows)  # unique ids


def test_a_line_on_two_lists_is_charged_once_at_the_higher_list_rate():
    two = json.loads(json.dumps(SMALL))
    two["legacy_section_301"]["list1"] = {"hts_heading": "9903.88.01", "rate": "25", "note": "(b)", "codes": ["4202.31.60"]}
    rows = china.rows_from_fixture(two)
    assert len(by(rows, measure="additional_duty", code="4202.31.60")) == 1


def test_the_recorded_reading_is_consistent_and_no_priced_line_is_exempt():
    fixture = json.loads((loaders.FIXTURES / "hts99" / "china_s301.json").read_text(encoding="utf-8"))
    assert fixture["section_301_12_5"]["hts_heading"] == "9903.05.31"
    from landfall_register import origins, seed

    assert "4202.31.60" not in fixture["section_301_12_5"]["exempt_lines_in_our_headings"]  # the wallet line is not exempt
    data = seed.derived_rows()
    assert len(by(data, measure="additional_duty", origin_scope="CN")) > 1000  # the whole tariff's legacy lists, read from the recorded Chapter 99
    exempt = {r["code"] for r in data if r["measure"] == "origin_exemption" and r["origin_scope"] == "ALL"}
    assert {origins._line8(c) for c in fixture["section_301_12_5"]["exempt_lines_in_our_headings"]} <= exempt  # every exempt line is switched off
