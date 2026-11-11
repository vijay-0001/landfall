"""Official places to look a customs code up, with search terms already filled in from the listing. Never a dead end: when Landfall cannot find a
code, or is not confident, the seller is handed these. No model call and no network call: the links are built from text."""
from __future__ import annotations

import re
from urllib.parse import quote

from .. import schemas as s

STOP = {"the", "and", "for", "with", "set", "pack", "pcs", "piece", "pieces", "hand", "made", "handmade", "new", "our", "from", "your", "that", "this", "size", "sizes",
        "small", "medium", "large", "of", "in", "a", "an", "to", "by", "on", "unisex", "mens", "womens", "kids", "vintage"}


def search_terms(title: str, description: str = "") -> str:
    """Up to five plain words that name the product: the title first, then the description if the title is too short."""
    def words(t: str) -> list[str]:
        return [w for w in re.findall(r"[a-zA-Z][a-zA-Z-]{2,}", t.lower()) if w not in STOP]

    out = list(dict.fromkeys(words(title)))[:5]
    if len(out) < 2:
        out += [w for w in dict.fromkeys(words(description)) if w not in out][: 3 - len(out)]
    return " ".join(out) or "product"


def help_links(terms: str, code: str | None = None, destinations: tuple[str, ...] = ("US", "GB", "EU")) -> list[s.HelpLink]:
    q = quote(terms)
    links = []
    if "US" in destinations:
        links += [
            s.HelpLink(label="US tariff search (USITC HTS)", url=f"https://hts.usitc.gov/search?query={q}", hint=f"Searches the official tariff for \"{terms}\"."),
            s.HelpLink(label="US customs rulings (CBP CROSS)", url=f"https://rulings.cbp.gov/search?term={q}&collection=ALL&sortBy=RELEVANCE&pageSize=30&page=1",
                       hint="Real rulings by US customs on similar goods: the closest thing to a precedent."),
        ]
    if "GB" in destinations:
        links.append(s.HelpLink(label="UK Trade Tariff", url=f"https://www.trade-tariff.service.gov.uk/search?q={q}", hint="The UK's official commodity search."))
    if "EU" in destinations:
        links.append(s.HelpLink(label="EU TARIC", url="https://ec.europa.eu/taxation_customs/dds2/taric/taric_consultation.jsp?Lang=en",
                                hint=f"The EU's tariff consultation page. Open it and search for \"{terms}\"."))
    if code and code != "none":
        digits = code.replace(".", "")
        links.insert(0, s.HelpLink(label=f"Check code {code} in the US tariff", url=f"https://hts.usitc.gov/search?query={digits}", hint="Opens the exact line Landfall recommended."))
    return links
