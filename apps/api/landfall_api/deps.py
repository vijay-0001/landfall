from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException
from sqlalchemy import Connection

from . import demo
from .config import env
from .db import engine


def get_conn() -> Iterator[Connection]:
    """One transaction per request: commits on success, rolls back on error."""
    with engine().begin() as conn:
        yield conn


def _from_header(authorization: str | None, conn: Connection) -> dict | None:
    from .services import merchants

    if authorization is None:
        return None
    scheme, _, key = authorization.partition(" ")
    shop = merchants.shop_for_key(conn, key.strip()) if scheme.lower() == "bearer" and key.strip() else None
    if shop is None:
        raise HTTPException(status_code=401, detail="That API key is not valid", headers={"WWW-Authenticate": "Bearer"})
    return shop


def current_shop(authorization: str | None = Header(default=None), conn: Connection = Depends(get_conn, scope="function")) -> dict:
    """The merchant behind the request. With a key: that merchant. Without one: the demo merchant (Kiln & Co.), as the console always showed."""
    return _from_header(authorization, conn) or dict(demo.SHOP)


def quote_shop(authorization: str | None = Header(default=None), x_landfall_key: str | None = Header(default=None),
               conn: Connection = Depends(get_conn, scope="function")) -> dict:
    """For the quote only: the secret key (Authorization) or the publishable key (X-Landfall-Key, what the checkout widget sends from a web page). With neither: the demo shop."""
    from .services import merchants

    if authorization is None and x_landfall_key is not None:
        shop = merchants.shop_for_publishable_key(conn, x_landfall_key.strip())
        if shop is None:
            raise HTTPException(status_code=401, detail="That publishable key is not valid")
        return shop
    return current_shop(authorization, conn)


def require_shop(authorization: str | None = Header(default=None), conn: Connection = Depends(get_conn, scope="function")) -> dict:
    shop = _from_header(authorization, conn)
    if shop is None:
        raise HTTPException(status_code=401, detail="This call needs your API key: Authorization: Bearer <key>", headers={"WWW-Authenticate": "Bearer"})
    return shop


READONLY_MESSAGE = ("The sample shop is read-only on this site: you can look at every recommendation and price, "
                    "but changing it, asking the assistant or running the AI needs your own account. See INSTALL.md to run Landfall yourself.")


def public_readonly() -> bool:
    """True on a public deployment (LANDFALL_DEMO_READONLY=1): nobody without an API key may spend model tokens or change anything."""
    return env("LANDFALL_DEMO_READONLY") == "1"


def writable_shop(authorization: str | None = Header(default=None), conn: Connection = Depends(get_conn, scope="function")) -> dict:
    """Like current_shop, for calls that change data or can spend model tokens. A caller with a valid key is its own merchant. Without a key the demo
    merchant is used only where the deployment allows it; on a public site (LANDFALL_DEMO_READONLY=1) the call is refused."""
    shop = _from_header(authorization, conn)
    if shop is not None:
        return shop
    if public_readonly():
        raise HTTPException(status_code=403, detail=READONLY_MESSAGE)
    return dict(demo.SHOP)


def ops_writer() -> None:
    """The ops console approves rule proposals that change the rate register. It has no login, so on a public site its write calls are refused."""
    if public_readonly():
        raise HTTPException(status_code=403, detail="Approving rule proposals is switched off on this public site.")
