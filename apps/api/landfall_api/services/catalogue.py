"""Catalogue, recommendations, answers, Accept/Override decisions, bulk accept.

The AI recommends; nothing reaches checkout without a decision row from the seller. Evidence is optional.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import UTC, date, datetime
from decimal import Decimal

from landfall_classifier import (
    PROMPT_VERSION,
    Decision,
    HaikuClient,
    Listing,
    NationalResult,
    classify_wide,
    decide,
    pick_national,
)
from landfall_classifier.candidates import describe, duty_lines
from landfall_classifier.model import LLM, MODEL
from landfall_classifier.rules import regulated_term
from landfall_classifier.text import shorten
from landfall_register import repo, uk_ondemand, us_ondemand
from sqlalchemy import Connection, text

from .. import demo
from .. import schemas as s
from ..config import env
from . import photos
from .coverage import ORIGIN_NAMES, covered_origin_codes
from .links import help_links, search_terms
from .pricing import EU27, ORIGIN_ALIASES, money, price_cart, trail_lines

FINE_PRINT_VERSION = "fp-2026-11-01.1"
FINE_PRINT = (
    "By accepting, you confirm this customs code and country of origin are correct for this product, and that you are the declarant. "
    "Duties shown are estimates from published rates on the date shown; customs and carriers set the final amount. "
    "Landfall's AI is a helper: it recommends and explains, and carries no customs or payment risk. Attaching evidence is optional."
)
SELLER = "seller:kiln"


def origin_unpriced(origin: str | None) -> bool:
    """True when the origin is one Landfall does not price for US buyers ("other", or a country outside the covered list; EU member states count as the EU)."""
    o = ORIGIN_ALIASES.get(origin or "", origin or "")
    return o not in ORIGIN_NAMES and o not in EU27


def _origin_impact(conn: Connection, rec: dict, origin: str) -> float | None:
    """What a buyer pays more or less for a named origin than for the AI's pick, from the register at today's rates (None when the line cannot be priced)."""
    d = rec["payload"]["decision"]
    nat = (rec["payload"].get("national") or {}).get(d["hs6"])
    usd = conn.execute(text("SELECT prices ->> 'USD' FROM product WHERE id = :i"), {"i": rec["product_id"]}).scalar()
    if not nat or not nat.get("code") or not usd:
        return None
    version = repo.latest_version(conn)
    taxes = []
    for o in (origin, d["origin"]):
        res = price_cart(conn, "US", _cart(nat["code"], o, usd), date.today(), version, window=0)
        taxes.append(res.tax_total if res.supported else None)
    return None if None in taxes else float(taxes[0] - taxes[1])


def _uk_get(path: str) -> dict:
    if env("LANDFALL_UK_ONDEMAND") == "off":  # set by the e2e run: it talks to the real recommender but never to the live UK Trade Tariff
        raise OSError("the on-demand UK read is switched off")
    return uk_ondemand.live_get(path)


uk_get = _uk_get  # unit tests replace this: they never reach the internet
us_fetch = us_ondemand.recorded_or_live  # the recorded export if present, else live from the USITC (LANDFALL_US_ONDEMAND=off forbids the live read); unit tests replace this


UNSUPPORTED = {
    "origin_not_covered": "The rate register does not cover this origin yet",
    "code_not_in_register": "No priced line for this code yet",
    "exclusion_review": "A product exclusion may apply to this line: not priced until reviewed",
    "special_duty_review": "Section 232 or other special duties may apply to this kind of product, and Landfall has not read them yet: not priced",
    "usmca_claim": "Goods from Canada and Mexico that qualify under USMCA pay no extra duty; Landfall cannot tell whether yours qualify, so it does not price this",
    "destination_not_supported": "This destination is not priced yet",
    "currency_mismatch": "Price must be set in the destination currency",
    "over_low_value_limit": "Order value is above the low-value limit for flat-duty entry",
    "seller_not_ioss": "EU is available for IOSS-registered sellers only",
    "no_rule_valid_on_date": "No rule valid on this date",
    "member_state_required": "Choose an EU member state",
    "vat_rate_not_in_register": "VAT rate not in the register",
}


def audit(conn: Connection, actor: str, action: str, entity: str, entity_id: str, payload: dict | None = None) -> None:
    conn.execute(text("INSERT INTO audit_event (actor, action, entity, entity_id, payload) VALUES (:a, :b, :c, :d, CAST(:p AS jsonb))"),
                 {"a": actor, "b": action, "c": entity, "d": entity_id, "p": json.dumps(payload or {}, default=str)})


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def llm_client() -> LLM | None:
    key = env("ANTHROPIC_API_KEY")
    return HaikuClient(key) if key else None


# ---------------------------------------------------------------- setup
def ensure_fine_print(conn: Connection) -> None:
    conn.execute(text("INSERT INTO fine_print (version, body) VALUES (:v, :b) ON CONFLICT (version) DO NOTHING"), {"v": FINE_PRINT_VERSION, "b": FINE_PRINT})


def inputs_hash(title: str, description: str, label_text: str | None = None) -> str:
    return hashlib.sha256(json.dumps([title.strip().lower(), description.strip().lower(), (label_text or "").strip().lower()]).encode()).hexdigest()


# Text visible on labels or tags in the demo shop's photos, as the seller entered it with each listing.
DEMO_EXTRA = {
    "p_wallet": {"label_text": 'MADE IN CHINA'},
    "p_napkins": {"supplier_hint": "Supplier invoice from a mill near Porto, Portugal is on file"},
    "p_tote": {"supplier_hint": "Blank cotton bags bought from a supplier in Gujarat, India"},
    "p_bowl": {"shop_history": "The seller's accepted stoneware mug was made in the same Stoke studio"},
}


def seed_shop(conn: Connection) -> None:
    ensure_fine_print(conn)
    conn.execute(text("INSERT INTO shop (id, name, country, city, ioss_registered) VALUES (:id, :name, :country, :city, :ioss) ON CONFLICT (id) DO NOTHING"),
                 {**{k: demo.SHOP[k] for k in ("id", "name", "country", "city")}, "ioss": demo.SHOP["ioss_registered"]})
    for p in demo.PRODUCTS:
        conn.execute(text("INSERT INTO product (id, shop_id, sku, title, description, prices, category, inputs_hash) VALUES (:id, :shop, :k, :t, :d, CAST(:pr AS jsonb), :c, :h) ON CONFLICT (id) DO NOTHING"),
                     {"id": p["id"], "shop": demo.SHOP["id"], "k": p["sku"], "t": p["title"], "d": p["description"], "pr": json.dumps(p["prices"]), "c": p["category"],
                      "h": inputs_hash(p["title"], p["description"], DEMO_EXTRA.get(p["id"], {}).get("label_text"))})
        conn.execute(text("UPDATE product SET sku = :k WHERE id = :id AND sku IS NULL"), {"k": p["sku"], "id": p["id"]})  # a database seeded before SKUs existed


# ---------------------------------------------------------------- register helpers
def _desc_from_ref(ref: str, code: str) -> str:
    m = re.match(rf"HTS {re.escape(code)}: (.*?)\. USITC", ref)
    return m.group(1) if m else ref[:80]


def us_lines(conn: Connection, version: int, hs6: str) -> list[dict]:
    """Register lines under a 6-digit subheading that have a pure ad valorem general rate (the lines the engine can price)."""
    digits = hs6.replace(".", "")
    try:  # the full description path from the recorded HTS export ("Other bed linen > Of cotton > ..."), not just the last words
        paths = {ln["code"]: ln["path"] for ln in duty_lines(hs6)}
    except (OSError, KeyError, ValueError):
        paths = {}
    out = []
    for r in repo.rows_visible(conn, version, "US", prefix=digits):
        if r["measure"] == "base_duty" and r["code"].replace(".", "").startswith(digits) and len(r["code"].replace(".", "")) > 6:
            out.append({"code": r["code"], "rate": r["rate"], "description": paths.get(r["code"]) or _desc_from_ref(r["source_ref"], r["code"])})
    return out


def gb_code(conn: Connection, version: int, hs6: str) -> str | None:
    digits = hs6.replace(".", "")
    for r in repo.rows_visible(conn, version, "GB", prefix=digits):
        if r["measure"] == "base_duty" and r["code"].startswith(digits):
            return r["code"]
    return None


def national_for(conn: Connection, llm: LLM | None, listing: Listing, hs6: str, version: int, cache: dict) -> dict | None:
    if hs6 in cache:
        return cache[hs6]
    lines = us_lines(conn, version, hs6)
    # keep leaf-like lines: drop a line if a more specific line under it is also present
    codes = [ln["code"] for ln in lines]
    lines = [ln for ln in lines if not any(c != ln["code"] and c.startswith(ln["code"]) for c in codes)]
    if llm is None or not lines:
        cache[hs6] = None
        return None
    pick = pick_national(llm, listing, hs6, lines)
    cache[hs6] = pick.model_dump() if pick else None
    return cache[hs6]


# ---------------------------------------------------------------- recommend
_SECTIONS = [(5, "Food and animals"), (14, "Plants and food"), (15, "Food and oils"), (24, "Food and drink"), (27, "Minerals and fuels"), (38, "Chemicals"),
             (40, "Plastics and rubber"), (43, "Leather and fur"), (46, "Wood and cork"), (49, "Paper and books"), (63, "Textiles and clothing"), (67, "Footwear and hats"),
             (70, "Ceramics and glass"), (71, "Jewellery"), (83, "Metal goods"), (85, "Electronics and machinery"), (89, "Vehicles"), (92, "Instruments"),
             (93, "Arms"), (96, "Toys, furniture and misc"), (97, "Art and antiques")]


def category_for(hs6: str) -> str:
    """A plain shopper-facing category from the tariff chapter (the first two digits of the code)."""
    ch = int(hs6[:2]) if hs6[:2].isdigit() else 0
    if ch in (42,):
        return "Leather goods and bags"
    if ch in (61, 62):
        return "Clothing"
    if ch in (69, 70):
        return "Ceramics and glass"
    if ch in (94, 95):
        return "Furniture and toys"
    for upto, label in _SECTIONS:
        if ch <= upto:
            return label
    return "Other goods"


def _listing(conn: Connection, prod: dict, product_id: str) -> Listing:
    extra = DEMO_EXTRA.get(product_id, {})
    country = conn.execute(text("SELECT country FROM shop WHERE id = :i"), {"i": prod["shop_id"]}).scalar_one_or_none() or demo.SHOP["country"]
    return Listing(title=prod["title"], description=prod["description"], shop_country=country, **extra)


def _cart(code: str, origin: str, price: str, sku: str = "item") -> list[dict]:
    return [{"sku": sku, "code": code, "origin": origin, "unit_price": price, "quantity": 1}]


def recommend(conn: Connection, product_id: str, llm: LLM | None, force: bool = False) -> dict | None:
    """Run the pipeline for one product and store the recommendation. Identical listings reuse the last result."""
    prod = conn.execute(text("SELECT * FROM product WHERE id = :i"), {"i": product_id}).mappings().one()
    if not force:
        own = conn.execute(text("SELECT id, inputs_hash FROM recommendation WHERE product_id = :p ORDER BY created_at DESC LIMIT 1"), {"p": product_id}).first()
        if own and own[1] == prod["inputs_hash"]:  # a recommendation for an earlier wording of the listing is not reused
            return {"id": own[0], "cached": True}
        # An identical listing (same title and description) already has a recommendation: this product gets its own copy of it, with no model call.
        # Only when the photos are the same too (a recommendation carries what the AI read in them), and never for goods the refusal screen now catches: a rule added later applies to a reused answer as well.
        twin = conn.execute(text("""SELECT r.* FROM recommendation r JOIN product p ON p.id = r.product_id
                                    WHERE r.inputs_hash = :h AND p.images = CAST(:im AS jsonb) ORDER BY r.created_at DESC LIMIT 1"""),
                            {"h": prod["inputs_hash"], "im": json.dumps(prod["images"] or [])}).mappings().first()
        if twin and regulated_term(_listing(conn, dict(prod), product_id)) is None:
            rid = new_id("rec")
            conn.execute(text("""INSERT INTO recommendation (id, product_id, payload, band, register_version, model, prompt_version, inputs_hash)
                                 VALUES (:id, :p, CAST(:pl AS jsonb), :b, :v, :m, :pv, :h)"""),
                         {"id": rid, "p": product_id, "pl": json.dumps(twin["payload"]), "b": twin["band"], "v": twin["register_version"], "m": twin["model"],
                          "pv": twin["prompt_version"], "h": prod["inputs_hash"]})
            audit(conn, "system:recommender", "recommendation_reused", "recommendation", rid, {"copied_from": twin["id"], "product": product_id})
            return {"id": rid, "cached": True}
    if llm is None:
        return None  # "Claude API down": listing stays Not yet reviewed, checkout unaffected
    listing = _listing(conn, prod, product_id)
    seen = photos.read_for_product(conn, dict(prod), llm)  # photos are read once, text kept; a photo that cannot be read never blocks the recommendation
    if seen["label_text"] and not listing.label_text:
        listing = listing.model_copy(update={"label_text": seen["label_text"]})
    if seen["materials"]:
        listing = listing.model_copy(update={"photo_materials": seen["materials"]})
    raw, cands = classify_wide(llm, listing)
    us_ondemand.ensure_headings(conn, sorted({k[:4] for k in cands}), us_fetch)  # the chosen headings' lines enter the register, with source and date
    version = repo.latest_version(conn)
    cache: dict = {}
    usd = prod["prices"]["USD"]
    on = date.today()

    def quoter(hs6: str, origin: str) -> Decimal | None:
        nat = national_for(conn, llm, listing, hs6, version, cache)
        if nat is None:
            return None
        res = price_cart(conn, "US", _cart(nat["code"], origin, usd), on, version, window=0)
        return res.tax_total if res.supported else None

    def nat_result(hs6: str) -> NationalResult | None:
        nat = national_for(conn, llm, listing, hs6, version, cache)
        return NationalResult(**nat) if nat else None

    def line_quoter(code: str, origin: str) -> Decimal | None:
        res = price_cart(conn, "US", _cart(code, origin, usd), on, version, window=0)
        return res.tax_total if res.supported else None

    d: Decision | None = decide(raw.a, raw.b, listing, quoter, Decimal(usd), national=nat_result, quote_line=line_quoter)
    if d is None:
        audit(conn, "system:recommender", "recommend_failed", "product", product_id, {"errors": raw.errors})
        return None
    national_for(conn, llm, listing, d.hs6, version, cache)
    # The UK side prices only subheadings it has a rate for: read the UK Trade Tariff for this one (and the runner-up) if not, then lock the new register version.
    if any(o.loaded for o in uk_ondemand.ensure_many(conn, [d.hs6, d.runner_up or ""], uk_get).values()):
        version = repo.latest_version(conn)
    if d.hs6 != "none":
        conn.execute(text("UPDATE product SET category = :c WHERE id = :i"), {"c": category_for(d.hs6), "i": product_id})
    rid = new_id("rec")
    payload = {"decision": d.model_dump(mode="json"), "national": cache, "errors": raw.errors, "photo_reads": seen["reads"], "usage": getattr(llm, "usage", None) and {
        "calls": llm.usage.calls, "input_tokens": llm.usage.input_tokens, "output_tokens": llm.usage.output_tokens}}  # type: ignore[attr-defined]
    conn.execute(text("""INSERT INTO recommendation (id, product_id, payload, band, register_version, model, prompt_version, inputs_hash)
                         VALUES (:id, :p, CAST(:pl AS jsonb), :b, :v, :m, :pv, :h)"""),
                 {"id": rid, "p": product_id, "pl": json.dumps(payload), "b": d.band, "v": version, "m": MODEL, "pv": PROMPT_VERSION, "h": prod["inputs_hash"]})
    audit(conn, "system:recommender", "recommended", "recommendation", rid,
          {"model": MODEL, "prompt_version": PROMPT_VERSION, "inputs_hash": prod["inputs_hash"], "register_version": version, "band": d.band, "triggers": d.triggers})
    return {"id": rid, "cached": False}


# ---------------------------------------------------------------- read models
def _latest_rec(conn: Connection, product_id: str) -> dict | None:
    r = conn.execute(text("SELECT * FROM recommendation WHERE product_id = :p ORDER BY created_at DESC LIMIT 1"), {"p": product_id}).mappings().first()
    return dict(r) if r else None


def _latest_decision(conn: Connection, product_id: str) -> dict | None:
    """The seller's decision that still applies: one made before the listing last changed (a feed sync sets product.changed_at) is not current."""
    r = conn.execute(text("SELECT d.* FROM decision d JOIN product p ON p.id = d.product_id WHERE d.product_id = :p AND (p.changed_at IS NULL OR d.at >= p.changed_at) "
                          "ORDER BY d.at DESC LIMIT 1"), {"p": product_id}).mappings().first()
    return dict(r) if r else None


def listing_changed(conn: Connection, product_id: str) -> bool:
    """True when the seller decided on an earlier wording of this listing and has not decided again since the feed changed it."""
    if _latest_decision(conn, product_id) is not None:
        return False
    return conn.execute(text("SELECT EXISTS (SELECT 1 FROM decision WHERE product_id = :p)"), {"p": product_id}).scalar_one()


def effective(rec: dict, decision: dict | None) -> tuple[str, str, str]:
    """(hs6, origin, US national code) after the seller's answers and any override."""
    d = rec["payload"]["decision"]
    answers = rec["answers"] or {}
    hs6, origin, line = d["hs6"], d["origin"], None
    for q in d["questions"]:
        a = answers.get(q["id"])
        if a:
            val = next((o["value"] for o in q["options"] if o["id"] == a), None)
            if val and q["id"] == "q_origin":
                origin = val
            if val and q["id"] == "q_code":
                hs6 = val
            if val and q["id"] == "q_line":
                line = val
    nat = (rec["payload"]["national"].get(hs6) or {}).get("code") or ""
    if line and line.replace(".", "").startswith(hs6.replace(".", "")):  # the seller chose between two tariff lines of this subheading
        nat = line
    if decision:
        if hs6 == "none":  # the seller supplied the code Landfall could not find: its 6-digit part is the subheading from here on
            d6 = "".join(ch for ch in decision["code"] if ch.isdigit())[:6]
            hs6 = f"{d6[:4]}.{d6[4:6]}"
        return hs6, decision["origin"], decision["code"]
    return hs6, origin, nat


def open_questions(rec: dict) -> list[dict]:
    answers = rec["answers"] or {}
    return [q for q in rec["payload"]["decision"]["questions"] if q["id"] not in answers]


def _pricing(conn: Connection, prod: dict, hs6: str, origin: str, us_code: str, version: int, paused: str | None) -> list[s.DestinationPricing]:
    label = repo.version_label(conn, version)
    out: list[s.DestinationPricing] = []
    on = date.today()
    for dest in ("US", "EU", "GB", "AU"):
        cur = demo.DEST_CURRENCY[dest]
        if cur not in prod["prices"] and not paused:
            out.append(s.DestinationPricing(destination=dest, supported=False, rule_applied=f"Not sold in {cur} yet", duty_and_tax=None,  # type: ignore[arg-type]
                                            as_of=None, register_version=label, paused_reason=f"Set a price in {cur} to sell to {demo.DEST_LABEL[dest]}: Landfall never converts currency"))
            continue
        if paused:
            out.append(s.DestinationPricing(destination=dest, supported=False, rule_applied="Not available for duties-included", duty_and_tax=None,  # type: ignore[arg-type]
                                            as_of=None, register_version=label, paused_reason=paused))
            continue
        code = us_code if dest in ("US", "EU", "AU") else (gb_code(conn, version, hs6) or "")
        if not code or (dest in ("US", "EU", "AU") and not us_code):
            out.append(s.DestinationPricing(destination=dest, supported=False, rule_applied="No priced line yet", duty_and_tax=None,  # type: ignore[arg-type]
                                            as_of=on, register_version=label, paused_reason="No priced national line for this code yet"))
            continue
        res = price_cart(conn, dest, _cart(code, origin, prod["prices"][cur]), on, version)
        if not res.supported:
            msg = UNSUPPORTED.get(res.unsupported_reason or "", res.unsupported_reason or "")
            out.append(s.DestinationPricing(destination=dest, supported=False, rule_applied=msg, duty_and_tax=None, as_of=on,  # type: ignore[arg-type]
                                            register_version=label, paused_reason=msg))
            continue
        flat = None
        if dest == "EU":
            flat = f"€{res.duty_total:.2f} + VAT"
        out.append(s.DestinationPricing(
            destination=dest, supported=True, rule_applied=res.rule_summary, duty_and_tax=None if res.home_market else money(res.tax_total, cur),  # type: ignore[arg-type]
            flat_label=("None" if res.home_market else flat), as_of=None if res.home_market else on,
            register_version=None if res.home_market else label, trail=trail_lines(res)))
    return out


def build_recommendation(conn: Connection, prod: dict, rec: dict, decision: dict | None) -> s.Recommendation:
    d = rec["payload"]["decision"]
    hs6, origin, us_code = effective(rec, decision)
    version = rec["register_version"]
    cur_version = repo.latest_version(conn) or version
    opens = open_questions(rec)
    qs = []
    for q in d["questions"]:
        qs.append(s.Question(
            id=q["id"], trigger=q["trigger"], text=q["text"], help=q.get("help"), evidence_crop_label=q.get("evidence"),
            options=[s.QuestionOption(id=o["id"], label=o["label"], is_ai_pick=o["is_ai_pick"],
                                      price_impact=None if o["impact"] is None else money(Decimal(str(o["impact"])), "USD")) for o in q["options"]]))
    headline = d["headline"] if opens or not d["questions"] else "Answered: the estimate now reflects your answers"
    sources = [s.SourceRef(label=f"USITC HTS {us_code}", url=f"https://hts.usitc.gov/search?query={us_code}")] if us_code else []
    refused = bool(d.get("paused_reason") and d["paused_reason"].startswith("Landfall will not price this"))  # legal, safety or moral: no lookup help
    terms = search_terms(prod["title"], prod["description"])
    band_out = "high" if (d["questions"] and not opens) else d["band"]
    if origin_unpriced(origin):  # the goods come from somewhere Landfall does not price: never "High confidence", and say what happens
        band_out = "check"
    return s.Recommendation(
        help_terms=terms, help_links=[] if refused else help_links(terms, None if hs6 == "none" else (us_code or hs6)),
        help_prominent=(not refused) and not decision and (hs6 == "none" or band_out != "high" or bool(d.get("paused_reason"))),
        id=rec["id"], product_id=prod["id"], code=us_code or hs6, code6=hs6, code_description=describe(hs6),
        code_reason=d["code_reason"] + (f" National line: {rec['payload']['national'].get(hs6, {}).get('reason', '').rstrip('. ')}." if rec["payload"]["national"].get(hs6) else ""),
        code_sources=sources, runner_up=d.get("runner_up"), origin=origin, origin_reason=d["origin_reason"],
        origin_signals=[s.OriginSignal(kind=x["kind"], text=x["text"], points_to=x.get("points_to")) for x in d["signals"]],
        band=band_out, triggers=d["triggers"], headline=("Origin not covered: buyers check out normally, with no duty added by Landfall" if origin_unpriced(origin) else headline), questions=qs,
        pricing=_pricing(conn, dict(prod), hs6, origin, us_code, cur_version, _open_pause(d, decision)),
        photo_reads=photos.view(rec["payload"].get("photo_reads") or []),
        model=rec["model"], prompt_version=rec["prompt_version"], register_version=repo.version_label(conn, version),
        created_at=rec["created_at"])


def _open_pause(d: dict, decision: dict | None) -> str | None:
    """The pause that still applies: a seller's override with their own code lifts "no code found", never a refusal for legal, safety or moral reasons."""
    p = d.get("paused_reason")
    if p and decision and not p.startswith("Landfall will not price this"):
        return None
    return p


def product_view(conn: Connection, prod: dict) -> s.Product:
    rec = _latest_rec(conn, prod["id"])
    dec = _latest_decision(conn, prod["id"])
    p = dict(id=prod["id"], shop_id=prod["shop_id"], sku=prod.get("sku"), title=prod["title"], description=prod["description"], photo_url=prod["photo_url"],
             prices=prod["prices"], category=prod["category"], review_status=dec["action"] if dec else "not_reviewed",
             listing_changed=listing_changed(conn, prod["id"]), image_urls=list(prod.get("images") or []))
    if rec is None:
        return s.Product(**p, band=None, code=None, origin=None, ai_note="Recommendation pending", question_count=0)
    d = rec["payload"]["decision"]
    hs6, origin, us_code = effective(rec, dec)
    opens = open_questions(rec)
    band = "high" if (d["questions"] and not opens) else d["band"]
    if origin_unpriced(origin):
        band = "check"  # origin outside what Landfall prices: not High confidence
    uncertain = bool(opens) and any(q["id"] == "q_origin" for q in opens)
    note = shorten(next((x["text"] for x in d["signals"] if x["kind"] == "label_photo"), None) or d["code_reason"], 110)
    return s.Product(**p, band=band, code=us_code or hs6, origin=origin, origin_uncertain=uncertain, ai_note=note,
                     question_count=len(opens), paused_reason=_open_pause(d, dec))


def get_prod(conn: Connection, product_id: str) -> dict:
    r = conn.execute(text("SELECT * FROM product WHERE id = :i"), {"i": product_id}).mappings().first()
    if r is None:
        raise LookupError(product_id)
    return dict(r)


def product_detail(conn: Connection, product_id: str) -> s.ProductDetail:
    prod = get_prod(conn, product_id)
    rec = _latest_rec(conn, product_id)
    dec = _latest_decision(conn, product_id)
    return s.ProductDetail(product=product_view(conn, prod), recommendation=build_recommendation(conn, prod, rec, dec) if rec else None,
                           fine_print_version=FINE_PRINT_VERSION, fine_print=FINE_PRINT)


def catalogue(conn: Connection, shop: dict | None = None) -> s.Catalogue:
    shop = shop or demo.SHOP
    rows = [dict(r) for r in conn.execute(text("SELECT * FROM product WHERE shop_id = :s AND active ORDER BY created_at, id"), {"s": shop["id"]}).mappings()]
    products = [product_view(conn, r) for r in rows]
    ready = sum(1 for p in products if p.review_status != "not_reviewed" and not p.paused_reason)
    high = sum(1 for p in products if bulk_block_reason(p) is None)
    stamps = conn.execute(text("SELECT count(*) FROM stamp WHERE shop_id = :s"), {"s": shop["id"]}).scalar_one()
    return s.Catalogue(shop=s.Shop(**{k: shop[k] for k in ("id", "name", "country", "city", "ioss_registered")}), summary=s.CatalogueSummary(
        ready_count=ready, total_count=len(products), ready_after_accept=ready + high, passport_countries=stamps, radar_next_days=None,
        radar_next_affects=0, high_band_open=high), products=products)


# ---------------------------------------------------------------- answers and decisions
def bulk_block_reason(p: s.Product) -> str | None:
    """Bulk accept is for the High band only (FR-13)."""
    if p.review_status != "not_reviewed":
        return "Already reviewed"
    if p.paused_reason:
        return "Not available for duties-included"
    if p.question_count > 0:
        return "Answer the questions first"
    if p.band != "high":
        return "Check this one on its own" if p.band == "check" else "Needs your answers"
    return None


def answer(conn: Connection, llm: LLM | None, rec_id: str, question_id: str, option_id: str, user: str = SELLER) -> s.AnswerOut:
    rec = conn.execute(text("SELECT * FROM recommendation WHERE id = :i"), {"i": rec_id}).mappings().first()
    if rec is None:
        raise LookupError(rec_id)
    rec = dict(rec)
    q = next((q for q in rec["payload"]["decision"]["questions"] if q["id"] == question_id), None)
    if q is not None and question_id == "q_origin" and not any(o["id"] == option_id for o in q["options"]):
        # "Somewhere else": the seller names any country Landfall prices (origin_XX). It joins the question's options, so everything downstream reads it like any other answer.
        m = re.fullmatch(r"origin_([A-Z]{2})", option_id)
        if m and m.group(1) in covered_origin_codes(conn):
            q["options"].append({"id": option_id, "label": ORIGIN_NAMES[m.group(1)], "value": m.group(1), "is_ai_pick": False, "impact": _origin_impact(conn, rec, m.group(1))})
            conn.execute(text("UPDATE recommendation SET payload = CAST(:p AS jsonb) WHERE id = :i"), {"p": json.dumps(rec["payload"]), "i": rec_id})
    if q is None or not any(o["id"] == option_id for o in q["options"]):
        raise ValueError("Unknown question or option")
    answers = {**(rec["answers"] or {}), question_id: option_id}
    conn.execute(text("UPDATE recommendation SET answers = CAST(:a AS jsonb) WHERE id = :i"), {"a": json.dumps(answers), "i": rec_id})
    rec["answers"] = answers
    if question_id == "q_code":  # a different 6-digit code needs its national line
        prod = get_prod(conn, rec["product_id"])
        hs6 = next(o["value"] for o in q["options"] if o["id"] == option_id)
        cache = rec["payload"]["national"]
        if hs6 not in cache or cache[hs6] is None:
            national_for(conn, llm, _listing(conn, prod, prod["id"]), hs6, rec["register_version"], cache)
            conn.execute(text("UPDATE recommendation SET payload = CAST(:p AS jsonb) WHERE id = :i"), {"p": json.dumps(rec["payload"]), "i": rec_id})
    audit(conn, user, "answered", "recommendation", rec_id, {"question": question_id, "option": option_id})
    prod = get_prod(conn, rec["product_id"])
    return s.AnswerOut(recommendation=build_recommendation(conn, prod, rec, _latest_decision(conn, rec["product_id"])), remaining_questions=len(open_questions(rec)))


def decide_product(conn: Connection, rec_id: str, body: s.DecisionIn, user: str = SELLER) -> s.Decision:
    rec = conn.execute(text("SELECT * FROM recommendation WHERE id = :i"), {"i": rec_id}).mappings().first()
    if rec is None:
        raise LookupError(rec_id)
    rec = dict(rec)
    if not conn.execute(text("SELECT 1 FROM fine_print WHERE version = :v"), {"v": body.fine_print_version}).first():
        raise ValueError("Unknown fine-print version")
    paused = rec["payload"]["decision"].get("paused_reason")
    if paused and (paused.startswith("Landfall will not price this") or body.action != "overridden" or not body.code):
        raise PermissionError(paused)  # goods refused for legal, safety or moral reasons can never be accepted; "no code found" can only be overridden with a code
    hs6, origin, us_code = effective(rec, None)
    if body.action == "overridden":
        code, origin = (body.code or us_code), (body.origin or origin)
        code = _check_override_code(conn, code)
        if (origin or "").lower() == "other":
            origin = "other"  # "a country Landfall does not price yet": buyers check out normally, no duty added
        elif not re.fullmatch(r"[A-Za-z]{2}", origin or ""):
            raise ValueError("The country of origin must be a two-letter country code")
        else:
            origin = origin.upper()
    else:
        code = us_code
    if not code:
        raise ValueError("No national code to accept yet")
    did = new_id("dec")
    conn.execute(text("""INSERT INTO decision (id, recommendation_id, product_id, action, code, origin, fine_print_version, evidence_ref, user_id)
                         VALUES (:i, :r, :p, :a, :c, :o, :f, :e, :u)"""),
                 {"i": did, "r": rec_id, "p": rec["product_id"], "a": body.action, "c": code, "o": origin, "f": body.fine_print_version, "e": body.evidence_ref, "u": user})
    audit(conn, user, body.action, "decision", did, {"product": rec["product_id"], "code": code, "origin": origin, "fine_print_version": body.fine_print_version})
    row = conn.execute(text("SELECT at FROM decision WHERE id = :i"), {"i": did}).scalar_one()
    return s.Decision(id=did, recommendation_id=rec_id, action=body.action, code=code, origin=origin, fine_print_version=body.fine_print_version,
                      evidence_ref=body.evidence_ref, at=row)


def _check_override_code(conn: Connection, code: str) -> str:
    """A seller-typed code must be a US tariff code Landfall can price (a plain percentage or free line): else say why, plainly."""
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) not in (8, 10) or not re.fullmatch(r"[0-9. ]+", code.strip()):
        raise ValueError("A US tariff code has 8 or 10 digits, like 6912.00.44.00. Use the USITC link on this page to find yours.")
    us_ondemand.ensure_headings(conn, [digits[:4]], us_fetch)
    if not any(r["measure"] == "base_duty" for r in repo.rows_visible(conn, repo.latest_version(conn), "US", prefix=digits)):
        raise ValueError(f"Landfall has no priced line for {code.strip()}: the code may not exist, or its duty is not a plain percentage (so it is not priced). "
                         "Check it in the USITC tariff with the link on this page.")
    return f"{digits[:4]}.{digits[4:6]}.{digits[6:8]}" + (f".{digits[8:10]}" if len(digits) == 10 else "")


def bulk_accept(conn: Connection, body: s.BulkAcceptIn, shop: dict | None = None) -> s.BulkAcceptOut:
    accepted, rejected = [], []
    for pid in body.product_ids:
        try:
            owns_product(conn, pid, shop or demo.SHOP)
            prod = get_prod(conn, pid)
        except LookupError:
            rejected.append({"product_id": pid, "reason": "Unknown product"})
            continue
        view = product_view(conn, prod)
        reason = bulk_block_reason(view)
        if reason:
            rejected.append({"product_id": pid, "reason": reason})
            continue
        rec = _latest_rec(conn, pid)
        decide_product(conn, rec["id"], s.DecisionIn(action="accepted", fine_print_version=body.fine_print_version))  # type: ignore[index]
        accepted.append(pid)
    return s.BulkAcceptOut(accepted=accepted, rejected=rejected)


def owns_product(conn: Connection, product_id: str, shop: dict) -> None:
    """A merchant reaches only its own products: any other id is simply unknown to it."""
    if conn.execute(text("SELECT 1 FROM product WHERE id = :i AND shop_id = :s"), {"i": product_id, "s": shop["id"]}).first() is None:
        raise LookupError(product_id)


def owns_recommendation(conn: Connection, rec_id: str, shop: dict) -> None:
    if conn.execute(text("SELECT 1 FROM recommendation r JOIN product p ON p.id = r.product_id WHERE r.id = :i AND p.shop_id = :s"), {"i": rec_id, "s": shop["id"]}).first() is None:
        raise LookupError(rec_id)


def create_product(conn: Connection, body: s.ProductCreate, shop: dict | None = None) -> s.Product:
    shop = shop or demo.SHOP
    pid = new_id("p")
    category = body.category or "other"  # worked out from the code once a recommendation exists
    urls = list(body.image_urls)
    conn.execute(text("INSERT INTO product (id, shop_id, title, description, photo_url, images, prices, category, inputs_hash) "
                      "VALUES (:i, :s, :t, :d, :ph, CAST(:im AS jsonb), CAST(:pr AS jsonb), :c, :h)"),
                 {"i": pid, "s": shop["id"], "t": body.title, "d": body.description, "ph": body.photo_url or (urls[0] if urls else None), "im": json.dumps(urls),
                  "pr": json.dumps(body.prices), "c": category, "h": inputs_hash(body.title, body.description, "|".join(urls) or None)})
    audit(conn, SELLER if shop["id"] == demo.SHOP["id"] else f"seller:{shop['id']}", "created", "product", pid, {"title": body.title})
    return product_view(conn, get_prod(conn, pid))


def seed_recommendations(conn: Connection, llm: LLM | None, include_extra: bool = False) -> list[str]:
    """Recommend every demo product that has none yet (real Haiku calls, stored). Returns product ids that got one.
    The storefront extras (t-shirt, spoons, train, vase) are only recommended when asked for (the app's own start-up does)."""
    done = []
    for p in demo.PRODUCTS:
        if p.get("extra") and not include_extra:
            continue
        if _latest_rec(conn, p["id"]) is None and llm is not None:
            if recommend(conn, p["id"], llm):
                done.append(p["id"])
    return done


def utcnow() -> datetime:
    return datetime.now(UTC)


def seed_demo_decision(conn: Connection, include_extra: bool = False) -> None:
    """The demo shop starts with its storefront products accepted: recorded seller decisions (actor seed:demo-shop), not mocks.

    The demo seller knows their own goods: if the recommender asked which national line fits, or where a product was made, the seed answers with the
    demo facts (the mug: line 6912.00.44.00, made in Britain; any other: the origin named in its listing, then the AI's own pick), each answer audited,
    then accepts. A product that is paused (outside what Landfall prices) is left alone, so the demo shows a product that cannot be priced."""
    for dp in demo.PRODUCTS:
        if not dp.get("accept") or (dp.get("extra") and not include_extra):
            continue
        if dp["id"] != "p_mug" and not include_extra:
            continue  # the original tests and demo accept the mug only
        pid = dp["id"]
        rec = _latest_rec(conn, pid)
        if not rec or _latest_decision(conn, pid) is not None:
            continue
        facts = {"q_origin": "origin_" + dp["origin"]}
        if pid == "p_mug":
            facts["q_line"] = "line_" + dp["codes"]["US"]
        for q in open_questions(rec):
            want = facts.get(q["id"])
            if not (want and any(o["id"] == want for o in q["options"])):
                want = next((o["id"] for o in q["options"] if o["is_ai_pick"]), None)
            if want:
                answer(conn, None, rec["id"], q["id"], want, user="seed:demo-shop")
                rec = _latest_rec(conn, pid)
        if rec["payload"]["decision"].get("paused_reason"):
            continue
        want = demo.SEED_CODES.get(pid)
        _, _, us_code = effective(rec, None)
        try:
            if want and us_code != want:  # the AI's pick varies between runs; the demo seller's recorded decision does not
                decide_product(conn, rec["id"], s.DecisionIn(action="overridden", code=want, origin=dp["origin"], fine_print_version=FINE_PRINT_VERSION), user="seed:demo-shop")
            elif not open_questions(rec):
                decide_product(conn, rec["id"], s.DecisionIn(action="accepted", fine_print_version=FINE_PRINT_VERSION), user="seed:demo-shop")
        except (ValueError, PermissionError):
            pass  # no national code to accept: leave it for the seller
