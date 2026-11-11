"""Origin rows for the US register, built from a recorded reading of the country duty headings (HTS Chapter 99, U.S. note 52).

Each priced origin gets: coverage (from 24 Feb 2026, like India, the EU and China), its additional rate or total-rate floor from 24 Jul 2026
(Federal Register 2026-15181), and the exemption lists that switch that duty off for a line (every country, and per country). Canada and Mexico
goods that qualify under USMCA are exempt; the register cannot tell, so those origins are refused with a plain reason instead of priced.
Countries already curated by hand (UK, India, EU, China) are not repeated here, only their exemption lists.
"""
from __future__ import annotations

COVERAGE_START = "2026-02-24"
EFFECTIVE = "2026-07-24"
HTS_URL = "https://hts.usitc.gov/search?query="
PRICED = {"VN", "TR", "TH", "ID", "BD", "PK", "JP", "KR"}
REVIEW = {"CA", "MX"}
LISTED_HEADING = {"GB": "9903.05.96", "EU": "9903.05.97", "BD": "9903.06.12", "ID": "9903.06.16"}


def _line8(code: str) -> str:
    d = code.replace(".", "")
    return f"{d[:4]}.{d[4:6]}.{d[6:8]}"


def _row(id_: str, code: str, scope: str, measure: str, rate: str | None, valid_from: str, source_ref: str, params: dict, url: str | None = None, note: str = "") -> dict:
    return {"id": id_, "destination": "US", "code": code, "origin_scope": scope, "measure": measure, "rate_kind": "percent" if rate is not None else "none",
            "rate": rate, "currency": None, "params": params, "valid_from": valid_from, "valid_to": None, "source_ref": source_ref, "source_url": url, "note": note}


def rows_from_fixture(fx: dict) -> list[dict]:
    src = fx["source"]
    rows: list[dict] = []
    for c in fx["countries"]:
        iso, head = c["iso"], c["heading"]
        if iso in PRICED:
            if not any(r["id"] == f"us-cov-{iso.lower()}" for r in rows):  # Japan and Korea have two headings (column 1 at or above / below the floor)
                rows.append(_row(f"us-cov-{iso.lower()}", "*", iso, "origin_coverage", None, COVERAGE_START,
                                 f"Register coverage: {c['name']} origin from 24 Feb 2026 (Section 122, then the country duty of U.S. note 52); earlier history is not curated", {},
                                 note="Prices before this date are not shown for this origin."))
            if c["floor"]:  # Japan, South Korea: the total rate is at least the floor (column 1 at or above it: no change)
                heads = [f"9903.05.{int(head[-2:]) - 1:02d}", head] if c["floor_applies_below_column_1"] else [head, f"9903.05.{int(head[-2:]) + 1:02d}"]
                rows.append(_row(f"us-s301-{iso.lower()}-floor", "*", iso, "total_rate_floor", c["floor"], EFFECTIVE,
                                 f"{src}: headings {heads[0]} and {heads[1]} (column 1 below {c['floor']}%: total {c['floor']}%; at or above: no change), "
                                 f"articles the product of {c['name']}; Federal Register 2026-15181", {"hts_headings": heads, "basis": "Section 301 (forced-labor investigations)"},
                                 HTS_URL + heads[0]))
            elif c["additional"]:
                rows.append(_row(f"us-s301-{iso.lower()}", "*", iso, "additional_duty", c["additional"], EFFECTIVE,
                                 f"{src}: heading {head} 'The duty provided in the applicable subheading + {c['additional']}%', articles the product of {c['name']}; Federal Register 2026-15181",
                                 {"hts_heading": head, "stacks_on_base": True, "basis": "Section 301 (forced-labor investigations)"}, HTS_URL + head))
        elif iso in REVIEW:
            sub = "(g)" if iso == "CA" else "(h)"
            rows.append(_row(f"us-cov-{iso.lower()}", "*", iso, "origin_coverage", None, COVERAGE_START, f"Register coverage: {c['name']} origin (USMCA claim not known)", {}))
            rows.append(_row(f"us-usmca-{iso.lower()}", "*", iso, "origin_review", None, EFFECTIVE,
                             f"{src}: heading {head} applies to {c['name']} goods except those entered free under USMCA (note 52 {sub})",
                             {"reason": "usmca_claim", "hts_heading": f"9903.05.{93 if iso == 'CA' else 94}"}, HTS_URL + head,
                             note="Whether the goods qualify under USMCA is not known from the listing, so the duty is not priced."))
    for code in fx["exempt_all_countries"]:
        line = _line8(code)
        rows.append(_row(f"us-n52-all-{line.replace('.', '')}", line, "ALL", "origin_exemption", None, EFFECTIVE,
                         f"HTS Rev 22 note 52(b) to (f): the country duties do not apply to {line}", {"hts_heading": "9903.05.86"}))
    for iso, lines in fx["exempt_by_country"].items():
        for code in lines:
            line = _line8(code)
            rows.append(_row(f"us-n52-{iso.lower()}-{line.replace('.', '')}", line, iso, "origin_exemption", None, EFFECTIVE,
                             f"HTS Rev 22 note 52 per-country list (heading {LISTED_HEADING.get(iso, '9903.06')}): no country duty on {line} of {iso}",
                             {"hts_heading": LISTED_HEADING.get(iso, "9903.06")}))
    return rows
