"""China origin rows for the US register, built from a recorded reading of the official HTS Chapter 99.

The reading (fixtures/hts99/china_s301.json, made by tools/extract_china_s301.py) holds, for the lines the register prices:
  - the legacy Section 301 lists (note 20(b), (d), (f): 25 percent; note 20(s)(i), List 4A: 7.5 percent);
  - the product exclusions in force (note 20(vvv), (www)), kept as "review" rows: such a line is not priced for China;
  - the 12.5 percent Section 301 action (heading 9903.05.31, FR 2026-15181, from 24 Jul 2026) and the note 52 exemption check.
China is covered from 24 Feb 2026, the day the IEEPA tariffs stopped (EO 14389), the same start as India and the EU. Earlier China
history (the 2025 emergency tariffs and their changes) is not curated and the register says so.
"""
from __future__ import annotations

COVERAGE_START = "2026-02-24"
HTS_URL = "https://hts.usitc.gov/search?query="
SOURCE_NOTE = "HTS Revision 22 (2026), Chapter 99, subchapter III"
LIST_LABEL = {"list1": "Section 301 List 1", "list2": "Section 301 List 2", "list3": "Section 301 List 3", "list4a": "Section 301 List 4A"}


def _line8(code: str) -> str:
    d = code.replace(".", "")
    return f"{d[:4]}.{d[4:6]}.{d[6:8]}"


def rows_from_fixture(fx: dict) -> list[dict]:
    src = fx.get("source", SOURCE_NOTE)
    rows: list[dict] = [{
        "id": "us-cov-cn", "destination": "US", "code": "*", "origin_scope": "CN", "measure": "origin_coverage", "rate_kind": "none", "rate": None,
        "currency": None, "params": {}, "valid_from": COVERAGE_START, "valid_to": None,
        "source_ref": "Register coverage: China origin from 24 Feb 2026 (legacy Section 301 lists, Section 122, the 12.5% Section 301 action); "
                      "earlier China history (2025 emergency tariffs) is not curated",
        "source_url": None, "note": "Prices before this date are not shown for China."}]

    best: dict[str, tuple[float, str, dict]] = {}
    for key, lst in fx["legacy_section_301"].items():
        for code in lst["codes"]:
            line = _line8(code)
            cur = best.get(line)
            if cur is None or float(lst["rate"]) > cur[0]:  # on two lists, the line is charged once, at the higher rate
                best[line] = (float(lst["rate"]), key, lst)
    for line in sorted(best):
        _, key, lst = best[line]
        rows.append({
            "id": f"us-s301-cn-{key}-{line.replace('.', '')}", "destination": "US", "code": line, "origin_scope": "CN", "measure": "additional_duty",
            "rate_kind": "percent", "rate": lst["rate"], "currency": None,
            "params": {"hts_heading": lst["hts_heading"], "list": LIST_LABEL[key], "stacks_on_base": True},
            "valid_from": COVERAGE_START, "valid_to": None,
            "source_ref": f"{src}, U.S. note 20{lst['note']} ({LIST_LABEL[key]}, heading {lst['hts_heading']}): +{lst['rate']}% on subheading {line}, articles the product of China",
            "source_url": HTS_URL + lst["hts_heading"],
            "note": "In force before the register's China start date; shown from the start date only."})

    review: dict[str, tuple[str | None, str]] = {}
    for ex in fx["exclusions_in_force"].values():
        for code in ex["codes"]:
            line = _line8(code)
            have = review.get(line)
            end = ex["valid_to"]
            if have is None:
                review[line] = (end, ex["hts_heading"])
            else:  # an open-ended exclusion on any suffix keeps the line in review; otherwise the later end date
                ends = [have[0], end]
                review[line] = (None if None in ends else max(ends), have[1])
    for line in sorted(review):
        end, heading = review[line]
        rows.append({
            "id": f"us-excl-cn-{line.replace('.', '')}", "destination": "US", "code": line, "origin_scope": "CN", "measure": "exclusion_review",
            "rate_kind": "none", "rate": None, "currency": None, "params": {"hts_heading": heading},
            "valid_from": COVERAGE_START, "valid_to": end,
            "source_ref": f"{src}, U.S. note 20 exclusions in force (heading {heading}): a product exclusion applies to a statistical suffix of {line}",
            "source_url": HTS_URL + heading,
            "note": "Not priced for China until reviewed: the listing cannot tell whether the exclusion applies."})

    n = fx["section_301_12_5"]
    rows.append({
        "id": "us-s301-cn-12-5", "destination": "US", "code": "*", "origin_scope": "CN", "measure": "additional_duty", "rate_kind": "percent", "rate": n["rate"],
        "currency": None, "params": {"hts_heading": n["hts_heading"], "stacks_on_base": True, "basis": "Section 301 (forced-labor investigations)"},
        "valid_from": n["effective"], "valid_to": None,
        "source_ref": f"Federal Register {n['federal_register']} (91 FR 47318, 28 Jul 2026), HTS {n['hts_heading']} 'The duty provided in the applicable subheading + {n['rate']}%', "
                      f"articles the product of China, U.S. note 52; effective 12:01 a.m. ET {n['effective']}",
        "source_url": f"https://www.federalregister.gov/d/{n['federal_register']}",
        "note": "Lines on the note 52 exemption lists are switched off by origin_exemption rows (landfall_register.origins)."})
    return rows
