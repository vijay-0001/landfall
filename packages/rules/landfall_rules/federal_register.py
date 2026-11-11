"""Federal Register: list new trade documents and fetch their plain text. Network lives here only; callers inject these
functions so tests run on recorded payloads."""
from __future__ import annotations

from datetime import date

import httpx

API = "https://www.federalregister.gov/api/v1/documents.json"
UA = "Mozilla/5.0 (compatible; landfall-sync/0.1; +https://example.invalid)"
AGENCIES = ["trade-representative-office-of-united-states", "u-s-customs-and-border-protection"]
FIELDS = ["title", "document_number", "publication_date", "html_url", "raw_text_url", "abstract", "type", "effective_on", "agency_names"]
# A cheap pre-filter on title and abstract. The model makes the real decision; this only avoids paying for obvious noise.
KEYWORDS = ("duty", "duties", "tariff", "de minimis", "informal entry", "formal entry", "htsus", "harmonized tariff", "low-value", "low value",
            "section 301", "section 232", "section 122", "import", "customs value")


def _params(since: date, agency: str | None, presidential: bool) -> list[tuple[str, str]]:
    p: list[tuple[str, str]] = [("conditions[publication_date][gte]", since.isoformat()), ("per_page", "100"), ("order", "oldest")]
    p += [("fields[]", f) for f in FIELDS]
    if agency:
        p.append(("conditions[agencies][]", agency))
    if presidential:
        p += [("conditions[type][]", "PRESDOCU"), ("conditions[term]", "tariff")]
    return p


def list_recent(since: date) -> list[dict]:
    """New documents from USTR and CBP, plus presidential documents that mention tariffs, since a date."""
    seen: dict[str, dict] = {}
    with httpx.Client(headers={"User-Agent": UA}, timeout=60) as c:
        for agency, pres in [(a, False) for a in AGENCIES] + [(None, True)]:
            r = c.get(API, params=_params(since, agency, pres))
            r.raise_for_status()
            for d in r.json().get("results", []):
                seen[d["document_number"]] = d
    return sorted(seen.values(), key=lambda d: (d["publication_date"], d["document_number"]))


def fetch_text(doc: dict) -> str:
    r = httpx.get(doc["raw_text_url"], headers={"User-Agent": UA}, timeout=90, follow_redirects=True)
    r.raise_for_status()
    return r.text


def is_candidate(doc: dict) -> bool:
    if doc.get("type") == "Proposed Rule":  # a proposal is not a rule in force; skip without paying for a model call
        return False
    hay = f"{doc.get('title') or ''} {doc.get('abstract') or ''}".lower()
    return any(k in hay for k in KEYWORDS)
