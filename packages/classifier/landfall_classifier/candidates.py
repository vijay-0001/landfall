"""Closed candidate list for the classifier, built from the register's recorded USITC headings.

The model chooses among real 6-digit subheadings; it never invents a code (HLD section 4, step 2).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / "register" / "fixtures" / "usitc"
CORE_HEADINGS = ["4201", "4202", "4203", "4205", "6101", "6102", "6103", "6104", "6105", "6106", "6107", "6108", "6109", "6110", "6111", "6112", "6113", "6114", "6115", "6116", "6117", "6201", "6202", "6203", "6204", "6205", "6206", "6207", "6208", "6209", "6210", "6211", "6212", "6213", "6214", "6215", "6216", "6217", "6301", "6302", "6303", "6304", "6305", "6307", "6907", "6911", "6912", "6913", "6914"]


HEADINGS = CORE_HEADINGS  # the original list, kept for callers that mean "the core subset"


def _texts(fixtures: Path | None = None) -> dict[str, str]:
    f = (fixtures or FIXTURES) / "headings.json"
    return json.loads(f.read_text(encoding="utf-8"))["texts"] if f.exists() else {}


def all_headings(fixtures: Path | None = None) -> list[str]:
    """Every 4-digit goods heading of the tariff (chapters 98 and 99 are special provisions, not goods). The list is the committed headings.json,
    so it is the same on a fresh clone; the rows under a heading are read on first use (heading_rows)."""
    return sorted(k for k in _texts(fixtures) if len(k) == 4 and k[:2] not in ("98", "99"))


def heading_menu(fixtures: Path | None = None) -> dict[str, str]:
    """Heading -> official text for the whole tariff (the menu the first model step chooses from)."""
    t = heading_texts(fixtures)
    return {h: t[h] for h in all_headings(fixtures) if t.get(h)}


def heading_rows(h: str, fixtures: Path | None = None) -> list[dict]:
    """The recorded USITC export rows of one heading. A heading that is not recorded yet is read live from the USITC once and kept
    (the file is git-ignored); LANDFALL_US_ONDEMAND=off forbids that, and tests never reach the internet."""
    if not (h.isdigit() and len(h) == 4):
        return []
    f = (fixtures or FIXTURES) / f"hts_{h}.json"
    if not f.exists():
        if os.environ.get("LANDFALL_US_ONDEMAND", "").lower() == "off":
            return []
        try:
            from landfall_register.us_ondemand import live_fetch

            data = live_fetch(h)
        except Exception:
            return []
        if not data.get("rows"):
            return []
        f.write_text(json.dumps(data), encoding="utf-8")
    return json.loads(f.read_text(encoding="utf-8"))["rows"]


def describe(hs6: str, fixtures: Path | None = None) -> str:
    """The subheading's descriptive text, for any code in the tariff."""
    return load_candidates(fixtures, headings=[hs6[:4]]).get(hs6, hs6)


def _clean(s: str) -> str:
    return " ".join((s or "").replace("’", "'").split()).rstrip(":")


def load_candidates(fixtures: Path | None = None, headings: list[str] | None = None) -> dict[str, str]:
    """hs6 ("6912.00") -> "ancestor text > ... > subheading text", from the recorded HTS export (indent gives the parents)."""
    out: dict[str, str] = {}
    heads = list(headings) if headings is not None else CORE_HEADINGS
    for h in heads:
        stack: list[tuple[int, str]] = []
        for r in heading_rows(h, fixtures):
            desc = _clean(r["description"])
            if not desc:
                continue
            ind = int(r["indent"] or 0)
            while stack and stack[-1][0] >= ind:
                stack.pop()
            stack.append((ind, desc))
            code = r["htsno"] or ""
            if len(code) >= 7 and code[4] == "." and code[:7] not in out:  # first line under the 6-digit subheading
                out[code[:7]] = " > ".join(d for _, d in (stack if len(code) <= 10 else stack[:-1] or stack))[:230]  # an 8-digit line with no 6-digit row IS the subheading
    for h in heads:  # a heading with no 6-digit rows of its own in the export (for example 4201)
        if not any(k.startswith(h) for k in out):
            for r in heading_rows(h, fixtures):
                code = r["htsno"] or ""
                if len(code) >= 7 and code.startswith(h):
                    out[code[:7]] = _clean(r["description"])[:200]
                    break
    texts = _texts(fixtures)
    for code in list(out):  # keep the ancestor chain when it has one; otherwise prefix the heading text
        if " > " in out[code]:
            continue
        head = texts.get(code[:4], "")
        sub = texts.get(code) or out[code]
        out[code] = (f"{head[:120]} > {sub}" if head and sub not in head else sub)[:240]
    return out


def children_of(hs6: str, fixtures: Path | None = None) -> list[dict]:
    """National lines (8 and 10 digit) under a 6-digit subheading with their general rate, for the per-destination pick."""
    rows = heading_rows(hs6[:4], fixtures)
    return [{"code": r["htsno"], "description": _clean(r["description"]), "general": r["general"], "indent": r["indent"]}
            for r in rows if (r["htsno"] or "").startswith(hs6) and len(r["htsno"]) > 7]


def heading_texts(fixtures: Path | None = None) -> dict[str, str]:
    """4-digit heading -> its official text, for the menu and for grouping the closed list."""
    return {k: v for k, v in _texts(fixtures).items() if len(k) == 4}


def examples(hs6: str, fixtures: Path | None = None, limit: int = 4) -> str:
    """A few distinctive national-line names under a subheading ("Damask; Plain woven"), to show what kind of goods it holds."""
    seen: list[str] = []
    for ln in children_of(hs6, fixtures):
        d = " ".join(ln["description"].split())
        d = d.split(" (")[0].strip().rstrip(":")
        if d and d.lower() not in ("other", "") and d not in seen and len(d) <= 60:
            seen.append(d)
    return "; ".join(seen[:limit])


def grouped_candidates(fixtures: Path | None = None, headings: list[str] | None = None) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """[(heading, heading text, [(hs6, distinguishing text + examples)])]: the heading text once, each subheading only what sets it apart."""
    cands = load_candidates(fixtures, headings=headings)
    heads = heading_texts(fixtures)
    out: dict[str, list[tuple[str, str]]] = {}
    for code, path in cands.items():
        h = code[:4]
        parts = [p.strip() for p in path.split(" > ")]
        if heads.get(h) and parts and _clean(parts[0]).lower() == _clean(heads[h]).lower():
            parts = parts[1:] or parts[-1:]
        text = " > ".join(parts)
        ex = examples(code, fixtures)
        out.setdefault(h, []).append((code, text + (f"  [e.g. {ex}]" if ex else "")))
    return [(h, heads.get(h, ""), items) for h, items in sorted(out.items())]


def duty_lines(hs6: str, fixtures: Path | None = None) -> list[dict]:
    """Every line under a 6-digit subheading that carries a general duty rate, with its full description path.

    These are the lines a duty is actually charged on (8 or 10 digits). Each has `code`, `path` (ancestors > line) and `general` (the rate text).
    """
    stack: list[tuple[int, str]] = []
    out: list[dict] = []
    for r in heading_rows(hs6[:4], fixtures):
        desc = _clean(r["description"])
        ind = int(r["indent"] or 0)
        while stack and stack[-1][0] >= ind:
            stack.pop()
        if desc:
            stack.append((ind, desc))
        code = r["htsno"] or ""
        if code.startswith(hs6) and len(code) >= 10 and (r["general"] or "").strip():
            out.append({"code": code, "path": " > ".join(d for _, d in stack)[:260], "general": r["general"].strip()})
    return out
