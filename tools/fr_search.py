import json
import sys
import urllib.parse
import urllib.request


def q(term, since="2025-01-01", n=15, extra=""):
    url = ("https://www.federalregister.gov/api/v1/documents.json?per_page=%d&order=newest&conditions[term]=%s&conditions[publication_date][gte]=%s%s"
           % (n, urllib.parse.quote(term), since, extra))
    d = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "landfall-research/0.1"}), timeout=60).read())
    print(f"\n## {term}  ({d['count']} total)")
    for r in d["results"]:
        print(r["document_number"], r["publication_date"], r["type"], "|", r["title"][:120])
for t in sys.argv[1:]:
    q(t)
