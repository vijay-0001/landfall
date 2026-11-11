"""Merchants: sign-up and API keys (only a hash is stored), and the import of a store's product feed.

The feed is the public Shopify-style `/products.json`. A feed address comes from a merchant, so it is treated as untrusted: https only, no
credentials in the address, and never a private, loopback or link-local host. LANDFALL_ALLOW_PRIVATE_FEEDS=1 lifts that for local development.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import secrets
import socket
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError
from sqlalchemy import Connection, text

from .. import schemas as s
from ..config import env
from . import catalogue as cat

KEY_PREFIX = "lf_test_"
MAX_FEED_BYTES = 2_000_000
MAX_PRODUCTS = 250
MAX_VARIANTS = 500
DEFAULT_VARIANT = "default title"
_SHOP_COLS = "id, name, country, city, ioss_registered"


def new_key() -> str:
    return KEY_PREFIX + secrets.token_hex(24)


def publishable_key(key: str) -> str:
    """Derived from the secret key by a one-way hash: it can sit in a web page and cannot be turned back into the secret."""
    return "lf_pub_" + hashlib.sha256(("publishable:" + key).encode("utf-8")).hexdigest()[:32]


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()  # the key is 192 random bits, so a plain hash is enough


def create_merchant(conn: Connection, body: s.MerchantCreate) -> s.MerchantCreated:
    shop_id = cat.new_id("shop")
    key = new_key()
    conn.execute(text("INSERT INTO shop (id, name, country, city, ioss_registered, api_key_hash, api_key_prefix, publishable_key) VALUES (:i, :n, :c, :t, false, :h, :p, :pk)"),
                 {"i": shop_id, "n": body.name, "c": body.country, "t": body.city, "h": key_hash(key), "p": key[:12], "pk": publishable_key(key)})
    cat.audit(conn, f"seller:{shop_id}", "merchant_created", "shop", shop_id, {"name": body.name, "country": body.country})
    return s.MerchantCreated(shop_id=shop_id, name=body.name, country=body.country, city=body.city, api_key=key, api_key_prefix=key[:12], publishable_key=publishable_key(key))


def shop_for_publishable_key(conn: Connection, pk: str) -> dict | None:
    r = conn.execute(text(f"SELECT {_SHOP_COLS} FROM shop WHERE publishable_key = :k"), {"k": pk}).mappings().first()  # noqa: S608
    return dict(r) if r else None


def shop_for_key(conn: Connection, key: str) -> dict | None:
    r = conn.execute(text(f"SELECT {_SHOP_COLS} FROM shop WHERE api_key_hash = :h"), {"h": key_hash(key)}).mappings().first()  # noqa: S608
    return dict(r) if r else None


def shop_by_id(conn: Connection, shop_id: str) -> dict | None:
    r = conn.execute(text(f"SELECT {_SHOP_COLS} FROM shop WHERE id = :i"), {"i": shop_id}).mappings().first()  # noqa: S608
    return dict(r) if r else None


def merchant_me(conn: Connection, shop: dict) -> s.MerchantMe:
    r = conn.execute(text("SELECT api_key_prefix, publishable_key, feed_url, created_at, last_synced_at FROM shop WHERE id = :i"), {"i": shop["id"]}).mappings().one()
    n = conn.execute(text("SELECT count(*) FROM product WHERE shop_id = :i AND active"), {"i": shop["id"]}).scalar_one()
    return s.MerchantMe(shop_id=shop["id"], name=shop["name"], country=shop["country"], city=shop["city"], api_key_prefix=r["api_key_prefix"], publishable_key=r["publishable_key"],
                        feed_url=r["feed_url"], product_count=n, last_synced_at=r["last_synced_at"])


def ensure_shop_key(conn: Connection, shop_id: str, key: str) -> None:
    """The mock merchant (Kiln & Co.) is given a key from the environment, so its separate app can call the API. Nothing is written without a key."""
    conn.execute(text("UPDATE shop SET api_key_hash = :h, api_key_prefix = :p, publishable_key = :pk WHERE id = :i"), {"h": key_hash(key), "p": key[:12], "pk": publishable_key(key), "i": shop_id})


# ---------------------------------------------------------------- feed address
def _private(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    return a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast or a.is_unspecified


def _allow_private() -> bool:
    return env("LANDFALL_ALLOW_PRIVATE_FEEDS") == "1"


def validate_feed_url(url: str) -> str:
    """Checks that need no network: scheme, credentials, and a host that is not obviously private. Raises ValueError with a plain reason."""
    try:
        u = urlsplit(url.strip())
        host = u.hostname
        _ = u.port
    except ValueError as e:
        raise ValueError("That is not a web address") from e
    if u.scheme not in ("https", "http") or not host:
        raise ValueError("The feed address must start with https://")
    if u.username or u.password:
        raise ValueError("The feed address must not contain a user name or password")
    if _allow_private():
        return url.strip()
    if u.scheme != "https":
        raise ValueError("The feed address must start with https://")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("The feed must be a public website, not a local address")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None  # a name, not an address: the network step checks what it resolves to
    if ip is not None and _private(str(ip)):
        raise ValueError("The feed must be a public website, not a private address")
    return url.strip()


def fetch_feed(url: str) -> dict:
    """The network part: resolve the host, refuse private addresses, then fetch with no redirects and a size cap.
    (The host is resolved once here for the check and once by the HTTP client. A hostile DNS server could answer differently the second
    time; for a hosted service the next step would be to connect to the checked address. Noted in docs/merchant-journey.md.)"""
    u = urlsplit(url)
    if not _allow_private():
        try:
            infos = socket.getaddrinfo(u.hostname, u.port or 443, proto=socket.IPPROTO_TCP)
        except OSError as e:
            raise ValueError("That web address could not be found") from e
        if any(_private(i[4][0]) for i in infos):
            raise ValueError("The feed must be a public website, not a private address")
    try:
        with httpx.stream("GET", url, timeout=10, follow_redirects=False, headers={"User-Agent": "Landfall-importer/1.0", "Accept": "application/json"}) as r:
            if r.status_code != 200:
                raise ValueError(f"The store answered {r.status_code} when asked for its product feed")
            buf = b""
            for chunk in r.iter_bytes():
                buf += chunk
                if len(buf) > MAX_FEED_BYTES:
                    raise ValueError("The product feed is larger than 2 MB: import it in smaller parts")
    except httpx.HTTPError as e:
        raise ValueError("The store did not answer in time") from e
    try:
        data = json.loads(buf)
    except ValueError as e:
        raise ValueError("The feed is not valid JSON") from e
    if not isinstance(data, dict):
        raise ValueError("The feed must be a JSON object with a products list")
    return data


# ---------------------------------------------------------------- feed to products
class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("br", "p", "li", "div"):
            self.parts.append(" ")


def plain_text(html: str | None) -> str:
    p = _Text()
    p.feed(html or "")
    return " ".join(unescape(" ".join(p.parts)).split())


def _prices(variant: dict, fallback_currency: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for pp in variant.get("presentment_prices") or []:
        price = (pp or {}).get("price") or {}
        cur, amount = price.get("currency_code"), price.get("amount")
        if cur in ("USD", "GBP", "EUR", "AUD", "CAD") and amount:
            out[cur] = str(amount)
    if not out and variant.get("price") not in (None, ""):
        out[fallback_currency] = str(variant["price"])
    return out


def _clean_price(v: str) -> str:
    return f"{float(v):.2f}"


def import_feed(conn: Connection, shop: dict, feed_url: str, currency: str) -> s.ImportOut:
    feed_url = validate_feed_url(feed_url)
    data = fetch_feed(feed_url)
    parsed = _read_feed(data, currency)
    created: list[str] = []
    updated: list[str] = []
    for sku, body in parsed.items:
        row = conn.execute(text("SELECT id FROM product WHERE shop_id = :s AND sku = :k"), {"s": shop["id"], "k": sku}).first()
        if row:  # the same SKU again: refresh prices (and photos) only, so a recommendation and the seller's decision are never silently invalidated
            conn.execute(text("UPDATE product SET prices = CAST(:pr AS jsonb), photo_url = :ph, images = CAST(:im AS jsonb) WHERE id = :i"),
                         {"pr": json.dumps(body.prices), "ph": body.photo_url, "im": json.dumps(body.image_urls), "i": row[0]})
            updated.append(row[0])
        else:
            created.append(_insert_product(conn, shop, sku, body))
    conn.execute(text("UPDATE shop SET feed_url = :u, feed_currency = :c, last_synced_at = now() WHERE id = :i"), {"u": feed_url, "c": currency, "i": shop["id"]})
    cat.audit(conn, f"seller:{shop['id']}", "feed_imported", "shop", shop["id"], {"feed_url": feed_url, "created": len(created), "updated": len(updated), "skipped": len(parsed.skipped)})
    view = lambda ids: [cat.product_view(conn, cat.get_prod(conn, i)) for i in ids]  # noqa: E731
    return s.ImportOut(created=view(created), updated=view(updated), skipped=parsed.skipped)


class _Parsed:
    def __init__(self) -> None:
        self.items: list[tuple[str, s.ProductCreate]] = []
        self.skipped: list[s.ImportSkipped] = []


def _insert_product(conn: Connection, shop: dict, sku: str, body: s.ProductCreate) -> str:
    pid = cat.new_id("p")
    conn.execute(text("INSERT INTO product (id, shop_id, sku, title, description, photo_url, images, prices, category, inputs_hash) "
                      "VALUES (:i, :s, :k, :t, :d, :ph, CAST(:im AS jsonb), CAST(:pr AS jsonb), 'other', :h)"),
                 {"i": pid, "s": shop["id"], "k": sku, "t": body.title, "d": body.description, "ph": body.photo_url, "im": json.dumps(body.image_urls), "pr": json.dumps(body.prices),
                  "h": cat.inputs_hash(body.title, body.description, "|".join(body.image_urls) or None)})
    return pid


def _image_urls(p: dict) -> list[str]:
    """The product's photo addresses from a Shopify-style feed (images[].src), at most four, anything that is not a plain web address left out."""
    out: list[str] = []
    for im in (p.get("images") or [])[:8]:
        src = (im or {}).get("src") if isinstance(im, dict) else im
        if isinstance(src, str) and src.strip().lower().startswith(("https://", "http://")) and len(src.strip()) <= 500 and not any(c in src for c in " \t\r\n<>\"'"):
            if src.strip() not in out:
                out.append(src.strip())
    return out[:4]


def _read_feed(data: dict, currency: str) -> _Parsed:
    """The feed read into one ProductCreate per SKU, with the reasons for anything skipped. Pure: no database."""
    out = _Parsed()
    products = data.get("products")
    if not isinstance(products, list):
        raise ValueError("The feed has no products list: expected the store's /products.json")
    if len(products) > MAX_PRODUCTS:
        raise ValueError(f"The feed has more than {MAX_PRODUCTS} products: import it in smaller parts")
    seen = 0
    for p in products:
        if not isinstance(p, dict):
            continue
        variants = [v for v in (p.get("variants") or []) if isinstance(v, dict)]
        for v in variants:
            seen += 1
            if seen > MAX_VARIANTS:
                raise ValueError(f"The feed has more than {MAX_VARIANTS} variants: import it in smaller parts")
            title = " ".join(str(p.get("title") or "").split())
            sku = str(v.get("sku") or "").strip()
            if not sku:
                out.skipped.append(s.ImportSkipped(title=title or "Untitled", reason="No SKU on the variant: Landfall needs one to match your checkout to the product"))
                continue
            vt = " ".join(str(v.get("title") or "").split())
            if len(variants) > 1 and vt and vt.lower() != DEFAULT_VARIANT:
                title = f"{title}, {vt}"
            try:
                prices = {c: _clean_price(a) for c, a in _prices(v, currency).items()}
                urls = _image_urls(p)
                body = s.ProductCreate(title=title[:120], description=plain_text(p.get("body_html"))[:2000], prices=prices, photo_url=urls[0] if urls else None, image_urls=urls)
            except (ValidationError, ValueError, TypeError) as e:
                reason = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:2]) if isinstance(e, ValidationError) else "Unreadable price"
                out.skipped.append(s.ImportSkipped(title=title or sku, reason=reason))
                continue
            out.items.append((sku, body))
    return out


def sync_feed(conn: Connection, shop: dict, llm=None, fetch=None, actor: str | None = None) -> s.SyncOut:
    """Re-read the shop's saved feed and bring the catalogue in line with it.

    A new SKU is added and gets a recommendation (an identical listing reuses an existing one: no model call). A price change refreshes prices and keeps the decision.
    A changed title or description sets changed_at, so the seller's earlier decision no longer applies (the quote says why) until they decide again, and the product gets
    a fresh recommendation. A SKU missing from the feed becomes inactive (the quote refuses it, the storefront hides it); one that returns is active again.
    `fetch` is injected so tests never touch the network. A feed with no usable products changes nothing (an outage must not empty the catalogue).
    """
    row = conn.execute(text("SELECT feed_url, feed_currency FROM shop WHERE id = :i"), {"i": shop["id"]}).mappings().one()
    if not row["feed_url"]:
        raise ValueError("Connect a product feed first: import your products once, then Landfall keeps them in sync")
    url = validate_feed_url(row["feed_url"])
    parsed = _read_feed((fetch or fetch_feed)(url), row["feed_currency"] or "USD")
    if not parsed.items:
        raise ValueError("The feed has no usable products, so nothing was changed")
    added, changed, price_updated, restored = [], [], 0, 0
    in_feed: set[str] = set()
    for sku, body in parsed.items:
        in_feed.add(sku)
        cur = conn.execute(text("SELECT id, title, description, prices, active, images FROM product WHERE shop_id = :s AND sku = :k"), {"s": shop["id"], "k": sku}).mappings().first()
        if cur is None:
            added.append(_insert_product(conn, shop, sku, body))
            continue
        if not cur["active"]:
            restored += 1
        had = list(cur["images"] or [])
        # Evidence changed: a different wording, or different photos where there were photos before. Photos added to a product that had none are stored without
        # sending the seller back to review (their decision was made on the words); the next recommendation reads them.
        evidence_changed = cur["title"] != body.title or cur["description"] != body.description or (bool(had) and had != body.image_urls)
        if evidence_changed:
            conn.execute(text("UPDATE product SET title = :t, description = :d, prices = CAST(:pr AS jsonb), photo_url = :ph, images = CAST(:im AS jsonb), image_reads = '{}'::jsonb, "
                              "inputs_hash = :h, changed_at = now(), active = true WHERE id = :i"),
                         {"t": body.title, "d": body.description, "pr": json.dumps(body.prices), "ph": body.photo_url, "im": json.dumps(body.image_urls),
                          "h": cat.inputs_hash(body.title, body.description, "|".join(body.image_urls) or None), "i": cur["id"]})
            changed.append(cur["id"])
        elif cur["prices"] != body.prices or not cur["active"] or had != body.image_urls:
            conn.execute(text("UPDATE product SET prices = CAST(:pr AS jsonb), photo_url = :ph, images = CAST(:im AS jsonb), active = true WHERE id = :i"),
                         {"pr": json.dumps(body.prices), "ph": body.photo_url, "im": json.dumps(body.image_urls), "i": cur["id"]})
            price_updated += 1 if cur["prices"] != body.prices else 0
    gone = [r[0] for r in conn.execute(text("SELECT id FROM product WHERE shop_id = :s AND sku IS NOT NULL AND active AND NOT (sku = ANY(:skus))"),
                                       {"s": shop["id"], "skus": sorted(in_feed)})]
    for pid in gone:
        conn.execute(text("UPDATE product SET active = false WHERE id = :i"), {"i": pid})
    recommended = pending = 0
    for pid in added + changed:
        try:
            with conn.begin_nested():  # one product's failure must not undo the sync
                made = cat.recommend(conn, pid, llm) if llm is not None else None
        except Exception:  # the recommender is a helper: the product stays "not yet reviewed" and the seller can ask again
            made = None
        recommended, pending = (recommended + 1, pending) if made else (recommended, pending + 1)
    conn.execute(text("UPDATE shop SET last_synced_at = now() WHERE id = :i"), {"i": shop["id"]})
    stamp = conn.execute(text("SELECT last_synced_at FROM shop WHERE id = :i"), {"i": shop["id"]}).scalar_one()
    cat.audit(conn, actor or f"seller:{shop['id']}", "feed_synced", "shop", shop["id"],
              {"added": len(added), "price_updated": price_updated, "changed": len(changed), "removed": len(gone), "restored": restored, "recommended": recommended, "pending": pending})
    return s.SyncOut(added=len(added), price_updated=price_updated, changed=len(changed), removed=len(gone), restored=restored, skipped=parsed.skipped,
                     recommended=recommended, pending=pending, last_synced_at=stamp)


def sync_all(engine, llm=None, fetch=None) -> list[dict]:
    """The nightly job: every shop with a saved feed, each in its own transaction so one bad feed never blocks the others."""
    with engine.connect() as c:
        shops = [dict(r) for r in c.execute(text(f"SELECT {_SHOP_COLS} FROM shop WHERE feed_url IS NOT NULL")).mappings()]  # noqa: S608
    out = []
    for shop in shops:
        try:
            with engine.begin() as c:
                r = sync_feed(c, shop, llm, fetch, actor="system:feed-sync")
            out.append({"shop": shop["id"], "ok": True, "added": r.added, "changed": r.changed, "removed": r.removed})
        except Exception as e:  # recorded, not raised
            out.append({"shop": shop["id"], "ok": False, "detail": str(e)[:160]})
    return out


_NAME_OK = re.compile(r"^[^<>{}\[\]\\]+$")


def check_text(v: str) -> str:
    if not _NAME_OK.match(v):
        raise ValueError("Letters, numbers and ordinary punctuation only")
    return v
