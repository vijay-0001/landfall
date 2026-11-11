"""Australia: no customs duty at or below AUD 1,000, 5% above it; GST 10% charged at sale or at the border. Expected values are hand-derived."""
from decimal import Decimal

from landfall_engine import price

ROWS = [
    {"id": "d", "destination": "AU", "code": "*", "origin_scope": "ALL", "measure": "base_duty", "rate_kind": "percent", "rate": "5", "currency": None, "params": {},
     "valid_from": "2025-01-01", "valid_to": None, "source_ref": "t", "source_url": None},
    {"id": "l", "destination": "AU", "code": "*", "origin_scope": "ALL", "measure": "low_value_relief", "rate_kind": "fixed", "rate": "1000", "currency": "AUD", "params": {},
     "valid_from": "2025-01-01", "valid_to": None, "source_ref": "t", "source_url": None},
    {"id": "g", "destination": "AU", "code": "*", "origin_scope": "ALL", "measure": "import_vat", "rate_kind": "percent", "rate": "10", "currency": None, "params": {},
     "valid_from": "2025-01-01", "valid_to": None, "source_ref": "t", "source_url": None},
    {"id": "a", "destination": "AU", "code": "22", "origin_scope": "ALL", "measure": "special_duty_review", "rate_kind": "none", "rate": None, "currency": None, "params": {},
     "valid_from": "2025-01-01", "valid_to": None, "source_ref": "t", "source_url": None},
]


def quote(items, ship="19.00"):
    return price({"destination": "AU", "currency": "AUD", "seller_country": "GB", "ioss_registered": False, "import_date": "2026-11-10", "shipping": ship, "items": items,
                  "change_window_days": 5, "origin_groups": {}}, ROWS)


def item(sku, code, unit, qty=1):
    return {"sku": sku, "code": code, "origin": "GB", "unit_price": unit, "quantity": qty}


def test_low_value_order_pays_gst_only():
    r = quote([item("A", "6912.00.44.00", "58.00")])
    assert r.supported and r.duty_total == Decimal("0.00") and r.vat_total == Decimal("7.70")  # 10% of (58 + 19)


def test_order_above_the_threshold_pays_duty_and_gst_on_duty_too():
    r = quote([item("A", "6912.00.44.00", "600.00", 2)])  # 1,200
    assert r.duty_total == Decimal("60.00") and r.vat_total == Decimal("127.90")  # 10% of (1200 + 19 + 60)


def test_exactly_the_threshold_is_still_low_value():
    assert quote([item("A", "6912.00.44.00", "1000.00")]).duty_total == Decimal("0.00")


def test_alcohol_is_not_priced():
    r = quote([item("W", "2204.21.00.00", "40.00")])
    assert not r.supported and r.unsupported_reason == "special_duty_review"


def test_a_two_line_order_splits_gst_to_the_cent():
    r = quote([item("A", "6912.00.44.00", "10.01"), item("B", "6912.00.44.00", "20.02")])
    assert sum(ln.duty_and_tax for ln in r.lines) == r.tax_total == Decimal("4.90")  # 10% of (30.03 + 19) rounded half up
