"""D7: Haiku classifier harness. Two independent calls per listing, closed candidate list, JSON out."""
import re, json, time, statistics, concurrent.futures as cf, anthropic
MODEL = "claude-haiku-5-5"
key = re.search(r'ANTHROPIC_API_KEY=(.*)', open('../../.env').read()).group(1).strip()
cl = anthropic.Anthropic(api_key=key)
CANDS = {
"6911.10":"Tableware/kitchenware of porcelain","6911.90":"Household/toilet articles of porcelain, other",
"6912.00":"Ceramic tableware/kitchenware/household articles other than porcelain (stoneware, earthenware)",
"6913.10":"Statuettes/ornamental ceramic articles, porcelain","6913.90":"Statuettes/ornamental ceramic articles, other than porcelain",
"6914.10":"Other ceramic articles, porcelain","6914.90":"Other ceramic articles, other than porcelain",
"6910.90":"Ceramic sinks/baths/bidets/WC pans etc, other","6907.21":"Ceramic tiles, water absorption <=0.5%",
"4202.11":"Trunks/suitcases, outer surface leather","4202.12":"Trunks/suitcases, outer surface plastic or textile",
"4202.21":"Handbags, outer surface leather","4202.22":"Handbags, outer surface plastic sheeting or textile",
"4202.31":"Pocket/handbag articles (wallets, card holders, purses), outer surface leather",
"4202.32":"Pocket/handbag articles, outer surface plastic or textile","4202.92":"Other bags/cases, outer surface plastic or textile",
"4203.10":"Apparel of leather","4203.21":"Gloves specially designed for sports, leather","4203.29":"Gloves, other, leather",
"4203.30":"Belts and bandoliers of leather","4201.00":"Saddlery and harness incl. dog collars and leads, any material",
"6109.10":"T-shirts, singlets, knitted, of cotton","6110.20":"Jerseys/pullovers/hoodies, knitted, of cotton",
"6115.95":"Hosiery/socks, knitted, of cotton","6203.42":"Men's trousers/jeans, woven, of cotton",
"6204.42":"Women's dresses, woven, of cotton","6205.20":"Men's shirts, woven, of cotton",
"6302.21":"Bed linen, printed, of cotton","6302.31":"Bed linen, other, of cotton","6302.51":"Table linen, other, of cotton",
"6302.60":"Toilet/kitchen linen, terry towelling, of cotton","6302.91":"Other toilet/kitchen linen, of cotton",
"6303.91":"Curtains/blinds, knitted or crocheted, of cotton","6303.92":"Curtains/blinds, of synthetic fibres",
"6214.90":"Shawls/scarves, of other textile materials","6302.53":"Table linen, of man-made fibres",
}
CANDS.update({"6104.62":"Women's trousers/leggings, knitted, of cotton","6111.20":"Babies' garments, knitted, of cotton","6206.30":"Women's blouses/shirts, woven, of cotton","6303.91":"Curtains/blinds, other than knitted, of cotton","6302.91":"Other toilet/kitchen linen, of cotton"})
CANDS["6303.91"]="Curtains/blinds, other than knitted, of cotton"
import json as _j
_rows=_j.load(open("listings.json"))
L=[(r["title"],r["description"],r["hs6"]) for r in _rows]
lst = "\n".join(f"{k} {v}" for k,v in CANDS.items())
SYSTEM = f"""You classify product listings for customs. Choose exactly one HS 6-digit code from this closed list only:
{lst}
Rules: use the material, construction and function in the listing; do not guess outside the list; if the listing is ambiguous between two codes, lower confidence and name the question that would resolve it.
Reply with JSON only: {{"hs6":"....","confidence":0.0-1.0,"reason":"one sentence","question":null or "one question"}}"""
def call(item):
    t=time.time()
    r=cl.messages.create(model=MODEL,max_tokens=300,thinking={"type":"disabled"},system=SYSTEM,
        messages=[{"role":"user","content":f"Title: {item[0]}\nDescription: {item[1]}"}])
    dt=time.time()-t
    txt="".join(b.text for b in r.content if b.type=="text")
    m=re.search(r'\{.*\}',txt,re.S)
    try: j=json.loads(m.group(0))
    except Exception: j={"hs6":None,"confidence":0}
    return j,dt,r.usage.input_tokens,r.usage.output_tokens
def run(i):
    a=call(L[i]); b=call(L[i]); return i,a,b
t0=time.time()
with cf.ThreadPoolExecutor(8) as ex: res=sorted(ex.map(run,range(len(L))))
tot=time.time()-t0
lat=[];ti=to=0;ok1=ok2=agree=heading=valid=0;rows=[]
for i,a,b in res:
    tr=L[i][2]
    for j,dt,x,y in (a,b): lat.append(dt);ti+=x;to+=y;valid+= j.get("hs6") in CANDS
    ok1+=a[0].get("hs6")==tr; ok2+=b[0].get("hs6")==tr
    ag=a[0].get("hs6")==b[0].get("hs6"); agree+=ag
    heading+=(a[0].get("hs6") or "")[:4]==tr[:4]
    rows.append({"title":L[i][0],"truth":tr,"a":a[0],"b":b[0],"agree":ag})
n=len(L); lat.sort()
p95=lat[int(len(lat)*0.95)-1]
PIN,POUT=1.0,5.0  # ASSUMED $/MTok (Haiku 4.5 list price); actual Haiku 5.5 price to confirm
cost=(ti*PIN+to*POUT)/1e6
out={"model":MODEL,"listings":n,"exact6_callA":ok1/n,"exact6_callB":ok2/n,"heading4_callA":heading/n,
"calls_agree":agree/n,"valid_in_list":valid/(2*n),"latency_p50":statistics.median(lat),"latency_p95":p95,
"latency_max":lat[-1],"per_product_2calls_tokens":[ti/n,to/n],"cost_per_product_assumed_usd":cost/n,"wall_s":tot}
json.dump({"summary":out,"rows":rows},open("eval_results.json","w"),indent=1)
print(json.dumps(out,indent=1))
for r in rows:
    if r["a"].get("hs6")!=r["truth"] or not r["agree"]: print("MISS",r["title"],r["truth"],r["a"].get("hs6"),r["b"].get("hs6"),r["a"].get("confidence"),r["a"].get("question"))
