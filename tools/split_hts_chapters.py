"""One-off dev tool: split recorded whole-chapter USITC exports into per-heading fixtures (the shape the register loader and the
classifier already read), and add every heading and subheading text to headings.json.

    python tools/split_hts_chapters.py DIR_WITH_hts_chNN.json   (made by exportList?from=NN00.00.00&to=NN99.99.99, one file per chapter)

Headings that already have a fixture are left as they are. Tests never run this.
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "packages" / "register" / "fixtures" / "usitc"
SOURCE = "https://hts.usitc.gov/reststop/exportList?from={h}00.00&to={h}99.99 (chapter export, split by heading)"


def main(src: Path) -> None:
    texts = json.loads((OUT / "headings.json").read_text(encoding="utf-8"))["texts"] if (OUT / "headings.json").exists() else {}
    made = kept = 0
    for f in sorted(src.glob("hts_ch*.json")):
        rows = json.loads(f.read_text(encoding="utf-8"))
        by: dict[str, list] = {}
        cur = None
        for r in rows:
            code = (r.get("htsno") or "").strip()
            if len(code) >= 4 and code[:4].isdigit():
                cur = code[:4]
                if len(code) in (4, 7) and code[4:5] in ("", "."):
                    texts.setdefault(code, " ".join((r.get("description") or "").split()).rstrip(":"))
            if cur is not None:
                by.setdefault(cur, []).append(r)
        for h, hrows in by.items():
            target = OUT / f"hts_{h}.json"
            if target.exists():
                kept += 1
                continue
            target.write_text(json.dumps({"fetched": datetime.date.today().isoformat(), "source": SOURCE.format(h=h[:2]), "rows": hrows}), encoding="utf-8")
            made += 1
    (OUT / "headings.json").write_text(json.dumps({"fetched": datetime.date.today().isoformat(), "texts": texts}, indent=0), encoding="utf-8")
    print(f"headings written {made}, left as they were {kept}, heading and subheading texts {len(texts)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
