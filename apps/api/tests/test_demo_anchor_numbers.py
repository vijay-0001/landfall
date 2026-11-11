"""The documented demo numbers (docs/demo.md) are reproducible from the demo seller's recorded codes, whatever Haiku picks on a fresh seed.
Each seeded code must exist in the register, and priced on a fixed date it must give the number the demo script quotes."""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from landfall_api import demo, main
from landfall_api.services.pricing import price_cart
from landfall_register import repo
from landfall_register.db import make_engine
from sqlalchemy import text

ON = date(2026, 11, 15)
# Chapters 44 (wood) and 95 (toys) are not in the committed core register: they are read from the live tariff on first use (tools/fetch_hts_all.py at deploy),
# which tests never reach. Their anchors are covered by the demo journey on a seeded database, not here.
ON_DEMAND_ONLY = {"p_spoons", "p_train"}
ANCHORS = {"p_mug": "7.60", "p_wallet": "11.83", "p_tee": "7.42", "p_spoons": "4.10", "p_train": "5.50"}  # docs/demo.md, on the listed US price


@pytest.fixture(scope="module")
def conn():
    eng = make_engine()
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    with TestClient(main.app):
        with eng.connect() as c:
            yield c


def test_every_seeded_demo_code_is_a_real_line_in_the_register(conn):
    for pid, code in demo.SEED_CODES.items():
        if pid in ON_DEMAND_ONLY:
            continue
        n = conn.execute(text("SELECT count(*) FROM rate_row WHERE destination = 'US' AND code = :c AND measure = 'base_duty'"), {"c": code}).scalar_one()
        assert n >= 1, f"{pid}: {code} is not in the register"


def test_the_seeded_codes_cover_every_accepted_demo_product():
    accepted = {p["id"] for p in demo.PRODUCTS if p.get("accept")}
    assert accepted == set(demo.SEED_CODES)


@pytest.mark.parametrize("pid,expected", sorted(ANCHORS.items()))
def test_the_demo_script_numbers_come_from_the_seeded_codes(conn, pid, expected):
    if pid in ON_DEMAND_ONLY:
        pytest.skip("this heading is read from the live tariff on first use")
    p = next(x for x in demo.PRODUCTS if x["id"] == pid)
    item = {"sku": pid, "code": demo.SEED_CODES[pid], "origin": p["origin"], "unit_price": p["prices"]["USD"], "quantity": 1}
    res = price_cart(conn, "US", [item], ON, repo.latest_version(conn), window=0)
    assert res.supported
    assert res.tax_total == Decimal(expected)
