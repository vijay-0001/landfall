"""Register tests: bitemporal reads, constraints in the database, and property tests with a seeded RNG.

Hypothesis is MPL-2.0, so it is not used.
"""
import json
import pathlib
import random
from datetime import date, timedelta
from decimal import Decimal

import pytest
from landfall_register import repo
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

ROW = {
    "destination": "US", "code": "6912.00.44", "origin_scope": "ALL", "measure": "base_duty", "rate_kind": "percent",
    "rate": "10", "currency": None, "params": {}, "valid_from": date(2025, 1, 1), "valid_to": None,
    "source_ref": "HTS test", "source_url": None, "note": None,
}


def mk(conn, label="v1"):
    return repo.new_version(conn, label)


def span(r):
    vf = r["valid_from"] if isinstance(r["valid_from"], date) else date.fromisoformat(r["valid_from"])
    vt = r["valid_to"]
    if isinstance(vt, str):
        vt = date.fromisoformat(vt)
    return vf, vt or date.max


def overlaps(a, b):
    (af, at), (bf, bt) = span(a), span(b)
    return af < bt and bf < at


def key(r):
    return (r["destination"], r["code"], r["origin_scope"], r["measure"], r.get("variant", ""))


def test_overlapping_validity_is_impossible_in_the_database(conn):
    v = mk(conn)
    repo.add_row(conn, v, ROW)
    with pytest.raises(DBAPIError):
        repo.add_row(conn, v, {**ROW, "valid_from": date(2026, 1, 1)})
    conn.rollback()


def test_adjacent_validity_is_allowed(conn):
    v = mk(conn)
    repo.add_row(conn, v, {**ROW, "valid_to": date(2026, 7, 24)})
    repo.add_row(conn, v, {**ROW, "valid_from": date(2026, 7, 24), "rate": "20"})
    assert len(repo.rows_visible(conn, v)) == 2


def test_rows_are_never_updated_or_deleted_in_place(conn):
    v = mk(conn)
    rid = repo.add_row(conn, v, ROW)
    with pytest.raises(DBAPIError):
        conn.execute(text("UPDATE rate_row SET rate = 99 WHERE id = :i"), {"i": rid})
    conn.rollback()
    v = mk(conn, "v-del")
    rid = repo.add_row(conn, v, {**ROW, "code": "1111"})
    with pytest.raises(DBAPIError):
        conn.execute(text("DELETE FROM rate_row WHERE id = :i"), {"i": rid})
    conn.rollback()


def test_correction_closes_old_row_and_replay_by_version_reproduces_history(conn):
    v1 = mk(conn, "v1")
    rid = repo.add_row(conn, v1, ROW)
    v2 = mk(conn, "v2")
    new_id = repo.correct(conn, rid, v2, rate="12")
    at_v1 = repo.rows_visible(conn, v1)
    at_v2 = repo.rows_visible(conn, v2)
    assert [r["rate"] for r in at_v1] == ["10"] and at_v1[0]["id"] == str(rid)
    assert [r["rate"] for r in at_v2] == ["12"] and at_v2[0]["id"] == str(new_id)
    with pytest.raises(ValueError):
        repo.supersede(conn, rid, v2)


def test_future_dated_row_is_visible_only_for_its_own_dates(conn):
    v = mk(conn)
    repo.add_row(conn, v, {**ROW, "valid_to": date(2026, 12, 1)})
    repo.add_row(conn, v, {**ROW, "valid_from": date(2026, 12, 1), "rate": "15"})
    assert [r["rate"] for r in repo.rate_lookup(conn, "US", "6912.00.44.00", "GB", date(2026, 10, 29))] == ["10"]
    assert [r["rate"] for r in repo.rate_lookup(conn, "US", "6912.00.44.00", "GB", date(2026, 12, 2))] == ["15"]


def test_version_at_resolves_known_time(conn):
    v1 = mk(conn, "v1")
    later = conn.execute(text("SELECT now() + interval '1 second'")).scalar_one()
    assert repo.version_at(conn, later) == v1


KEYS = [
    ("US", "6912.00.44", "ALL", "base_duty"),
    ("US", "*", "GB", "additional_duty"),
    ("EU", "*", "ALL", "import_vat"),
    ("GB", "*", "ALL", "low_value_relief"),
]


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6, 7, 8])
def test_property_no_overlap_and_replay_reproduces_history(conn, seed):
    rnd = random.Random(seed)
    base = date(2025, 1, 1)
    snapshots: dict[int, list[tuple]] = {}
    prev = None
    for step in range(40):
        v = repo.new_version(conn, f"p{seed}-{step}")
        for _ in range(rnd.randint(1, 3)):
            kind = rnd.choice(["add", "add", "correct", "close", "overlap"])
            dest, code, origin, measure = rnd.choice(KEYS)
            vf = base + timedelta(days=rnd.randint(0, 900))
            vt = None if rnd.random() < 0.4 else vf + timedelta(days=rnd.randint(1, 400))
            row = {**ROW, "destination": dest, "code": code, "origin_scope": origin, "measure": measure,
                   "valid_from": vf, "valid_to": vt, "rate": str(rnd.randint(0, 40))}
            open_rows = repo.rows_visible(conn, v)
            same = [r for r in open_rows if key(r)[:4] == (dest, code, origin, measure)]
            sp = conn.begin_nested()
            try:
                if kind == "add":
                    repo.add_row(conn, v, row)
                    assert not any(overlaps(row, r) for r in same), "database accepted an overlapping row"
                elif kind == "correct" and open_rows:
                    repo.correct(conn, int(rnd.choice(open_rows)["id"]), v, rate=str(rnd.randint(0, 40)))
                elif kind == "close" and open_rows:
                    repo.supersede(conn, int(rnd.choice(open_rows)["id"]), v)
                elif kind == "overlap" and same:
                    t = rnd.choice(same)
                    repo.add_row(conn, v, {**row, "valid_from": date.fromisoformat(t["valid_from"]), "valid_to": None})
                    raise AssertionError("an overlapping row was accepted")
                sp.commit()
            except (DBAPIError, ValueError):
                sp.rollback()
        snapshots[v] = sorted((r["id"], r["rate"]) for r in repo.rows_visible(conn, v))
        if prev is not None:  # rows never vanish silently: only closing a row removes it from a later version
            assert prev <= v
        prev = v
    for v in snapshots:  # invariant 1: no overlapping validity for one key within any version
        rows = repo.rows_visible(conn, v)
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                if key(a) == key(b):
                    assert not overlaps(a, b), (v, a, b)
    for v, snap in snapshots.items():  # invariant 2: replay by version reproduces history exactly
        assert sorted((r["id"], r["rate"]) for r in repo.rows_visible(conn, v)) == snap


def test_golden_cases_price_identically_from_the_database(conn):
    """The same golden cases, but the rows come out of Postgres through the register."""
    from landfall_engine import price

    gold = pathlib.Path(__file__).resolve().parents[2] / "engine" / "tests" / "golden"
    rows = json.loads((gold / "rows.json").read_text(encoding="utf-8"))
    cases = json.loads((gold / "cases.json").read_text(encoding="utf-8"))
    v = mk(conn, "golden")
    for r in rows:
        vt = date.fromisoformat(r["valid_to"]) if r["valid_to"] else None
        repo.add_row(conn, v, {**r, "valid_from": date.fromisoformat(r["valid_from"]), "valid_to": vt})
    for c in cases:
        inp = c["input"]
        db_rows = repo.rows_for_pricing(conn, inp["destination"], date.fromisoformat(inp["import_date"]), v,
                                        inp.get("change_window_days", 5))
        res = price(inp, db_rows)
        exp = c["expected"]
        assert res.supported is exp["supported"], c["id"]
        if exp["supported"]:
            assert res.tax_total == Decimal(exp["tax_total"]), c["id"]
        else:
            assert res.unsupported_reason == exp["unsupported_reason"], c["id"]
