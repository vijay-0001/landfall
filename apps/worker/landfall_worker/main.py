"""Worker: APScheduler. Nightly source sync at 02:00 UTC (and one pass at start-up when the last good run is older than a day), then each connected shop's product feed at 03:00 UTC."""
from __future__ import annotations

import json
import time

from apscheduler.schedulers.blocking import BlockingScheduler
from landfall_register.db import make_engine, migrate
from sqlalchemy import text

from .sync import run_all


def stale(engine) -> bool:
    with engine.connect() as c:
        age = c.execute(text("SELECT extract(epoch FROM now() - max(finished_at)) FROM source_run WHERE ok")).scalar_one()
    return age is None or age > 24 * 3600


def sync_feeds(engine) -> list[dict]:
    """Re-read every connected shop's product feed (new SKUs recommended, changed listings back to review, removed SKUs inactive). Shared code with POST /api/products/sync."""
    import os

    from landfall_api.services.merchants import sync_all
    from landfall_classifier.model import HaikuClient

    key = os.environ.get("ANTHROPIC_API_KEY")
    out = sync_all(engine, HaikuClient(key) if key else None)
    print(json.dumps(out), flush=True)
    return out


def main() -> None:
    for _ in range(30):  # the API creates the schema; wait for it
        try:
            migrate()
            break
        except Exception:
            time.sleep(2)
    engine = make_engine()
    if stale(engine):
        run_all(engine)
    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(lambda: run_all(engine), "cron", hour=2, minute=0, id="nightly-sync", max_instances=1, coalesce=True)
    sched.add_job(lambda: sync_feeds(engine), "cron", hour=3, minute=0, id="feed-sync", max_instances=1, coalesce=True)
    print("worker: nightly source sync scheduled for 02:00 UTC, shop feed sync for 03:00 UTC", flush=True)
    sched.start()


if __name__ == "__main__":
    main()
