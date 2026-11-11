"""One-off dev tool: record USITC HTS headings in scope as fixtures. Tests never run this."""
import datetime
import json
import pathlib
import sys
import time
import urllib.request

OUT = pathlib.Path(__file__).resolve().parent.parent / "packages/register/fixtures/usitc"
OUT.mkdir(parents=True, exist_ok=True)
HEADINGS = ["4201", "4202", "4203", "4205", "6101", "6102", "6103", "6104", "6105", "6106", "6107", "6108", "6109", "6110", "6111", "6112", "6113", "6114", "6115", "6116", "6117", "6201", "6202", "6203", "6204", "6205", "6206", "6207", "6208", "6209", "6210", "6211", "6212", "6213", "6214", "6215", "6216", "6217", "6301", "6302", "6303", "6304", "6305", "6307", "6907", "6911", "6912", "6913", "6914"]
HEADINGS = sys.argv[1:] or HEADINGS  # optional: record only some headings; headings.json is merged
for h in HEADINGS:
    url = f"https://hts.usitc.gov/reststop/exportList?from={h}.00.00&to={h}.99.99&format=JSON&styles=false"
    req = urllib.request.Request(url, headers={"User-Agent": "landfall-fixture-recorder/0.1"})
    data = json.loads(urllib.request.urlopen(req, timeout=60).read())
    (OUT / f"hts_{h}.json").write_text(json.dumps({"fetched": datetime.date.today().isoformat(), "source": url, "rows": data}, indent=1), encoding="utf-8")
    print(h, len(data))
    time.sleep(0.5)

# Heading and 6-digit subheading texts (the range export omits them): record via the search endpoint.
import urllib.parse

heads = json.loads((OUT / "headings.json").read_text(encoding="utf-8"))["texts"] if (OUT / "headings.json").exists() else {}
for h in HEADINGS:
    url = "https://hts.usitc.gov/reststop/search?keyword=" + urllib.parse.quote(h)
    data = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "landfall-fixture-recorder/0.1"}), timeout=60).read())
    for r in data:
        code = r.get("htsno") or ""
        if (len(code) == 4 or (len(code) == 7 and code[4] == ".")) and code.startswith(h):
            heads[code] = " ".join((r.get("description") or "").split()).rstrip(":")
    time.sleep(0.4)
(OUT / "headings.json").write_text(json.dumps({"fetched": datetime.date.today().isoformat(), "texts": heads}, indent=1), encoding="utf-8")
print("headings", len(heads))
