"""API contract. The web app generates its TypeScript types from the OpenAPI schema of these models.

Conventions
- Money is a string decimal plus a currency code, never a float. Landfall never converts currency.
- Dates are ISO dates (YYYY-MM-DD); timestamps are ISO 8601 UTC.
- Words: the AI gives a "recommendation". Never "ruling" or "determination".
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Destination = Literal["US", "EU", "GB", "AU", "CA"]
Band = Literal["high", "check", "ask"]
ReviewStatus = Literal["not_reviewed", "accepted", "overridden"]
Trigger = Literal["T1", "T2", "T3", "T4", "T5", "T6"]
Currency = Literal["USD", "GBP", "EUR", "AUD", "CAD"]


class Money(BaseModel):
    amount: str = Field(examples=["7.60"])
    currency: Currency


# ---------------------------------------------------------------- shop and catalogue
class Shop(BaseModel):
    id: str
    name: str
    country: str
    city: str
    ioss_registered: bool
    sandbox_label: str = "PayPal sandbox"


class SourceRef(BaseModel):
    label: str
    url: str | None = None
    document_id: str | None = None


class Product(BaseModel):
    id: str
    shop_id: str
    sku: str | None = Field(default=None, description="The merchant's own SKU, so its checkout can name the product the way its store does")
    title: str
    description: str
    photo_url: str | None = None
    prices: dict[Currency, str]
    category: str
    review_status: ReviewStatus
    band: Band | None = None
    code: str | None = Field(default=None, description="Accepted or recommended code, as displayed")
    origin: str | None = None
    origin_uncertain: bool = False
    ai_note: str | None = None
    question_count: int = 0
    paused_reason: str | None = Field(default=None, description="T5: duties-included not available")
    image_urls: list[str] = Field(default_factory=list, description="The product's photo addresses")
    listing_changed: bool = Field(default=False, description="The store changed this listing after the seller's decision: review again. Until then it is not priced duty-paid")


class MerchantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    country: str = Field(pattern=r"^[A-Z]{2}$", description="ISO-2 country the shop ships from")
    city: str = Field(min_length=2, max_length=80)

    @field_validator("name", "city")
    @classmethod
    def _plain(cls, v: str) -> str:
        from .services.merchants import check_text

        return check_text(" ".join(v.split()))


class MerchantCreated(BaseModel):
    shop_id: str
    name: str
    country: str
    city: str
    api_key: str = Field(description="Shown once. Landfall keeps only a hash of it.")
    api_key_prefix: str
    publishable_key: str = Field(description="Quote-only and safe to put in a web page: the checkout widget sends it. It cannot import, order or read anything.")


class MerchantMe(BaseModel):
    shop_id: str
    name: str
    country: str
    city: str
    api_key_prefix: str | None
    publishable_key: str | None = None
    feed_url: str | None
    product_count: int
    last_synced_at: datetime | None = None


class ImportIn(BaseModel):
    feed_url: str = Field(min_length=8, max_length=500, description="The store's public product feed, for example https://shop.example/products.json")
    currency: Currency = Field(description="Currency of the feed's plain prices (feeds that carry presentment prices bring their own)")


class ImportSkipped(BaseModel):
    title: str
    reason: str


class ImportOut(BaseModel):
    created: list[Product]
    updated: list[Product]
    skipped: list[ImportSkipped]


class SyncOut(BaseModel):
    added: int
    price_updated: int
    changed: int = Field(description="Title or description changed in the feed: the earlier decision no longer applies until the seller reviews again")
    removed: int = Field(description="No longer in the feed: not sold through the checkout")
    restored: int
    skipped: list[ImportSkipped]
    recommended: int = Field(description="New or changed products that now have a recommendation waiting for the seller")
    pending: int = Field(description="New or changed products left without a recommendation (the recommender was unavailable)")
    last_synced_at: datetime


class ProductCreate(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=10, max_length=2000)
    photo_url: str | None = Field(default=None, max_length=500)
    image_urls: list[str] = Field(default_factory=list, max_length=4, description="Up to four photo addresses (https). The AI reads them once for labels, a made-in country and visible materials; Landfall keeps the addresses and the text read, never the image")
    prices: dict[Currency, str] = Field(min_length=1)
    category: str | None = None

    @field_validator("image_urls")
    @classmethod
    def _images(cls, v: list[str]) -> list[str]:
        out = []
        for u in v:
            u = u.strip()
            if not u:
                continue
            if len(u) > 500 or not u.lower().startswith(("https://", "http://")) or any(c in u for c in " \t\r\n<>\"'"):
                raise ValueError("A photo address must be a web address (https://...) without spaces, up to 500 characters")
            if u not in out:
                out.append(u)
        return out

    @field_validator("title", "description")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = "\n".join(" ".join(line.split()) for line in v.strip().splitlines())
        if len(v) < 3:
            raise ValueError("too short")
        return v

    @field_validator("prices")
    @classmethod
    def _prices(cls, v: dict) -> dict:
        import re

        for cur, amount in v.items():
            if not re.fullmatch(r"\d{1,7}(\.\d{1,2})?", amount) or float(amount) <= 0:
                raise ValueError(f"The {cur} price must be a positive number with at most 2 decimals, up to 9,999,999.99")
        return v


class CatalogueSummary(BaseModel):
    ready_count: int
    total_count: int
    ready_after_accept: int
    passport_countries: int
    radar_next_days: int | None
    radar_next_affects: int
    high_band_open: int


class Catalogue(BaseModel):
    shop: Shop
    summary: CatalogueSummary
    products: list[Product]


# ---------------------------------------------------------------- recommendation
class OriginSignal(BaseModel):
    kind: Literal["label_photo", "listing_text", "shop_history", "handmade_claim", "supplier_hint", "shop_country"]
    text: str
    points_to: str | None = None


class QuestionOption(BaseModel):
    id: str
    label: str
    price_impact: Money | None = Field(default=None, description="Change to what the buyer pays if chosen")
    is_ai_pick: bool = False


class Question(BaseModel):
    id: str
    trigger: Trigger
    text: str
    help: str | None = None
    evidence_crop_label: str | None = None
    options: list[QuestionOption]


class TrailLine(BaseModel):
    label: str
    base: Money
    rate: str = Field(examples=["10%"])
    amount: Money
    source_ref: str
    source_url: str | None = None
    row_id: int | None = None


class HelpLink(BaseModel):
    label: str
    url: str
    hint: str


class DestinationPricing(BaseModel):
    destination: Destination
    supported: bool
    rule_applied: str
    duty_and_tax: Money | None
    flat_label: str | None = Field(default=None, description="e.g. EUR 3.00 + VAT")
    as_of: date | None
    register_version: str | None
    paused_reason: str | None = None
    trail: list[TrailLine] = []


class PhotoReadOut(BaseModel):
    url: str
    label_text: str | None = Field(default=None, description="Text printed on the product's own label, tag or packaging")
    made_in: str | None = Field(default=None, description="A country named as the place of manufacture")
    materials: str | None = None
    notes: str | None = None
    error: str | None = Field(default=None, description="Why this photo could not be read, in plain words")


class Recommendation(BaseModel):
    id: str
    product_id: str
    code: str = Field(description="Code for the primary destination as displayed, e.g. 6912.00.44.00")
    code6: str
    code_description: str
    code_reason: str
    code_sources: list[SourceRef]
    runner_up: str | None = None
    origin: str
    origin_reason: str
    origin_signals: list[OriginSignal]
    band: Band
    triggers: list[Trigger]
    headline: str = Field(examples=["No questions needed: both likely codes cost the same"])
    questions: list[Question]
    pricing: list[DestinationPricing]
    help_terms: str = Field(default="", description="Search words taken from the listing, already filled into the help links")
    help_links: list[HelpLink] = Field(default_factory=list, description="Official places to look the code up; empty for goods Landfall will not price for legal, safety or moral reasons")
    help_prominent: bool = Field(default=False, description="True when Landfall found no code or is not confident: the links lead the page")
    photo_reads: list[PhotoReadOut] = Field(default_factory=list, description="What the AI read in the product's photos (text only: the photos are not kept)")
    model: str
    prompt_version: str
    register_version: str
    created_at: datetime


class ProductDetail(BaseModel):
    product: Product
    recommendation: Recommendation | None
    fine_print_version: str
    fine_print: str


class AnswerIn(BaseModel):
    question_id: str
    option_id: str


class AnswerOut(BaseModel):
    recommendation: Recommendation
    remaining_questions: int


class DecisionIn(BaseModel):
    action: Literal["accepted", "overridden"]
    code: str | None = None
    origin: str | None = None
    fine_print_version: str
    evidence_ref: str | None = Field(default=None, description="Optional. Never required.")


class Decision(BaseModel):
    id: str
    recommendation_id: str
    action: Literal["accepted", "overridden"]
    code: str
    origin: str
    fine_print_version: str
    evidence_ref: str | None
    at: datetime


class BulkAcceptIn(BaseModel):
    product_ids: list[str]
    fine_print_version: str


class BulkAcceptOut(BaseModel):
    accepted: list[str]
    rejected: list[dict[str, str]] = Field(description="product_id and reason; only the High band is bulk-acceptable")


# ---------------------------------------------------------------- quote, checkout
class QuoteItemIn(BaseModel):
    product_id: str | None = Field(default=None, description="Landfall's product id")
    sku: str | None = Field(default=None, description="The merchant's own SKU (needs the merchant's API key)")
    quantity: int = Field(default=1, ge=1, le=99)

    @model_validator(mode="after")
    def _one_id(self) -> QuoteItemIn:
        if (self.product_id is None) == (self.sku is None):
            raise ValueError("Give each item either product_id or sku, not both and not neither")
        return self


class QuoteIn(BaseModel):
    shop_id: str | None = Field(default=None, description="Only for the keyless demo shop. With an API key the shop is the key's own.")
    destination: Destination | None = Field(default=None, description="Optional when ship_to_country is given: the country decides it")
    items: list[QuoteItemIn] = Field(min_length=1, max_length=50)
    currency: Currency | None = Field(default=None, description="Optional: it is the destination's currency. If given it must match: Landfall never converts.")
    ship_to_country: str | None = Field(default=None, description="ISO-2 ship-to country; with it the destination, member state or province follow")
    region: str | None = Field(default=None, description="Canadian province code (the EU member state goes in eu_member_state)")
    ship_to_postcode: str | None = None
    eu_member_state: str | None = Field(default=None, description="ISO-2 code, EL for Greece")
    import_date: date | None = None


class QuoteLine(BaseModel):
    product_id: str
    sku: str | None = None
    title: str
    quantity: int
    unit_price: Money
    duty_and_tax: Money
    duties_included: bool
    trail: list[TrailLine]
    unpriced_reason: str | None = Field(default=None, description="Plain reason this line carries no duty (not reviewed, not priced, outside what Landfall prices)")
    origin: str | None = None
    code: str | None = None


class Quote(BaseModel):
    destination: Destination
    ship_to_label: str
    currency: Currency
    lines: list[QuoteLine]
    item_total: Money
    shipping: Money
    tax_total: Money
    seller_discount: Money = Field(description="Duty the seller covers (Absorb it on Rule Radar). The duty stays in tax_total in full; this is a separate seller-funded discount.")
    total: Money
    duties_included: bool
    old_way_note: str
    rates_as_of: date
    register_version: str
    ship_to_country: str | None = None
    stale_note: str | None = Field(default=None, description="48 h without a good sync")
    paused_reason: str | None = Field(default=None, description="7 days without a good sync: duties-included paused")
    delivered_duty_paid_note: str
    paypal_purchase_unit: dict[str, Any] | None = Field(default=None, description="The PayPal purchase unit for this cart: amount with its breakdown (tax_total) and the items with their tax, exact to the cent. A merchant with its own PayPal integration puts it into its own create-order call.")
    quote_token: str | None = Field(default=None, description="Signed by Landfall. The merchant's server sends it to /api/quotes/verify with the PayPal order before capturing.")
    quote_expires_at: int | None = Field(default=None, description="Unix seconds. After this the quote must be asked for again.")


class QuoteVerifyIn(BaseModel):
    quote_token: str
    paypal_order: dict[str, Any] = Field(description="The order as PayPal returns it (GET /v2/checkout/orders/{id}), fetched with the merchant's own credentials")


class QuoteVerifyOut(BaseModel):
    valid: bool
    reasons: list[str] = Field(description="Plain reasons when the order does not match the quote; empty when it does")


class OrderCreateIn(BaseModel):
    quote: QuoteIn
    return_url: str
    cancel_url: str


class OrderCreated(BaseModel):
    order_id: str
    paypal_order_id: str
    approve_url: str
    register_version: str
    total: Money
    paypal_purchase_unit: dict[str, Any] | None = Field(default=None, description="The purchase unit Landfall sent to PayPal: amount.breakdown.tax_total and the per-item tax. Shown so a merchant can see where the duty lands.")


class OrderCaptured(BaseModel):
    order_id: str
    paypal_order_id: str
    capture_id: str
    status: str
    tax_total: Money
    register_version: str
    shipment_id: str | None = None
    stamp_minted: Destination | None = None


# ---------------------------------------------------------------- time machine (public)
class TimeMachineOption(BaseModel):
    id: str
    label: str


class TimeMachinePoint(BaseModel):
    date: date
    buyer_total: Money
    duty_and_tax: Money
    is_change_date: bool = False
    is_future: bool = False
    illustrative: bool = False
    label: str | None = None
    source_ref: str | None = None
    source_url: str | None = None


class TimeMachineSeries(BaseModel):
    product_id: str
    product_label: str
    origin_id: str
    origin_label: str
    destination: Destination
    destination_label: str
    item_price: Money
    shipping: Money
    headline: str
    points: list[TimeMachinePoint]
    today: date
    sources: list[str]
    has_illustrative: bool
    register_version: str


class TimeMachineOptions(BaseModel):
    products: list[TimeMachineOption]
    origins: list[TimeMachineOption]
    destinations: list[TimeMachineOption]


# ---------------------------------------------------------------- radar
class RadarAlert(BaseModel):
    id: str
    destination: Destination
    effective_from: date | None
    effective_label: str
    days_left: int | None
    title: str
    summary: str
    affected_product_ids: list[str]
    impact_per_order: Money | None
    source_url: str | None
    status: Literal["act", "further_out", "watching", "in_effect"]
    choice: Literal["absorb", "pass_on"] | None = None
    scheduled_price_change: str | None = None


class RadarChoiceIn(BaseModel):
    choice: Literal["absorb", "pass_on"]


# ---------------------------------------------------------------- passport
class Stamp(BaseModel):
    destination: Destination | str
    label: str
    earned_on: date | None
    product_count: int = 0
    note: str | None = None
    earned: bool


class LevelRequirement(BaseModel):
    text: str
    done: bool


class Passport(BaseModel):
    level: int
    level_name: str
    next_level_progress_pct: int
    stamps: list[Stamp]
    next_stamps: list[Stamp]
    requirements: list[LevelRequirement]
    badge_headline: str
    badge_subline: str
    badge_image_url: str
    share_url: str


# ---------------------------------------------------------------- ops
class SourceHealth(BaseModel):
    id: str
    name: str
    last_success_at: datetime | None
    rows_changed: int
    future_dated: int
    publish: Literal["automatic", "needs_review"]
    health: Literal["ok", "stale_48h", "paused_7d"]
    detail: str | None = None


class SyncStatus(BaseModel):
    register_version: str
    sources: list[SourceHealth]
    shipment_cross_check: list[CrossCheck] = []


class CrossCheck(BaseModel):
    order_id: str
    our_duty: Money
    easyship_duty: Money | None
    difference: Money | None
    note: str


class QuotedField(BaseModel):
    value: str | None
    quote: str | None = Field(description="Sentence the value came from. Blank field if the model found none.")


class RuleProposal(BaseModel):
    id: str
    notice_title: str
    notice_doc_number: str
    notice_url: str
    notice_published: date
    notice_excerpt: str
    destination: QuotedField
    code_pattern: QuotedField
    origin_scope: QuotedField
    measure: QuotedField
    rate: QuotedField
    valid_from: QuotedField
    valid_to: QuotedField
    products_affected: int
    sellers_affected: int
    status: Literal["pending", "approved", "edited", "rejected"]
    model: str
    prompt_version: str


class RuleEditIn(BaseModel):
    destination: str | None = None
    code_pattern: str | None = None
    origin_scope: str | None = None
    measure: str | None = None
    rate: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None


# ---------------------------------------------------------------- how it works
class HowItWorks(BaseModel):
    steps: list[dict[str, str]]
    sources: list[str]
    powers: list[str]
    scope_note: str
    ai_note: str
    sample_register_version: str


SyncStatus.model_rebuild()


# ---------------------------------------------------------------- storefront (buyer side)
class ShipToCountry(BaseModel):
    country: str
    name: str
    destination: Destination
    currency: Currency
    region: str | None = None


class ShopProduct(BaseModel):
    id: str
    title: str
    description: str
    category: str
    origin: str | None
    prices: dict[Currency, str]
    photo_url: str | None = None
    duties_included: bool = Field(description="True when the seller has accepted a code and origin: the buyer pays duty in the price")
    note: str | None = Field(default=None, description="Plain reason when duties are not included")
    blocked: bool = Field(default=False, description="True for goods Landfall will not handle for legal, safety or moral reasons: they cannot be added to a cart")


class Storefront(BaseModel):
    shop: Shop
    countries: list[ShipToCountry]
    products: list[ShopProduct]


class ReceiptLine(BaseModel):
    title: str
    quantity: int
    unit_price: Money
    duty_and_tax: Money
    duties_included: bool
    unpriced_reason: str | None = None


class OrderReceipt(BaseModel):
    order_id: str
    paypal_order_id: str
    status: str
    capture_id: str | None
    ship_to_label: str
    lines: list[ReceiptLine]
    item_total: Money
    shipping: Money
    tax_total: Money
    seller_discount: Money
    total: Money
    duties_included: bool
    register_version: str
    rates_as_of: date
    shipment_id: str | None = None
    delivered_duty_paid_note: str


# ---------------------------------------------------------------- assistant
class AssistantIn(BaseModel):
    question: str = Field(max_length=2000)


class AssistantReply(BaseModel):
    id: int
    question: str
    answer: str
    kind: Literal["explain", "ask", "sources", "refusal"]
    refused: bool = Field(description="True when the assistant declined (asked to decide, to pay less than is due, or off topic). It never decides for the seller.")


# ---------------------------------------------------------------- coverage and sources
class CoverageDestination(BaseModel):
    id: str
    name: str
    note: str | None = None


class CoverageOrigin(BaseModel):
    code: str
    name: str
    destinations: list[str] = Field(description="The destination ids this origin is covered for")


class CoverageSource(BaseModel):
    id: str
    name: str
    provides: str
    refreshed: str
    last_success_at: datetime | None
    status: Literal["ok", "stale", "paused", "no_run_yet", "manual"]
    detail: str | None = None


class Coverage(BaseModel):
    as_of: datetime
    register_version: str
    destinations: list[CoverageDestination]
    origins: list[CoverageOrigin]
    sources: list[CoverageSource]
    stale_rule: str
    pause_rule: str
    disclaimer: str
