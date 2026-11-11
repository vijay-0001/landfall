"""Country-rate exemptions (U.S. note 52), special-duty review and origin review. Expected values are hand-derived from the rates in the rows."""
from decimal import Decimal

from landfall_engine import price


def row(id_, measure, code="*", scope="ALL", rate=None, **params):
    return {"id": id_, "destination": "US", "code": code, "origin_scope": scope, "measure": measure,
            "rate_kind": "percent" if rate is not None else "none", "rate": rate, "currency": None, "params": params,
            "valid_from": "2026-02-24", "valid_to": None, "source_ref": f"test {id_}", "source_url": None}


ROWS = [
    row("base-toy", "base_duty", "9503.00.00", rate="0"), row("base-cup", "base_duty", "6912.00.44", rate="10"), row("base-hat", "base_duty", "6505.00.15", rate="5"),
    row("cov-vn", "origin_coverage", scope="VN"), row("cov-jp", "origin_coverage", scope="JP"), row("cov-ca", "origin_coverage", scope="CA"),
    row("vn", "additional_duty", scope="VN", rate="12.5", hts_heading="9903.05.84"),
    row("jp-floor", "total_rate_floor", scope="JP", rate="12.5", hts_headings=["9903.05.48", "9903.05.49"]),
    row("ca-usmca", "origin_review", scope="CA", reason="usmca_claim"),
    row("exempt-toy", "origin_exemption", "9503.00.00", hts_heading="9903.05.86"),
    row("exempt-vn-hat", "origin_exemption", "6505.00.15", scope="VN", hts_heading="9903.06.99"),
    row("s232-steel", "special_duty_review", "73"),
]


def quote(code, origin, price_="100.00"):
    inp = {"destination": "US", "currency": "USD", "seller_country": "GB", "ioss_registered": False, "import_date": "2026-10-29", "shipping": "10.00",
           "items": [{"sku": "X", "code": code, "origin": origin, "unit_price": price_, "quantity": 1}], "change_window_days": 5, "origin_groups": {}}
    return price(inp, ROWS)


def test_vietnam_pays_the_base_duty_plus_12_5_percent():
    r = quote("6912.00.44.00", "VN")
    assert r.supported and r.duty_total == Decimal("22.50")  # 10% + 12.5% of 100


def test_a_line_on_the_note_52_exemption_list_skips_the_country_duty():
    r = quote("9503.00.00.00", "VN")
    assert r.supported and r.duty_total == Decimal("0.00")  # base 0%, country duty switched off for this line
    assert any("Exempt" in t.label for t in r.trail)


def test_a_per_country_exemption_applies_to_that_country_only():
    assert quote("6505.00.15.00", "VN").duty_total == Decimal("5.00")  # exempt for Vietnam: base 5% only


def test_a_total_rate_floor_is_switched_off_too_when_exempt():
    assert quote("9503.00.00.00", "JP").duty_total == Decimal("0.00")
    assert quote("6912.00.44.00", "JP").duty_total == Decimal("12.50")  # floor 12.5% total, base 10%


def test_special_duty_review_refuses_instead_of_pricing_without_it():
    r = quote("7323.93.00.00", "VN")
    assert not r.supported and r.unsupported_reason == "special_duty_review"


def test_origin_review_refuses_with_its_own_reason():
    r = quote("6912.00.44.00", "CA")
    assert not r.supported and r.unsupported_reason == "usmca_claim"
