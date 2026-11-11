"""Dev tool: record UK Trade Tariff commodity JSON as fixtures (browser-like UA required)."""
import json
import pathlib
import sys
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
OUT = pathlib.Path(__file__).resolve().parent.parent / "packages/register/fixtures/uk_tariff"
OUT.mkdir(parents=True, exist_ok=True)
def get(path):
    return json.loads(urllib.request.urlopen(urllib.request.Request("https://www.trade-tariff.service.gov.uk/api/v2/" + path, headers={"User-Agent": UA}), timeout=60).read().decode("utf-8"))
def summary(d):
    inc = {(i["type"], i["id"]): i for i in d["included"]}
    for m in d["included"]:
        if m["type"] != "measure": continue
        a = m["attributes"]; mt = inc.get(("measure_type", m["relationships"]["measure_type"]["data"]["id"]), {}).get("attributes", {}).get("description")
        geo = m["relationships"]["geographical_area"]["data"]["id"]
        if mt and ("Third country" in mt or "VAT" in mt):
            de = inc.get(("duty_expression", m["relationships"].get("duty_expression", {}).get("data", {}).get("id")), {}).get("attributes", {})
            print("  ", mt, "|", geo, "|", de.get("base"), "|", a.get("effective_start_date"), "->", a.get("effective_end_date"), "| measure", m["id"])
if __name__ == "__main__":
    for arg in sys.argv[1:]:
        if len(arg) == 4:
            h = get(f"headings/{arg}")
            leaves = [i["attributes"]["goods_nomenclature_item_id"] + " " + i["attributes"]["description"][:50] for i in h["included"] if i["type"] == "commodity" and i["attributes"]["leaf"]]
            print(arg, "leaves:", *leaves[:25], sep="\n  ")
        else:
            d = get(f"commodities/{arg}")
            (OUT / f"commodity_{arg}.json").write_text(json.dumps(d, indent=1), encoding="utf-8")
            print(arg, d["data"]["attributes"]["description"]); summary(d)
