"""The worker schedules the shop feed sync (03:00 UTC, after the 02:00 source sync) and the job hands every connected shop to the shared sync code. No network, no model call."""
from landfall_worker import main as worker


class FakeSched:
    jobs: list[dict] = []

    def __init__(self, timezone=None):
        self.timezone = timezone

    def add_job(self, fn, trigger, **kw):
        FakeSched.jobs.append({"fn": fn, "trigger": trigger, **kw})

    def start(self):
        pass


def test_the_worker_schedules_the_source_sync_at_0200_and_the_feed_sync_at_0300_utc(monkeypatch):
    FakeSched.jobs = []
    monkeypatch.setattr(worker, "BlockingScheduler", FakeSched)
    monkeypatch.setattr(worker, "migrate", lambda: None)
    monkeypatch.setattr(worker, "make_engine", lambda: object())
    monkeypatch.setattr(worker, "stale", lambda e: False)
    worker.main()
    by = {j["id"]: j for j in FakeSched.jobs}
    assert (by["nightly-sync"]["hour"], by["nightly-sync"]["minute"]) == (2, 0)
    assert (by["feed-sync"]["hour"], by["feed-sync"]["minute"]) == (3, 0)
    assert by["feed-sync"]["max_instances"] == 1


def test_the_feed_job_uses_the_shared_sync_and_runs_without_a_model_key(monkeypatch):
    import landfall_api.services.merchants as merchants

    seen = {}

    def fake_sync_all(engine, llm=None, fetch=None):
        seen["engine"], seen["llm"] = engine, llm
        return [{"shop": "s1", "ok": True, "added": 1, "changed": 0, "removed": 0}]

    monkeypatch.setattr(merchants, "sync_all", fake_sync_all)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = worker.sync_feeds("ENGINE")
    assert out[0]["ok"] and seen == {"engine": "ENGINE", "llm": None}  # no key: products stay 'not yet reviewed'; nothing breaks
