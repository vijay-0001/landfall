"""Haiku drafts the fixed rule form from a notice. The model is a helper: a field survives only if its quoted sentence is
found verbatim in the notice and its value passes a rule check. Anything else is left blank for ops. Model: claude-haiku-5-5."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from landfall_classifier.model import LLM, MODEL, parse_json

PROMPT_VERSION = "rule-v2"
FIELD_NAMES = ["destination", "code_pattern", "origin_scope", "measure", "rate", "valid_from", "valid_to"]
MEASURES = ["additional_duty", "base_duty", "low_value_relief", "total_rate_floor", "process_requirement"]
MAX_NOTICE_CHARS = 70_000

SYSTEM = """You read one official trade notice and fill a fixed rule form for a human reviewer. You recommend; a person approves.
Say relevant=false unless the document itself puts into force, or fixes the date of, a change to customs duties, tariffs,
low-value or de minimis treatment, or customs entry rules for goods imported into the United States, the United Kingdom or the
European Union. Proposed rules, requests for comments, hearing notices, and notices of tests or pilots are relevant=false.
Fields: destination (US, GB or EU), code_pattern (a tariff code prefix such as 4202 or 6912.00, or * for all goods),
origin_scope (a two-letter country code, EU, or ALL), measure (one of: additional_duty, base_duty, low_value_relief,
total_rate_floor, process_requirement), rate (percent as a number, no % sign), valid_from and valid_to (YYYY-MM-DD).
For EVERY field give the value and a quote: one sentence or clause copied EXACTLY, character for character, from the notice.
If the notice does not state a value, set both value and quote to null. Never infer, round or guess. Never invent a quote.
Reply with one JSON object and nothing else:
{"relevant": true or false, "title": "short plain title", "fields": {"destination": {"value": ..., "quote": ...}, ... all seven fields ...}}"""


@dataclass
class Draft:
    relevant: bool
    title: str = ""
    fields: dict[str, dict] = field(default_factory=dict)  # name -> {"value": str|None, "quote": str|None}
    dropped: list[str] = field(default_factory=list)  # fields blanked, and why
    model: str = MODEL
    prompt_version: str = PROMPT_VERSION


_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def normalise(t: str) -> str:
    t = re.sub(r"\[\[Page \d+\]\]", " ", t).translate(_QUOTES)
    t = t.replace("``", '"').replace("''", '"')
    return re.sub(r"\s+", " ", t).strip().lower()


def _valid_date(v: str) -> bool:
    try:
        date.fromisoformat(v)
        return True
    except ValueError:
        return False


CHECKS = {
    "destination": lambda v: v in ("US", "GB", "EU"),
    "code_pattern": lambda v: bool(re.fullmatch(r"\*|\d{2,4}(\.\d{2}){0,4}(\.\*)?", v)),
    "origin_scope": lambda v: bool(re.fullmatch(r"[A-Z]{2}|EU|ALL", v)),
    "measure": lambda v: v in MEASURES,
    "rate": lambda v: bool(re.fullmatch(r"\d{1,3}(\.\d{1,4})?", v)),
    "valid_from": _valid_date,
    "valid_to": _valid_date,
}


COUNTRY_WORDS = {
    "US": ["united states", "u.s.", "customs and border protection", "htsus", "harmonized tariff schedule"], "GB": ["united kingdom", "u.k.", "britain"],
    "EU": ["european union", "eu member", "union customs"], "CN": ["china", "people's republic of china"], "IN": ["india"], "CA": ["canada"],
    "MX": ["mexico"], "JP": ["japan"], "KR": ["korea"], "TW": ["taiwan"], "VN": ["vietnam", "viet nam"], "TR": ["turkey", "turkiye"],
    "CH": ["switzerland"], "BR": ["brazil"], "AU": ["australia"], "ID": ["indonesia"], "TH": ["thailand"], "PT": ["portugal"], "DE": ["germany"],
    "FR": ["france"], "IT": ["italy"], "ES": ["spain"], "NL": ["netherlands"], "BD": ["bangladesh"], "KH": ["cambodia"], "MY": ["malaysia"],
}
_MONTHS = "january february march april may june july august september october november december".split()


def quote_dates(q: str) -> set[str]:
    """Every calendar date a quote states, as ISO strings (Month D, YYYY; D Month YYYY; YYYY-MM-DD; M/D/YYYY)."""
    out: set[str] = set()
    low = normalise(q)
    names = "|".join(_MONTHS)
    for m, d, y in re.findall(rf"({names})\s+(\d{{1,2}}),?\s+(\d{{4}})", low):
        out.add(f"{y}-{_MONTHS.index(m) + 1:02d}-{int(d):02d}")
    for d, m, y in re.findall(rf"(\d{{1,2}})\s+({names}),?\s+(\d{{4}})", low):
        out.add(f"{y}-{_MONTHS.index(m) + 1:02d}-{int(d):02d}")
    out.update(re.findall(r"\d{4}-\d{2}-\d{2}", low))
    for mo, d, y in re.findall(r"(\d{1,2})/(\d{1,2})/(\d{4})", low):
        out.add(f"{y}-{int(mo):02d}-{int(d):02d}")
    return out


def _supports(name: str, value: str, quote: str) -> bool:
    """Does the quoted sentence itself contain the value? A real sentence that does not mention the value is not evidence."""
    low = normalise(quote)
    if name in ("destination", "origin_scope"):
        if value == "ALL":
            return bool(re.search(r"(all|any|every)", low))
        return any(w in low for w in COUNTRY_WORDS.get(value, []))
    if name in ("valid_from", "valid_to"):
        return value in quote_dates(quote)
    if name == "rate":
        return bool(re.search(rf"(?<![\d.]){re.escape(value)}(?:\.0+)?\s*-?\s*(?:percent|per cent|%)", low))
    if name == "code_pattern":
        if value == "*":
            return bool(re.search(r"(all|any|every)", low))
        want = re.sub(r"\D", "", value)
        return any(re.sub(r"\D", "", tok).startswith(want) for tok in re.findall(r"\d{4}(?:\.\d{2}){0,4}", low))
    if name == "measure":
        if value in ("additional_duty", "base_duty", "total_rate_floor"):
            return "dut" in low or "tariff" in low
        if value == "low_value_relief":
            return any(w in low for w in ("de minimis", "low-value", "low value", "informal entry", "value"))
    return True


def verify(raw_fields: dict, notice_text: str) -> tuple[dict[str, dict], list[str]]:
    """Keep a field only if its quote is in the notice and its value passes the rule check; otherwise blank it."""
    hay = normalise(notice_text)
    out: dict[str, dict] = {}
    dropped: list[str] = []
    for name in FIELD_NAMES:
        f = raw_fields.get(name) or {}
        value = None if f.get("value") in (None, "") else str(f["value"]).strip()
        quote = None if f.get("quote") in (None, "") else str(f["quote"]).strip()
        if value is None or quote is None:
            if value is not None or quote is not None:
                dropped.append(f"{name}: value and quote must come together")
            out[name] = {"value": None, "quote": None}
        elif len(normalise(quote)) < 12 or normalise(quote) not in hay:
            dropped.append(f"{name}: quote not found in the notice")
            out[name] = {"value": None, "quote": None}
        elif not CHECKS[name](value):
            dropped.append(f"{name}: value {value!r} is not a valid {name}")
            out[name] = {"value": None, "quote": None}
        elif not _supports(name, value, quote):
            dropped.append(f"{name}: the quoted sentence does not contain {value!r}")
            out[name] = {"value": None, "quote": None}
        else:
            out[name] = {"value": value, "quote": quote}
    return out, dropped


def draft_rule(llm: LLM, title: str, notice_text: str) -> Draft:
    """One Haiku call. Raises ValueError if the reply is not usable JSON (the caller skips the notice and retries next night)."""
    user = f"Notice title: {title}\n\nNotice text:\n{notice_text[:MAX_NOTICE_CHARS]}"
    reply = parse_json(llm.complete(SYSTEM, user, max_tokens=1500))
    if not reply.get("relevant"):
        return Draft(relevant=False)
    fields, dropped = verify(reply.get("fields") or {}, notice_text)
    return Draft(relevant=True, title=str(reply.get("title") or title)[:200], fields=fields, dropped=dropped)
