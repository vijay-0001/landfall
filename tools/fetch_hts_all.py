"""One-off dev tool: record the whole US tariff, one file per chapter (USITC exportList), then run tools/split_hts_chapters.py on the folder.

    python tools/fetch_hts_all.py OUT_DIR      # about 3 minutes, 97 requests
"""
import json,sys,time,urllib.request,pathlib
out=pathlib.Path(sys.argv[1]); out.mkdir(exist_ok=True)
def get(u):
    for a in range(3):
        try: return json.loads(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"landfall-fixture-recorder/0.1"}),timeout=90).read())
        except Exception as e: time.sleep(3)
    return None
n=0
for ch in range(1,98):
    if ch==77: continue
    c=f"{ch:02d}"
    d=get(f"https://hts.usitc.gov/reststop/exportList?from={c}00.00.00&to={c}99.99.99&format=JSON&styles=false")
    if d is None: print("fail",c); continue
    (out/f"hts_ch{c}.json").write_text(json.dumps(d),encoding="utf-8"); n+=len(d); print(c,len(d),flush=True); time.sleep(0.6)
print("total rows",n)
