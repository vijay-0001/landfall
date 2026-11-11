"""Home page copy. Product rules are in the copy itself: the AI recommends, the seller decides, duty remittance is simulated."""
from __future__ import annotations

from landfall_register import repo
from sqlalchemy import Connection

from .. import schemas as s
from .health import SOURCE_NAMES

STEPS = [
    {"n": "01 · Seller", "title": "Connects a store", "body": "Landfall reads the product feed of the shop the seller already has, photos included, and keeps in step with it every night. Nothing to list twice."},
    {"n": "02 · AI", "title": "Recommends", "body": "A customs code, a country of origin and the duty per destination, with its reasoning and confidence. The seller is asked only when it is genuinely unsure."},
    {"n": "03 · Seller", "title": "Accepts or overrides", "body": "One click, once per product, with the fine print shown. The seller stays responsible for the declaration; evidence is optional."},
    {"n": "04 · Buyer", "title": "Pays one price with PayPal", "body": "The merchant's checkout shows item, shipping and duties in the buyer's currency, before they pay. Landfall never converts currency; PayPal does."},
    {"n": "05 · Partner", "title": "Pays customs", "body": "A prepaid-duty carrier or broker files the entry and remits the duty. Simulated in the hackathon demo."},
]
SOURCES = ["usitc", "uk", "tedb", "federal_register"]


def how_it_works(conn: Connection) -> s.HowItWorks:
    return s.HowItWorks(
        steps=STEPS, sources=[SOURCE_NAMES[k] for k in SOURCES],
        powers=["Duties at checkout", "Tariff Time Machine", "Rule Radar", "Passport stamps"],
        scope_note="Hackathon scope: parcels shipped to the US, the UK, Australia and the EU, for goods made in 12 countries. Not priced yet: Canada, and goods that carry extra steel, aluminium or similar duties (Section 232).",
        ai_note="The AI is a helper. It recommends and explains; it carries no customs or payment risk. The seller accepts or overrides.",
        sample_register_version=repo.version_label(conn, repo.latest_version(conn)))
