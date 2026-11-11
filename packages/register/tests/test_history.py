"""The curated US history: seeded register prices the UK mug through every legal period, with citations."""
from datetime import date
from decimal import Decimal

from landfall_engine import price
from landfall_register import repo
from landfall_register.seed import seed_register

MUG = {"sku": "MUG", "code": "6912.00.44.00", "origin": "GB", "unit_price": "38.00", "quantity": 1}


def us(on: str):
    return {"destination": "US", "currency": "USD", "seller_country": "GB", "ioss_registered": True, "import_date": on,
            "shipping": "14.00", "items": [MUG], "change_window_days": 0, "origin_groups": {"EU": ["PT", "DE", "FR"]}}


def test_uk_mug_through_every_legal_period(conn):
    v, reports = seed_register(conn, "r-test.1")
    assert sum(r.rows_added for r in reports) > 150
    expect = {
        "2025-01-15": ("0.00", "de minimis 800 dollars: duty-free"),
        "2025-06-01": ("0.00", "IEEPA reciprocal 10% exists but de minimis still applies"),
        "2025-09-15": ("7.60", "de minimis suspended: 10% general + 10% IEEPA"),
        "2026-03-15": ("7.60", "IEEPA ended, Section 122 10% + 10% general"),
        "2026-07-23": ("7.60", "last day of Section 122"),
        "2026-07-24": ("7.60", "Section 301 UK +10%"),
        "2026-10-29": ("7.60", "demo anchor"),
    }
    for d, (duty, why) in expect.items():
        rows = repo.rows_for_pricing(conn, "US", date.fromisoformat(d), v, 0)
        r = price(us(d), rows)
        assert r.supported, (d, r.unsupported_reason)
        assert r.tax_total == Decimal(duty), (d, why, r.tax_total)
        assert all(t.source_ref for t in r.trail), d


def test_india_not_priced_before_it_is_curated(conn):
    v, _ = seed_register(conn, "r-test.1")
    item = {**MUG, "origin": "IN"}
    early = price({**us("2025-10-01"), "items": [item]}, repo.rows_for_pricing(conn, "US", date(2025, 10, 1), v, 0))
    assert not early.supported and early.unsupported_reason == "origin_not_covered"
    late = price({**us("2026-10-29"), "items": [item]}, repo.rows_for_pricing(conn, "US", date(2026, 10, 29), v, 0))
    assert late.supported and late.tax_total == Decimal("7.60")
