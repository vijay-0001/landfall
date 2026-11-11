"""Bands and triggers, set by rules (not by a model score). Pure functions: no model call, no I/O.

Band: High if both calls agree at 6 digits and no origin signals conflict; Check if the calls disagree or one failed;
Ask if a trigger fires and a question is needed (HLD section 4). Triggers T1 to T6; at most 4 questions per product.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from .national import NationalResult
from .pipeline import Listing, ModelAnswer
from .text import missing_fact

MAX_QUESTIONS = 4
_NAMES = (
    "AE:United Arab Emirates,AR:Argentina,AT:Austria,AU:Australia,BD:Bangladesh,BE:Belgium,BG:Bulgaria,BR:Brazil,CA:Canada,CH:Switzerland,CL:Chile,CN:China,"
    "CO:Colombia,CY:Cyprus,CZ:Czechia,DE:Germany,DK:Denmark,EE:Estonia,EG:Egypt,ES:Spain,FI:Finland,FR:France,GB:United Kingdom,GR:Greece,HK:Hong Kong,"
    "HR:Croatia,HU:Hungary,ID:Indonesia,IE:Ireland,IL:Israel,IN:India,IS:Iceland,IT:Italy,JP:Japan,KE:Kenya,KR:South Korea,LK:Sri Lanka,LT:Lithuania,"
    "LU:Luxembourg,LV:Latvia,MA:Morocco,MT:Malta,MX:Mexico,MY:Malaysia,NG:Nigeria,NL:Netherlands,NO:Norway,NP:Nepal,NZ:New Zealand,PE:Peru,PH:Philippines,"
    "PK:Pakistan,PL:Poland,PT:Portugal,RO:Romania,RS:Serbia,SA:Saudi Arabia,SE:Sweden,SG:Singapore,SI:Slovenia,SK:Slovakia,TH:Thailand,TN:Tunisia,"
    "TR:Türkiye,TW:Taiwan,UA:Ukraine,US:United States,VN:Vietnam,ZA:South Africa,EL:Greece")
COUNTRY = dict(p.split(":") for p in _NAMES.split(","))
# Origins with their own entry in the duty register (an origin-specific list): T4 applies when origin is not firmly known.
ORIGIN_SPECIFIC = {"GB", "CN", "IN", "PT", "DE", "FR", "IT", "ES", "TR", "VN", "BD", "PK", "JP", "KR", "TH", "ID", "MX", "CA"}
TOLERANCE_ABS = Decimal("1.00")
TOLERANCE_PCT = Decimal("0.03")

# Quoter: duty and tax a US buyer would pay for (hs6, origin), or None if the register cannot price it yet.
Quoter = Callable[[str, str], Decimal | None]


class QOption(BaseModel):
    id: str
    label: str
    value: str
    impact: Decimal | None
    is_ai_pick: bool = False


class QQuestion(BaseModel):
    id: str
    trigger: Literal["T1", "T2", "T3", "T4", "T5", "T6"]
    text: str
    help: str | None = None
    evidence: str | None = None
    options: list[QOption]


class Decision(BaseModel):
    band: Literal["high", "check", "ask"]
    triggers: list[str]
    hs6: str
    runner_up: str | None
    origin: str
    code_reason: str
    origin_reason: str
    signals: list[dict]
    questions: list[QQuestion]
    paused_reason: str | None = None
    headline: str


# Goods Landfall will not price, whatever the code, each with the plain reason the seller is told.
_REFUSALS = [
    ("radioactive material", r"radioactive|uranium|plutonium|thorium|nuclear fuel",
     "Radioactive material is dangerous goods. It is tightly controlled and cannot be shipped or imported through ordinary parcel channels."),
    ("weapons and explosives", r"explosives?|detonators?|dynamite|ammunition|firearms?|rifles?|pistols?|handguns?|grenades?|weapons?",
     "Weapons, ammunition and explosives need licences and are banned from normal parcel shipping in most countries."),
    ("illegal drugs", r"narcotics?|cocaine|heroin|methamphetamine|cannabis|marijuana",
     "Illegal drugs are prohibited, and Landfall will not help price or ship them."),
    ("protected wildlife", r"elephant ivory|ivory tusks?|rhino horn|endangered",
     "Products from protected or endangered wildlife are banned or tightly restricted by international treaty (CITES)."),
    ("human remains", r"human remains|human bones?|human skulls?",
     "Trade in human remains is prohibited or heavily restricted, and Landfall will not price it."),
    ("stolen or looted goods", r"stolen|looted",
     "Selling or shipping stolen or looted goods is unlawful, and Landfall will not help price them. If this is a mistake, change the description."),
    ("counterfeit goods", r"counterfeit|forged|fake (?:designer|branded)",
     "Counterfeit goods infringe other people's rights and are seized at the border. Landfall will not price them."),
]
_REGULATED = [(cat, re.compile(r"\b(" + pat + r")\b", re.I), why) for cat, pat, why in _REFUSALS]


def regulated_term(listing) -> tuple[str, str, str] | None:
    """(the word that triggered it, the category, the plain reason) when the listing is for goods Landfall will not price."""
    text = f"{listing.title} {listing.description}"
    for cat, rx, why in _REGULATED:
        m = rx.search(text)
        if m:
            return m.group(1).lower(), cat, why
    return None


def country_name(c: str) -> str:
    return COUNTRY.get(c, c)


def choose_origin(a: ModelAnswer, b: ModelAnswer | None) -> tuple[str, bool, bool, str | None]:
    """(origin, conflict, strong, label_evidence). A label on the goods beats the listing text; shop country is weakest."""
    answers = [x for x in (a, b) if x]
    sigs = [s for x in answers for s in x.signals if s.points_to]
    non_shop = [s for s in sigs if s.kind != "shop_country"]
    label = next((s for s in non_shop if s.kind == "label_photo"), None)
    points = {s.points_to for s in non_shop}
    origins = {x.origin for x in answers}
    conflict = len(points) > 1 or len(origins) > 1
    if label and label.points_to:
        origin = label.points_to
    else:
        origin = a.origin
    strong = bool(non_shop) and not conflict
    return origin, conflict, strong, (label.text if label else None)


def decide(a: ModelAnswer | None, b: ModelAnswer | None, listing: Listing, quote: Quoter, buyer_price: Decimal, *,
           national: Callable[[str], NationalResult | None] | None = None, quote_line: Callable[[str, str], Decimal | None] | None = None) -> Decision | None:
    """Combine two independent answers into one recommendation. Returns None if neither call produced a valid answer."""
    hit = regulated_term(listing)
    if hit:  # said plainly, before any code is considered: no price, and the seller is told exactly why
        term, cat, why = hit
        shop = next((x.origin for x in (a, b) if x), listing.shop_country)
        return Decision(
            band="check", triggers=["T5"], hs6="none", runner_up=None, origin=shop,
            code_reason=f"The listing mentions \"{term}\". {why}",
            origin_reason="Origin is not assessed for goods Landfall will not price.", signals=[], questions=[],
            headline=f"Landfall will not price this: {cat}",
            paused_reason=f"Landfall will not price this: {cat}. {why} Standard checkout applies; the decision is yours, and the rules where you ship are yours to check.")
    if a and b and a.hs6 == "none" and b.hs6 != "none":
        a, b = b, a  # keep the answer that names a code as the primary one
    first = a or b
    if first is None:
        return None
    if all(x.hs6 == "none" for x in (a, b) if x):  # outside the closed list: duties-included is not offered for it
        why = first.reason.rstrip(".")
        return Decision(band="check", triggers=["T5"], hs6="none", runner_up=None, origin=first.origin, code_reason=first.reason, origin_reason=first.origin_reason,
                        signals=[], questions=[], headline="Landfall could not find a tariff code it can price for this product",
                        paused_reason=f"Not available for duties-included: Landfall could not match this to a tariff code it can price ({why}). Standard checkout applies; you can look the code up yourself with the Help me find it links on this page and then use Override.")
    triggers: list[str] = []
    questions: list[QQuestion] = []
    origin, conflict, strong, label_text = choose_origin(first, b if a else None)
    hs6 = first.hs6
    runner_up = first.runner_up
    disagree = bool(a and b and a.hs6 != b.hs6)
    # A listing that leaves out a fact deciding the subheading is as uncertain as two calls that disagree: the model
    # reports what is unstated, and these rules (not a model score) turn that into a question or a Check.
    unknown = next((x for x in (a, b) if x and x.decisive_unknown and x.runner_up and x.runner_up != first.hs6), None)
    unstated = bool(unknown) and not disagree
    single = a is None or b is None
    if disagree:
        runner_up = b.hs6 if b and b.hs6 != hs6 else runner_up
    code_reason = first.reason
    paused = None
    regulated = any(x.regulated for x in (a, b) if x)
    if regulated:
        triggers.append("T5")
        paused = next((x.regulated_reason for x in (a, b) if x and x.regulated and x.regulated_reason), "This looks like a regulated product")
        paused = f"Not available for duties-included: {paused}. Regulated goods need a licensed broker."

    # T1: two candidate codes whose duty differs by more than the larger of $1 or 3% of the buyer price
    if (disagree or unstated) and not paused:  # the two candidates: the two independent calls, or the one fact the listing leaves out
        runner_up = b.hs6 if disagree and b else unknown.runner_up
        if runner_up == "none":
            runner_up = None
        base, alt = (quote(hs6, origin), quote(runner_up, origin)) if runner_up else (None, None)
        tol = max(TOLERANCE_ABS, buyer_price * TOLERANCE_PCT)
        if base is not None and alt is not None and abs(alt - base) > tol:
            triggers.append("T1")
            questions.append(QQuestion(
                id="q_code", trigger="T1", text="Which of these describes the product better?",
                help=("The listing does not say " + missing_fact(unknown.decisive_unknown) + ", and the two options carry different duty.") if unstated
                else "The two options sit under different customs codes with different duty.",
                options=[QOption(id=f"code_{h}", label=h, value=h, impact=(d - base) if h != hs6 else Decimal("0.00"), is_ai_pick=(h == hs6))
                         for h, d in ((hs6, base), (runner_up, alt))]))

    # Origin questions: T2 contradiction, T3 transformed, T4 weak evidence on an origin-specific list
    transformed = any(x.transformed for x in (a, b) if x)
    weak = not strong
    if not paused:
        if conflict:
            trig = "T2"
        elif transformed:
            trig = "T3"
        elif weak and origin in ORIGIN_SPECIFIC:
            trig = "T4"
        else:
            trig = None
        if trig:
            triggers.append(trig)
            cands: list[str] = []
            for x in (a, b):
                if x:
                    cands += [x.origin] + [s.points_to for s in x.signals if s.points_to and s.kind != "shop_country"]
            cands = list(dict.fromkeys([origin] + cands + [listing.shop_country]))[:3]
            base = quote(hs6, origin)
            opts = [QOption(id=f"origin_{c}", label=country_name(c), value=c, is_ai_pick=(c == origin),
                            impact=(None if (q := quote(hs6, c)) is None or base is None else q - base)) for c in cands]
            opts.append(QOption(id="origin_other", label="Somewhere else", value="other", impact=None))
            text = {"T2": f'We spotted "{label_text}". Where was it made?' if label_text else "The listing and its photos disagree. Where was it made?",
                    "T3": "You worked this product yourself. Where was the blank or base product made?",
                    "T4": "We could not find a strong sign of where this was made. Where was it made?"}[trig]
            questions.append(QQuestion(id="q_origin", trigger=trig, text=text,  # type: ignore[arg-type]
                                       help="Relabelling or adding your own packaging does not change the country of origin.",
                                       evidence=label_text, options=opts))
    # The duty is charged on the national line, so an uncertain line matters as much as an uncertain 6-digit code: ask when the two
    # candidate lines carry materially different duty, say so plainly when they cannot be priced, and stay quiet when the duty is the same.
    line_unpriced = False
    if national and quote_line and not paused and hs6 != "none":
        nat = national(hs6)
        if nat and nat.runner_up and (not nat.agreed or nat.decisive_unknown):
            base_l, alt_l = quote_line(nat.code, origin), quote_line(nat.runner_up, origin)
            if base_l is None or alt_l is None:
                line_unpriced = True
            elif abs(alt_l - base_l) > max(TOLERANCE_ABS, buyer_price * TOLERANCE_PCT):
                if "T1" not in triggers:
                    triggers.append("T1")
                why = f"The listing does not say {missing_fact(nat.decisive_unknown)}, and the two lines carry different duty." if nat.decisive_unknown                     else "The two options are different tariff lines with different duty."
                questions.append(QQuestion(
                    id="q_line", trigger="T1", text="Which of these describes the product better?", help=why,
                    options=[QOption(id=f"line_{c}", label=nat.labels.get(c, c), value=c, impact=(d - base_l) if c != nat.code else Decimal("0.00"), is_ai_pick=(c == nat.code))
                             for c, d in ((nat.code, base_l), (nat.runner_up, alt_l))]))
    questions = questions[:MAX_QUESTIONS]
    if questions:
        band = "ask"
    elif disagree or single or unstated or line_unpriced:
        band = "check"
    else:
        band = "high"
    if questions:
        n = len(questions)
        headline = f"{n} quick question{'s' if n > 1 else ''}: the answers change what buyers pay"
    elif band == "check":
        headline = ("Check this one: the listing does not say " + missing_fact(unknown.decisive_unknown)) if unstated else "Check this one: the two AI runs did not fully agree"
    else:
        headline = "No questions needed: both likely codes cost the same"
    sigs = [s.model_dump() for x in (a, b) if x for s in x.signals]
    unique = list({(s["kind"], s["text"]): s for s in sigs}.values())
    return Decision(band=band, triggers=triggers, hs6=hs6, runner_up=runner_up, origin=origin, code_reason=code_reason,
                    origin_reason=first.origin_reason, signals=unique, questions=questions, paused_reason=paused, headline=headline)
