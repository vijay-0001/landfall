"""Landfall API. Routes follow docs/hld.md section 10. Each route is implemented as its screen is wired."""
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from landfall_register import loaders
from landfall_register.seed import ensure_curated, ensure_derived, seed_register
from sqlalchemy import Connection

from . import demo
from . import schemas as s
from .config import env
from .db import engine, migrate_all
from .deps import current_shop, get_conn, ops_writer, quote_shop, require_shop, writable_shop
from .services import assistant, checkout, content, merchants, quote_token, storefront, timemachine
from .services import catalogue as cat
from .services import coverage as coverage_svc
from .services import ops as ops_svc
from .services import passport as passport_svc
from .services import radar as radar_svc
from .services.health import seed_initial_runs

STOREFRONT_SEED = os.environ.get("LANDFALL_SEED_STOREFRONT", "on") != "off"  # tests switch it off: they never reach the internet


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrate_all()
    with engine().begin() as conn:
        seed_register(conn)
        ensure_curated(conn, loaders.DATA / "notices.json")
        ensure_derived(conn)  # China and the country duties of note 52, for registers seeded before they existed
        ensure_curated(conn, loaders.DATA / "au_rows.json")  # Australia: general duty, low-value threshold, GST
        ensure_curated(conn, loaders.DATA / "us_special_review.json")  # Section 232 groups that are not priced
        seed_initial_runs(conn)
        cat.seed_shop(conn)
        if env("LANDFALL_KILN_API_KEY"):  # the mock merchant's separate app calls the API with this key (kept in .env, never in the repo)
            merchants.ensure_shop_key(conn, demo.SHOP["id"], env("LANDFALL_KILN_API_KEY"))
        radar_svc.seed_watch_items(conn)
    with engine().begin() as conn:
        cat.seed_recommendations(conn, cat.llm_client(), include_extra=STOREFRONT_SEED)
        cat.seed_demo_decision(conn, include_extra=STOREFRONT_SEED)
    yield


app = FastAPI(title="Landfall API", version="0.1.0", description="Duties-included checkout. Recommendations, not rulings.", lifespan=lifespan)
# The checkout widget calls the quote from a merchant's web page, so browsers must be allowed to. Nothing here uses cookies: every call that does more than quote
# needs the secret key in a header. (Before going live: restrict the origins per merchant. See docs/security-v1.md.)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type", "X-Landfall-Key"], max_age=600)

WIDGET = Path(__file__).parent / "static" / "landfall.js"


@app.get("/api/widget/landfall.js", include_in_schema=False)
def widget_script() -> Response:
    """The checkout widget: one script a merchant adds to its checkout page."""
    return Response(WIDGET.read_text(encoding="utf-8"), media_type="text/javascript; charset=utf-8", headers={"Cache-Control": "public, max-age=300"})


def _keyless_shop(shop_id: str | None, shop: dict) -> None:
    """Without a key only the demo shop can be named. With a key the shop is the key's own and a different shop_id is refused."""
    if shop_id is not None and shop_id != shop["id"]:
        raise ValueError("That shop is not yours: use your own API key")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/merchants", response_model=s.MerchantCreated)
def create_merchant(body: s.MerchantCreate, conn: Connection = Depends(get_conn, scope="function")) -> s.MerchantCreated:
    """Open a merchant account. The API key in the answer is shown once; Landfall keeps only its hash.
    Closed by default: a deployment opens sign-up with LANDFALL_ALLOW_SIGNUP=1 (local runs and tests do). The hosted demo has one merchant, Kiln & Co."""
    if env("LANDFALL_ALLOW_SIGNUP") != "1":
        raise HTTPException(status_code=403, detail="Sign-up is closed on this deployment. The demo merchant is Kiln & Co.; to run your own merchant, run Landfall yourself.")
    return merchants.create_merchant(conn, body)


@app.get("/api/merchants/me", response_model=s.MerchantMe)
def merchant_me(shop: dict = Depends(require_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.MerchantMe:
    return merchants.merchant_me(conn, shop)


@app.post("/api/products/import", response_model=s.ImportOut)
def import_products(body: s.ImportIn, shop: dict = Depends(require_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.ImportOut:
    """Read the store's public product feed (Shopify-style /products.json) into this merchant's catalogue, one product per SKU. No model call here:
    recommendations are requested per product afterwards."""
    try:
        return merchants.import_feed(conn, shop, body.feed_url, body.currency)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.post("/api/products/sync", response_model=s.SyncOut)
def sync_products(shop: dict = Depends(require_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.SyncOut:
    """Re-read the saved feed now (the nightly job does the same for every shop). New products get a recommendation; changed listings must be reviewed again."""
    try:
        return merchants.sync_feed(conn, shop, cat.llm_client())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.get("/api/catalogue", response_model=s.Catalogue)
def catalogue(shop: dict = Depends(current_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.Catalogue:
    return cat.catalogue(conn, shop)


@app.post("/api/products", response_model=s.Product)
def create_product(body: s.ProductCreate, shop: dict = Depends(writable_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.Product:
    return cat.create_product(conn, body, shop)


@app.get("/api/products/{product_id}", response_model=s.ProductDetail)
def get_product(product_id: str, shop: dict = Depends(current_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.ProductDetail:
    try:
        cat.owns_product(conn, product_id, shop)
        return cat.product_detail(conn, product_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail="Unknown product") from e


@app.post("/api/products/{product_id}/recommend", response_model=s.ProductDetail)
def recommend(product_id: str, shop: dict = Depends(writable_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.ProductDetail:
    try:
        cat.owns_product(conn, product_id, shop)
    except LookupError as e:
        raise HTTPException(status_code=404, detail="Unknown product") from e
    llm = cat.llm_client()
    if llm is None:
        raise HTTPException(status_code=503, detail="The recommender is not available right now. The product is saved as Not yet reviewed.")
    cat.recommend(conn, product_id, llm)
    detail = cat.product_detail(conn, product_id)
    if detail.recommendation is None:  # the AI step produced nothing: say so, keep the product, let the seller retry
        raise HTTPException(status_code=503, detail="The AI could not give a recommendation this time. Your product is saved; please try again.")
    return detail


@app.get("/api/products/{product_id}/assistant", response_model=list[s.AssistantReply])
def assistant_history(product_id: str, shop: dict = Depends(current_shop), conn: Connection = Depends(get_conn, scope="function")) -> list[s.AssistantReply]:
    try:
        cat.owns_product(conn, product_id, shop)
        return assistant.history(conn, product_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail="Unknown product") from e


@app.post("/api/products/{product_id}/assistant", response_model=s.AssistantReply)
def assistant_ask(product_id: str, body: s.AssistantIn, shop: dict = Depends(writable_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.AssistantReply:
    """Ask about this product's recommendation. The assistant explains and points to sources; it has no path to Accept or Override."""
    try:
        cat.owns_product(conn, product_id, shop)
        return assistant.ask(conn, cat.llm_client(), product_id, body.question)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e) if "recommendation" in str(e) else "Unknown product") from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.post("/api/recommendations/{rec_id}/answer", response_model=s.AnswerOut)
def answer(rec_id: str, body: s.AnswerIn, shop: dict = Depends(writable_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.AnswerOut:
    try:
        cat.owns_recommendation(conn, rec_id, shop)
        return cat.answer(conn, cat.llm_client(), rec_id, body.question_id, body.option_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail="Unknown recommendation") from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.post("/api/recommendations/{rec_id}/decision", response_model=s.Decision)
def decide(rec_id: str, body: s.DecisionIn, shop: dict = Depends(writable_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.Decision:
    try:
        cat.owns_recommendation(conn, rec_id, shop)
        return cat.decide_product(conn, rec_id, body)
    except LookupError as e:
        raise HTTPException(status_code=404, detail="Unknown recommendation") from e
    except PermissionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.post("/api/products/bulk-accept", response_model=s.BulkAcceptOut)
def bulk_accept(body: s.BulkAcceptIn, shop: dict = Depends(writable_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.BulkAcceptOut:
    try:
        return cat.bulk_accept(conn, body, shop)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.post("/api/quote", response_model=s.Quote)
def quote(body: s.QuoteIn, shop: dict = Depends(quote_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.Quote:
    """The duty for a cart and a destination, from the register: no model call. With the merchant's API key the items may be named by SKU."""
    try:
        _keyless_shop(body.shop_id, shop)
        return checkout.quote(conn, body, shop)
    except (ValueError, LookupError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.post("/api/orders", response_model=s.OrderCreated)
def create_order(body: s.OrderCreateIn, shop: dict = Depends(writable_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.OrderCreated:
    """Create the PayPal order with the duty as tax_total and per-item tax. Returns the PayPal approval link for the buyer."""
    try:
        _keyless_shop(body.quote.shop_id, shop)
        return checkout.create_order(conn, body, shop=shop)
    except (ValueError, LookupError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/quotes/verify", response_model=s.QuoteVerifyOut)
def verify_quote(body: s.QuoteVerifyIn, shop: dict = Depends(require_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.QuoteVerifyOut:
    """Before capturing, the merchant's server sends the PayPal order the buyer approved and the quote's token. Valid means the order carries exactly the quoted
    duty, totals, currency and items. Nothing here touches PayPal or any PayPal credential."""
    try:
        payload = quote_token.read(body.quote_token)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if payload["shop"] != shop["id"]:
        raise HTTPException(status_code=422, detail="That quote was not issued to this merchant")
    reasons = quote_token.check_order(payload, body.paypal_order)
    if not reasons:  # a verified order with duties included earns the destination's passport stamp (the capture itself happens on the merchant's server)
        passport_svc.record_verified(conn, shop, payload, str(body.paypal_order.get("id") or "") or None)
    return s.QuoteVerifyOut(valid=not reasons, reasons=reasons)


@app.get("/api/shop", response_model=s.Storefront)
def shop(shop: dict = Depends(current_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.Storefront:
    return storefront.storefront(conn, shop)


@app.get("/api/orders/{order_id}", response_model=s.OrderReceipt)
def order_receipt(order_id: str, shop: dict = Depends(current_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.OrderReceipt:
    try:
        return storefront.receipt(conn, order_id, shop)
    except LookupError as e:
        raise HTTPException(status_code=404, detail="Unknown order") from e


@app.post("/api/orders/{order_id}/capture", response_model=s.OrderCaptured)
def capture_order(order_id: str, shop: dict = Depends(writable_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.OrderCaptured:
    try:
        return checkout.capture_order(conn, order_id, shop=shop)
    except LookupError as e:
        raise HTTPException(status_code=404, detail="Unknown order") from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/api/timemachine/options", response_model=s.TimeMachineOptions)
def tm_options() -> s.TimeMachineOptions:
    return timemachine.options()


@app.get("/api/timemachine/series", response_model=s.TimeMachineSeries)
def tm_series(product: str, origin: str, destination: s.Destination, conn: Connection = Depends(get_conn, scope="function")) -> s.TimeMachineSeries:
    res = timemachine.series(conn, product, origin, destination)
    if res is None:
        raise HTTPException(status_code=404, detail="No verified series for this product, origin and destination yet")
    return res


def _render_png(path: str) -> Response:
    """Ask the renderer to screenshot one of our /share pages (1200x630). Cached at the edge for an hour."""
    base = os.environ.get("RENDERER_URL", "http://127.0.0.1:3300")
    try:
        r = httpx.get(f"{base}/render", params={"path": path}, timeout=30)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail="Share image renderer is not available") from e
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Renderer said: {r.text[:120]}")
    return Response(content=r.content, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/timemachine/share.png")
def tm_share(product: str, origin: str, destination: s.Destination, date: str | None = None) -> Response:
    q = {"product": product, "origin": origin, "destination": destination, **({"date": date} if date else {})}
    return _render_png(f"/share/time-machine?{urlencode(q)}")


@app.get("/api/radar", response_model=list[s.RadarAlert])
def radar(shop: dict = Depends(current_shop), conn: Connection = Depends(get_conn, scope="function")) -> list[s.RadarAlert]:
    return radar_svc.alerts(conn, shop)


@app.post("/api/radar/{alert_id}/choice", response_model=s.RadarAlert)
def radar_choice(alert_id: str, body: s.RadarChoiceIn, shop: dict = Depends(writable_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.RadarAlert:
    try:
        return radar_svc.choose(conn, alert_id, body.choice, shop=shop)
    except LookupError as e:
        raise HTTPException(status_code=404, detail="Unknown alert") from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.get("/api/passport", response_model=s.Passport)
def passport(shop: dict = Depends(current_shop), conn: Connection = Depends(get_conn, scope="function")) -> s.Passport:
    return passport_svc.passport(conn, shop)


@app.get("/api/passport/shared/{shop_id}", response_model=s.Passport)
def passport_shared(shop_id: str, conn: Connection = Depends(get_conn, scope="function")) -> s.Passport:
    """The passport a seller chose to share: public by its link, and only the badge facts (stamps, level), never products, prices or keys."""
    from .services import merchants

    shop = merchants.shop_by_id(conn, shop_id)
    if shop is None:
        raise HTTPException(status_code=404, detail="Unknown passport")
    return passport_svc.passport(conn, shop)


@app.get("/api/passport/badge.png")
def passport_badge(shop: str | None = None) -> Response:
    """The shareable badge image: for the seller whose id is in the link (the demo seller's when none is given)."""
    if shop is not None and not re.fullmatch(r"[A-Za-z0-9_-]{3,64}", shop):
        raise HTTPException(status_code=422, detail="That passport link is not valid")
    return _render_png("/share/passport" + (f"?{urlencode({'shop': shop})}" if shop else ""))


@app.get("/api/coverage", response_model=s.Coverage)
def coverage(conn: Connection = Depends(get_conn, scope="function")) -> s.Coverage:
    """What Landfall covers and where each source comes from (public; no seller data)."""
    return coverage_svc.coverage(conn)


@app.get("/api/ops/sync", response_model=s.SyncStatus)
def ops_sync(conn: Connection = Depends(get_conn, scope="function")) -> s.SyncStatus:
    return ops_svc.sync_status(conn)


@app.get("/api/ops/rules", response_model=list[s.RuleProposal])
def ops_rules(conn: Connection = Depends(get_conn, scope="function")) -> list[s.RuleProposal]:
    return ops_svc.rules(conn)


def _rule_action(conn: Connection, rule_id: str, action: str, edits: dict | None = None) -> s.RuleProposal:
    try:
        return ops_svc.act(conn, rule_id, action, edits)
    except LookupError as e:
        raise HTTPException(status_code=404, detail="Unknown rule") from e
    except PermissionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@app.post("/api/ops/rules/{rule_id}/approve", response_model=s.RuleProposal)
def ops_approve(rule_id: str, conn: Connection = Depends(get_conn, scope="function"), _guard: None = Depends(ops_writer)) -> s.RuleProposal:
    return _rule_action(conn, rule_id, "approve")


@app.post("/api/ops/rules/{rule_id}/edit", response_model=s.RuleProposal)
def ops_edit(rule_id: str, body: s.RuleEditIn, conn: Connection = Depends(get_conn, scope="function"), _guard: None = Depends(ops_writer)) -> s.RuleProposal:
    return _rule_action(conn, rule_id, "edit", body.model_dump(exclude_none=True))


@app.post("/api/ops/rules/{rule_id}/reject", response_model=s.RuleProposal)
def ops_reject(rule_id: str, conn: Connection = Depends(get_conn, scope="function"), _guard: None = Depends(ops_writer)) -> s.RuleProposal:
    return _rule_action(conn, rule_id, "reject")


@app.get("/api/how-it-works", response_model=s.HowItWorks)
def how_it_works(conn: Connection = Depends(get_conn, scope="function")) -> s.HowItWorks:
    return content.how_it_works(conn)
