"""Small text helpers for what the seller reads."""
from __future__ import annotations

import re


def shorten(text: str, limit: int) -> str:
    """At most `limit` characters, ending on a whole sentence if one fits, else on a whole word with an ellipsis. Never mid-word."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = ""
    for s in sentences:
        nxt = f"{out} {s}".strip()
        if len(nxt) > limit:
            break
        out = nxt
    if out:
        return out
    room = text[: limit - 1]  # leave one character for the ellipsis
    cut = room.rsplit(" ", 1)[0].rstrip(" ,;:-") if " " in room else room
    return (cut or room) + "…"


def lower_first(text: str) -> str:
    """'Whether it is X' becomes 'whether it is X' when it continues a sentence; an acronym or a proper noun is left alone."""
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        return text[0].lower() + text[1:]
    return text


_PREFIX = re.compile(r"^\s*(?:the\s+)?listing\s+(?:does\s+not|doesn't|did\s+not)\s+(?:say|state|specify|mention|indicate|name)\s+", re.I)


def missing_fact(text: str) -> str:
    """The unstated fact, ready to follow 'The listing does not say ': the model sometimes already starts with that phrase."""
    return lower_first(_PREFIX.sub("", (text or "").strip()).rstrip("."))
