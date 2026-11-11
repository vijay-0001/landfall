"""One-off dev tool: read the country duty headings (9903.05.20 to 9903.05.84) and the U.S. note 52 exemption lists from the official HTS Chapter 99.

    pip install pypdf --target SCRATCH      # dev only (BSD); never into the repo
    PYTHONPATH=SCRATCH python tools/extract_origins.py CHAPTER99.pdf_or_text

Source: https://hts.usitc.gov/reststop/file?release=currentRelease&filename=Chapter%2099 (Revision 22, 2026). Reads as text:
  - the country heading table: country, heading, additional rate, and for Japan and South Korea the 12.5 percent total-rate floor
  - note 52(b) to (f): exemption lists that apply to every country
  - note 52(g) / (h): Canada and Mexico goods entered free under USMCA are exempt (the register cannot tell, so it refuses to price those)
  - the per-country exemption lists (note 52(j) and the 9903.06 headings) for Bangladesh, Indonesia, the United Kingdom and the EU
Tests never run this; they read the recorded fixture (fixtures/hts99/country_rates.json) and the rows made from it (data/us_origins.json).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = re.compile(r"\d{4}\.\d{2}\.\d{2}")
ISO = {"Vietnam": "VN", "Mexico": "MX", "Canada": "CA", "Japan": "JP", "South Korea": "KR", "Thailand": "TH", "Indonesia": "ID", "Bangladesh": "BD", "Pakistan": "PK",
       "India": "IN", "the United Kingdom": "GB", "United Kingdom": "GB", "China": "CN", "Türkiye": "TR", "Taiwan": "TW"}


def load_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        import pypdf

        return "\n\f".join((p.extract_text() or "") for p in pypdf.PdfReader(str(path)).pages)
    return path.read_text(encoding="utf-8")


def countries(raw: str) -> list[dict]:
    a = raw.find("Except for products described in headings\n9903.05.85")
    txt = " ".join(raw[a - 200:a + 90000].split())
    out = []
    for m in re.finditer(r"articles the product of (.+?), as provided for in U\.S\. note 52.*?\.{2,}\s*1?/?(9903\.05\.\d\d)(.*?)(?=Except for products|\Z)", txt):
        name, head, rest = m.group(1), m.group(2), m.group(3)
        name = re.sub(r"T.rkiye", "Türkiye", name)
        iso = ISO.get(name.split(",")[0])
        if iso is None:
            continue
        add = re.findall(r"\+\s*([\d.]+)%", rest[:400])
        floor = re.search(r"No change\s*([\d.]+)%", rest[:200])
        out.append({"iso": iso, "heading": head, "name": name.split(",")[0], "additional": add[0] if add else None, "floor": floor.group(1) if floor else None,
                    "floor_applies_below_column_1": "less than" in name})
    return out


def codes(seg: str) -> list[str]:
    return sorted(set(CODE.findall(seg)))


def main(src: Path) -> None:
    raw = load_text(src)
    start = raw.find("(b) As provided in heading 9903.05.86")
    end = raw.find("(g) As provided in heading 9903.05.93", start)
    general = codes(raw[start:end])
    percountry: dict[str, list[str]] = {}
    seg = raw[start:raw.find("(k) As provided in headings", start)]
    pat = (r"As provided in heading (9903\.0\d\.\d\d), the dut(?:y|ies) imposed by headings? (.*?) shall not apply to articles\s+the product\s+of (.+?) "
           r"that are classifiable in the following provisions of the HTSUS:(.*?)(?=As provided in heading|\n\([ivx]+\) |\Z)")
    for m in re.finditer(pat, seg, re.S):
        name = " ".join(m.group(3).split())
        iso = "EU" if "European Union" in name else ISO.get(name)
        if iso:
            percountry.setdefault(iso, []).extend(codes(m.group(4)))
    extra = {"BD": ["1211.90.89", "1515.90.81"], "ID": ["1302.19.91"]}  # the "particular articles" lines (9903.06.13 and 9903.06.17)
    for k, v in extra.items():
        percountry.setdefault(k, []).extend(v)
    fixture = {"source": "HTS Revision 22 (2026), Chapter 99, subchapter III U.S. note 52",
               "source_url": "https://hts.usitc.gov/reststop/file?release=currentRelease&filename=Chapter%2099",
               "read_on": date.today().isoformat(), "countries": countries(raw), "exempt_all_countries": general,
               "exempt_by_country": {k: sorted(set(v)) for k, v in percountry.items()}, "usmca": {"CA": "9903.05.93", "MX": "9903.05.94"}}
    out = ROOT / "packages/register/fixtures/hts99/country_rates.json"
    out.write_text(json.dumps(fixture, indent=1, ensure_ascii=False), encoding="utf-8")
    sys.path.insert(0, str(ROOT / "packages" / "register"))
    from landfall_register.origins import rows_from_fixture

    rows = rows_from_fixture(fixture)
    (ROOT / "packages/register/data/us_origins.json").write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print({c["iso"]: (c["heading"], c["additional"], c["floor"]) for c in fixture["countries"]}, "exempt_all:", len(general),
          {k: len(v) for k, v in fixture["exempt_by_country"].items()}, "rows:", len(rows))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
