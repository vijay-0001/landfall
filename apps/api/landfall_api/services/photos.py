"""Product photos for the recommender. A photo is fetched, sent to the model once and dropped: Landfall stores the address and the TEXT the model read (labels, a country
named as the place of manufacture, visible materials), never the image. The seller sees what was read next to the recommendation and can correct the decision.

The fetch follows the same rules as the feed fetch: public https only (private and local hosts refused unless LANDFALL_ALLOW_PRIVATE_FEEDS is set for local development),
no credentials, no redirects, a size cap, and the type is checked from the file's own bytes. A photo that cannot be read never blocks a recommendation.
"""
from __future__ import annotations

import json
import socket
from urllib.parse import urlsplit

import httpx
from landfall_classifier.vision import MAX_BYTES, MAX_IMAGES, Photo, join_reads, read_photo, sniff
from sqlalchemy import Connection, text

from .. import schemas as s


def fetch_image(url: str) -> Photo:
    """The photo's bytes, held in memory only. Raises ValueError with a plain reason."""
    # the same address checks as the feed; imported here because merchants imports the catalogue
    from . import merchants

    try:
        url = merchants.validate_feed_url(url)
    except ValueError as e:
        raise ValueError(str(e).replace("feed address", "photo address").replace("The feed", "The photo")) from None
    u = urlsplit(url)
    if not merchants._allow_private():  # noqa: SLF001
        try:
            infos = socket.getaddrinfo(u.hostname, u.port or 443, proto=socket.IPPROTO_TCP)
        except OSError:
            raise ValueError("That photo address could not be found") from None
        if any(merchants._private(i[4][0]) for i in infos):  # noqa: SLF001
            raise ValueError("The photo must be on a public website, not a private address")
    try:
        with httpx.stream("GET", url, timeout=15, follow_redirects=False, headers={"User-Agent": "Landfall-importer/1.0", "Accept": "image/*"}) as r:
            if r.status_code != 200:
                raise ValueError(f"The photo could not be fetched: the site answered {r.status_code}")
            if int(r.headers.get("content-length") or 0) > MAX_BYTES:
                raise ValueError("The photo is larger than 5 MB")
            data = bytearray()
            for chunk in r.iter_bytes():
                data += chunk
                if len(data) > MAX_BYTES:
                    raise ValueError("The photo is larger than 5 MB")
    except httpx.HTTPError:
        raise ValueError("The photo could not be fetched") from None
    kind = sniff(bytes(data))
    if kind is None:
        raise ValueError("That address is not a JPEG, PNG, WebP or GIF photo")
    return Photo(kind, bytes(data))


def read_for_product(conn: Connection, prod: dict, llm) -> dict:
    """Read the product's photos (at most MAX_IMAGES, each once: a reading is kept by address) and return
    {"label_text", "materials", "reads": [{url, label_text, made_in, materials, notes, error}]}. Nothing here raises."""
    urls = [u for u in (prod.get("images") or []) if isinstance(u, str)][:MAX_IMAGES]
    out = {"label_text": None, "materials": None, "reads": []}
    if not urls:
        return out
    cache = dict(prod.get("image_reads") or {})
    can_read = llm is not None and hasattr(llm, "complete_images")
    changed = False
    reads = []
    for url in urls:
        got = cache.get(url)
        if got is None and can_read:
            try:
                got = read_photo(llm, fetch_image(url), prod["title"]).model_dump()
            except ValueError as e:
                got = {"error": str(e)}
            except Exception:  # the model or the network failed: not cached, so the next recommendation tries again
                got = {"error": "The photo could not be read this time"}
                reads.append({"url": url, **got})
                continue
            if "error" not in got:  # only a good reading is kept: a failure is tried again next time
                cache[url] = got
                changed = True
        if got is not None:
            reads.append({"url": url, **got})
    if changed:
        conn.execute(text("UPDATE product SET image_reads = CAST(:r AS jsonb) WHERE id = :i"), {"r": json.dumps(cache), "i": prod["id"]})
    ok = [s_ for s_ in (_as_read(r) for r in reads if not r.get("error")) if s_ is not None]
    out["reads"] = reads
    out["label_text"] = join_reads(ok)
    out["materials"] = "; ".join(dict.fromkeys(r.materials for r in ok if r.materials))[:300] or None
    return out


def _as_read(r: dict):
    from landfall_classifier.vision import PhotoRead

    try:
        return PhotoRead(**{k: r.get(k) for k in ("label_text", "made_in", "materials", "notes")})
    except ValueError:
        return None


def view(reads: list[dict]) -> list[s.PhotoReadOut]:
    return [s.PhotoReadOut(url=r["url"], label_text=r.get("label_text"), made_in=r.get("made_in"), materials=r.get("materials"), notes=r.get("notes"), error=r.get("error"))
            for r in reads]
