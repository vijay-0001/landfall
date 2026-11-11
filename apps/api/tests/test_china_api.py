"""China origin priced from the seeded register (Postgres): legacy Section 301 list, the 12.5% action, Section 122, exclusion review."""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from landfall_api import main
from landfall_api.services import catalogue as cat
from landfall_api.services.pricing import price_cart
from landfall_register import repo
from landfall_register.db import make_engine
from sqlalchemy import text


@pytest.fixture(scope="module")
def conn():
    with make_engine().begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    main.cat.llm_client = lambda: None
    with TestClient(main.app), make_engine().connect() as c:
        yield c


def duty(conn, code, price, on, origin="CN"):
    res = price_cart(conn, "US", cat._cart(code, origin, price), on, repo.latest_version(conn), window=0)  # noqa: SLF001
    return res, (res.tax_total if res.supported else None)


def test_wallet_from_china_stacks_base_list3_and_the_new_12_5_percent(conn):
    res, d = duty(conn, "4202.31.60.00", "26.00", date(2026, 11, 8))
    assert str(d) == "11.83"  # 8% + 25% (List 3, heading 9903.88.03) + 12.5% (9903.05.31) on 26.00
    labels = [t.label for t in res.trail]
    assert labels.count("Additional duty (origin-specific)") == 2 and all(t.source_ref for t in res.trail)


def test_section_122_period_and_the_day_the_new_rate_starts(conn):
    assert str(duty(conn, "4202.31.60.00", "26.00", date(2026, 7, 23))[1]) == "11.18"  # 8 + 25 + 10 (Section 122) = 43%
    assert str(duty(conn, "4202.31.60.00", "26.00", date(2026, 7, 24))[1]) == "11.83"  # Section 122 ends, 12.5% starts: 45.5%


def test_mug_from_china_is_not_on_a_legacy_list_so_pays_base_plus_12_5(conn):
    assert str(duty(conn, "6912.00.44.00", "38.00", date(2026, 11, 8))[1]) == "8.55"  # 10% + 12.5% = 22.5% of 38.00


def test_a_line_with_an_exclusion_in_force_is_not_priced_until_it_ends(conn):
    res, d = duty(conn, "4202.92.31.00", "30.00", date(2026, 11, 3))
    assert not res.supported and res.unsupported_reason == "exclusion_review" and d is None
    assert duty(conn, "4202.92.31.00", "30.00", date(2026, 11, 20))[0].supported  # the exclusion ended on 9 Nov 2026


def test_china_before_the_register_starts_is_not_priced(conn):
    res, _ = duty(conn, "4202.31.60.00", "26.00", date(2026, 1, 15))
    assert not res.supported and res.unsupported_reason == "origin_not_covered"


def test_exclusion_review_rows_never_become_radar_alerts_or_time_machine_steps(conn):
    from landfall_api.services import radar
    from landfall_api.services import timemachine as tm

    assert "exclusion_review" in radar.SKIP_MEASURES and "exclusion_review" in tm.SKIP_MEASURES
