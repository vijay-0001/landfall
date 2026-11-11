"""Golden duty cases. Written as data before the engine exists; each cites its official source.

Expected values are hand-derived from the cited rates, never produced by the engine.
Failing is the correct state until landfall_engine.price exists.
"""
import json
import pathlib
from decimal import Decimal

import pytest

GOLDEN = pathlib.Path(__file__).parent / "golden"
ROWS = json.loads((GOLDEN / "rows.json").read_text(encoding="utf-8"))
CASES = json.loads((GOLDEN / "cases.json").read_text(encoding="utf-8"))


def test_at_least_20_cases_each_with_a_source():
    assert len(CASES) >= 20
    for c in CASES:
        assert c["basis"], c["id"]
        assert c["verification"], c["id"]


def test_every_row_cites_a_source():
    for r in ROWS:
        assert r["source_ref"], r["id"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden(case):
    from landfall_engine import price  # fails until the engine exists

    result = price(case["input"], ROWS)
    exp = case["expected"]
    assert result.supported is exp["supported"], result
    if not exp["supported"]:
        assert result.unsupported_reason == exp["unsupported_reason"]
        return
    assert result.duty_total == Decimal(exp["duty_total"])
    assert result.vat_total == Decimal(exp["vat_total"])
    assert result.tax_total == Decimal(exp["tax_total"])
    assert sum(line.duty_and_tax for line in result.lines) == result.tax_total
    assert result.trail, "every price carries a calculation trail"
    for key in ("straddle_applied", "home_market"):
        if key in exp:
            assert getattr(result, key) is exp[key]
