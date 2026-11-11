"""Fetch every distinct source link in the register and report which ones do not resolve. Run by hand; tests never use the network.

    LANDFALL_DATABASE_URL=... python tools/check_source_links.py

Some official sites sit behind bot walls that answer curl with 403 or a redirect page while a person's browser is fine
(UK Trade Tariff, Federal Register). Those are listed as "bot wall" and should be opened once in a browser.
"""
from __future__ import annotations

import concurrent.futures as cf
import urllib.error
import urllib.request

from landfall_register.db import make_engine
from sqlalchemy import text

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
BOT_WALL = ("trade-tariff.service.gov.uk", "federalregister.gov")


def check(url: str) -> tuple[str, str]:
    req = urllib.request.Request(url.split("#")[0], headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            final = r.geturl()
            if "unblock." in final or "captcha" in final:
                return "bot wall", final
            return ("ok" if r.status == 200 else f"http {r.status}"), final
    except urllib.error.HTTPError as e:
        host = url.split("/")[2]
        return ("bot wall" if e.code in (403, 429) and any(h in host for h in BOT_WALL) else f"HTTP {e.code}"), url
    except Exception as e:  # noqa: BLE001
        return f"error {str(e)[:50]}", url


def main() -> None:
    with make_engine().connect() as c:
        urls = sorted({r[0] for r in c.execute(text("SELECT DISTINCT source_url FROM rate_row WHERE source_url IS NOT NULL"))})
    print(len(urls), "distinct links")
    with cf.ThreadPoolExecutor(6) as ex:
        results = list(ex.map(check, urls))
    bad = 0
    for u, (status, final) in zip(urls, results, strict=True):
        flag = "" if status == "ok" else "  <-- CHECK"
        bad += status not in ("ok", "bot wall")
        print(f"{status:10} {u}{flag}")
    print(f"{bad} link(s) need fixing; 'bot wall' ones are fine in a browser but should be opened once to confirm")


if __name__ == "__main__":
    main()
