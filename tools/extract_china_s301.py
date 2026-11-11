"""One-off dev tool: read the China duty lists from the official HTS Chapter 99 (Revision 22, 2026) and record them as data.

    pip install pypdf          # dev only, BSD; not a product dependency
    python tools/extract_china_s301.py CHAPTER99.pdf_or_text [--out-fixture ...] [--out-rows ...]

Source: https://hts.usitc.gov/reststop/file?release=currentRelease&filename=Chapter%2099 (the official Chapter 99 PDF).
What it reads (as text; none of these are images in the HTS):
  - U.S. note 20(b), (d), (f): Section 301 Lists 1, 2 and 3, 25 percent (headings 9903.88.01, .02, .03)
  - U.S. note 20(s)(i): Section 301 List 4A, 7.5 percent (heading 9903.88.15). Lists 4B (note 20(u), 9903.88.16) is suspended and is not applied.
  - U.S. note 20(vvv) and (www): product exclusions in force (headings 9903.88.69 and .70). A line that has an exclusion on any of its
    statistical suffixes is not priced for China (exclusion_review), because the seller cannot tell from the listing whether it applies.
  - U.S. note 52(b) to (f): the exemption lists for the 12.5 percent Section 301 action on China (heading 9903.05.31). None of our lines is on them.
Only lines under the headings the register prices are kept. Tests never run this; they read the recorded fixture.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USITC = ROOT / "packages" / "register" / "fixtures" / "usitc"
SOURCE_URL = "https://hts.usitc.gov/reststop/file?release=currentRelease&filename=Chapter%2099"
# 8-digit lines only: the tables run codes together without a separator ("4202.12.404202.12.29"), and the exclusions are
# recorded to their 8-digit line anyway.
CODE = re.compile(r"\d{4}\.\d{2}\.\d{2}")


def load_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        import pypdf

        r = pypdf.PdfReader(str(path))
        return "\n\f".join((p.extract_text() or "") for p in r.pages)
    return path.read_text(encoding="utf-8")


def our_headings() -> set[str]:
    return {Path(p).stem[4:8] for p in glob.glob(str(USITC / "hts_[0-9][0-9][0-9][0-9].json"))}


def between(raw: str, start_pat: str, end_pat: str, after: int = 0) -> tuple[int, str]:
    s = raw.find(start_pat, after)
    if s < 0:
        raise SystemExit(f"not found: {start_pat!r}")
    e = raw.find(end_pat, s + len(start_pat))
    if e < 0:
        raise SystemExit(f"not found: {end_pat!r}")
    return s, raw[s:e]


def codes_in(seg: str, heads: set[str]) -> list[str]:
    return sorted({c for c in CODE.findall(seg) if c[:4] in heads})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--out-fixture", default=str(ROOT / "packages/register/fixtures/hts99/china_s301.json"))
    ap.add_argument("--out-rows", default=str(ROOT / "packages/register/data/us_china.json"))
    a = ap.parse_args()
    raw = load_text(Path(a.source))
    heads = our_headings()
    n20 = raw.find("(a) For the purposes of heading 9903.88.01")
    n20_end = raw.find("\n21. ", n20)
    note20 = raw[n20:n20_end]
    lists = {}
    for key, (head, rate, start, end) in {
        "list1": ("9903.88.01", "25", "(b) Heading 9903.88.01 applies", "(c) For the purposes of heading 9903.88.02"),
        "list2": ("9903.88.02", "25", "(d) Heading 9903.88.02 applies", "(e) For the purposes of heading 9903.88.03"),
        "list3": ("9903.88.03", "25", "(f) Heading 9903.88.03 applies", "(g) For the purposes of heading 9903.88.04"),
    }.items():
        _, seg = between(note20, start, end)
        lists[key] = {"hts_heading": head, "rate": rate, "note": start[:3], "codes": codes_in(seg, heads)}
    _, s_seg = between(note20, "(s) Heading 9903.88.15 applies to:", "(t) For the purposes of heading 9903.88.16")
    i_end = s_seg.find("(ii) the following products of China")
    lists["list4a"] = {"hts_heading": "9903.88.15", "rate": "7.5", "note": "(s)(i)", "codes": codes_in(s_seg[:i_end], heads)}

    excl: dict[str, dict] = {}
    for tag, heading, ends in (("vvv", "9903.88.69", "2026-11-10"), ("www", "9903.88.70", None)):
        ms = [m.start() for m in re.finditer(rf"\n\({tag}\) (?:\(i\) )?The U\.S\.\s?Trade Representative determined", note20)]
        if not ms:
            raise SystemExit(f"exclusion note ({tag}) not found")
        seg = note20[ms[-1]:]
        if tag == "vvv":  # the exclusion list runs to the start of (www)
            end = re.search(r"\n\(www\) ", seg)
            seg = seg[: end.start()] if end else seg
        excl[tag] = {"hts_heading": heading, "valid_to": ends, "codes": codes_in(seg, heads)}

    n52 = raw.find("(b) As provided in heading 9903.05.86")
    n52_end = raw.find("(g) As provided in heading 9903.05.93", n52)
    exempt = codes_in(raw[n52:n52_end], heads)
    china_heading = re.search(r"articles the product of China, as provided for in U\.S\. note 52 to this subchapter\.+\s*1/(9903\.05\.\d\d)", raw.replace("\n", " "))
    fixture = {
        "source": "HTS Revision 22 (2026), Chapter 99, subchapter III U.S. note 20 and subchapter III U.S. note 52",
        "source_url": SOURCE_URL, "read_on": date.today().isoformat(), "headings_kept": sorted(heads),
        "legacy_section_301": lists, "exclusions_in_force": excl,
        "section_301_12_5": {"hts_heading": china_heading.group(1) if china_heading else None, "rate": "12.5", "effective": "2026-07-24",
                             "federal_register": "2026-15181", "exempt_lines_in_our_headings": exempt},
    }
    Path(a.out_fixture).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out_fixture).write_text(json.dumps(fixture, indent=1), encoding="utf-8")
    sys.path.insert(0, str(ROOT / "packages" / "register"))
    from landfall_register.china import rows_from_fixture

    rows = rows_from_fixture(fixture)
    Path(a.out_rows).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print({k: len(v["codes"]) for k, v in lists.items()}, {k: len(v["codes"]) for k, v in excl.items()}, "exempt hits:", exempt,
          "china heading:", fixture["section_301_12_5"]["hts_heading"], "rows:", len(rows))


if __name__ == "__main__":
    main()
