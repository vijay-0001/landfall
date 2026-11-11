"""Classifier tests with a fake model: bands, triggers T1 to T6 behaviour, schema validation, Haiku-only rule. No network."""
import json
from decimal import Decimal

import pytest
from landfall_classifier import MODEL, Listing, classify, decide, load_candidates
from landfall_classifier.pipeline import ModelAnswer

CANDS = {"6912.00": "ceramic tableware", "6914.90": "other ceramic", "4202.31": "wallets leather", "4202.32": "wallets textile", "4202.22": "handbags textile"}


class Fake:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    def complete(self, system, user, max_tokens=600):
        self.calls += 1
        r = self.replies.pop(0)
        return r if isinstance(r, str) else json.dumps(r)


def ans(hs6="6912.00", origin="GB", signals=None, **kw):
    return {"hs6": hs6, "reason": "r", "origin": origin, "origin_reason": "o", "signals": signals or [{"kind": "listing_text", "text": "thrown in our studio", "points_to": origin}], **kw}


L = Listing(title="t", description="d")
flat = lambda hs6, origin: Decimal("7.60")  # noqa: E731  (a quoter that prices everything alike)


def test_haiku_only():
    assert MODEL == "claude-haiku-5-5"


def test_candidates_come_from_the_register_headings():
    c = load_candidates()
    assert "6912.00" in c and "4202.31" in c and "6302.51" in c and len(c) > 60
    assert all(len(k) == 7 for k in c)


def test_mug_is_high_and_asks_nothing():
    raw = classify(Fake(ans(), ans()), L, CANDS)
    d = decide(raw.a, raw.b, L, flat, Decimal("38"))
    assert d.band == "high" and d.questions == [] and d.triggers == []


def test_label_vs_listing_conflict_is_T2_and_label_wins():
    sig = [{"kind": "label_photo", "text": "MADE IN CHINA", "points_to": "CN"}, {"kind": "listing_text", "text": "hand-finished in Britain", "points_to": "GB"}]
    raw = classify(Fake(ans("4202.31", "CN", sig), ans("4202.31", "GB", sig)), L, CANDS)
    quote = lambda hs6, o: {"CN": Decimal("3.90"), "GB": Decimal("3.20")}.get(o)  # noqa: E731
    d = decide(raw.a, raw.b, L, quote, Decimal("26"))
    assert d.band == "ask" and d.origin == "CN" and d.triggers == ["T2"]
    q = d.questions[0]
    assert q.id == "q_origin" and "MADE IN CHINA" in q.text
    by = {o.value: o for o in q.options}
    assert by["CN"].is_ai_pick and by["CN"].impact == Decimal("0.00") and by["GB"].impact == Decimal("-0.70")


def test_shop_country_is_the_weakest_signal():
    sig = [{"kind": "shop_country", "text": "shop is in the UK", "points_to": "GB"}]
    raw = classify(Fake(ans(signals=sig), ans(signals=sig)), L, CANDS)
    d = decide(raw.a, raw.b, L, flat, Decimal("38"))
    assert d.triggers == ["T4"] and d.band == "ask"  # only the weakest signal on an origin-specific list


def test_transformed_product_is_T3():
    raw = classify(Fake(ans("4202.22", "IN", transformed=True), ans("4202.22", "IN", transformed=True)), L, CANDS)
    d = decide(raw.a, raw.b, L, flat, Decimal("24"))
    assert d.triggers == ["T3"] and "blank" in d.questions[0].text


def test_t1_fires_only_when_the_price_gap_exceeds_the_tolerance():
    raw = classify(Fake(ans("4202.31"), ans("4202.32")), L, CANDS)
    small = decide(raw.a, raw.b, L, lambda h, o: Decimal("5.00") if h == "4202.31" else Decimal("5.90"), Decimal("100"))
    big = decide(raw.a, raw.b, L, lambda h, o: Decimal("5.00") if h == "4202.31" else Decimal("9.00"), Decimal("100"))
    assert "T1" not in small.triggers and small.band == "check"
    assert big.triggers[0] == "T1" and big.band == "ask" and big.questions[0].id == "q_code"


def test_a_far_fetched_runner_up_does_not_cause_a_question():
    raw = classify(Fake(ans(runner_up="6914.90"), ans(runner_up="6914.90")), L, CANDS)
    d = decide(raw.a, raw.b, L, lambda h, o: Decimal("7.60") if h == "6912.00" else Decimal("20"), Decimal("38"))
    assert d.band == "high" and d.questions == []


def test_disagreement_without_price_impact_is_check_never_bulk_acceptable():
    raw = classify(Fake(ans("6912.00"), ans("6914.90")), L, CANDS)
    d = decide(raw.a, raw.b, L, flat, Decimal("38"))
    assert d.band == "check"


def test_regulated_goods_pause_duties_included_T5():
    raw = classify(Fake(ans(regulated=True, regulated_reason="a cosmetic"), ans()), L, CANDS)
    d = decide(raw.a, raw.b, L, flat, Decimal("20"))
    assert "T5" in d.triggers and d.paused_reason and "Not available for duties-included" in d.paused_reason and d.questions == []


def test_at_most_four_questions():
    sig = [{"kind": "label_photo", "text": "X", "points_to": "CN"}, {"kind": "listing_text", "text": "Y", "points_to": "GB"}]
    raw = classify(Fake(ans("4202.31", "CN", sig), ans("4202.32", "GB", sig)), L, CANDS)
    d = decide(raw.a, raw.b, L, lambda h, o: Decimal("1") if h == "4202.31" else Decimal("20"), Decimal("26"))
    assert len(d.questions) <= 4


def test_invalid_output_is_retried_once_then_recorded_not_papered_over():
    f = Fake("not json", "still not json", ans(), ans())
    raw = classify(f, L, CANDS)
    assert raw.a is None and raw.b is not None and len(raw.errors) == 1 and f.calls == 3
    d = decide(raw.a, raw.b, L, flat, Decimal("38"))
    assert d.band == "check"  # one run only: never High


def test_code_outside_the_closed_list_is_rejected():
    raw = classify(Fake(ans("9999.99"), ans("9999.99"), ans("9999.99"), ans("9999.99")), L, CANDS)
    assert raw.a is None and raw.b is None
    assert decide(raw.a, raw.b, L, flat, Decimal("1")) is None


def test_origin_must_be_iso2():
    try:
        ModelAnswer(hs6="6912.00", reason="r", origin="United Kingdom", origin_reason="o")
        raise AssertionError("should have been rejected")
    except ValueError:
        pass


# ---------------------------------------------------------------- harness fixes from the first accuracy run
def test_the_subheading_line_keeps_its_own_text_in_the_candidate_list():
    c = load_candidates()
    assert "man-made" in c["6302.53"].lower() and "cotton" in c["6302.91"].lower()  # these were "Other table linen" and "Other"
    assert c["6302.51"].endswith("Of cotton")


def test_apparel_headings_the_eval_set_uses_are_in_the_closed_list():
    c = load_candidates()
    assert {"6104.62", "6111.20", "6206.30"} <= set(c)  # their absence made 15 of 200 listings unanswerable


def test_parse_json_takes_the_first_object_and_ignores_the_rest():
    from landfall_classifier import parse_json

    assert parse_json('Sure: {"a": 1} and then {"b": 2}') == {"a": 1}
    assert parse_json('{"a": {"b": [1, 2]}} trailing') == {"a": {"b": [1, 2]}}
    with pytest.raises(ValueError):
        parse_json("no json here")


def test_a_wordy_reason_is_shortened_not_rejected():
    from landfall_classifier import ModelAnswer

    a = ModelAnswer.model_validate({"hs6": "6912.00", "reason": "x" * 450, "origin": "gb", "origin_reason": "y" * 301})
    assert len(a.reason) <= 300 and a.reason.endswith("…") and len(a.origin_reason) <= 300 and a.origin == "GB"


# ---------------------------------------------------------------- an unstated deciding fact is as uncertain as a disagreement (cls-v2)
def classify_pair(a: dict, b: dict):
    """Run the real two-call classify over a fake model and return the two validated answers."""
    r = classify(Fake(a, b), L, {**CANDS, "6203.42": "men's trousers cotton", "6204.62": "women's trousers cotton"})
    return r.a, r.b


def pair(gap: str):
    return lambda hs6, origin: Decimal("0.00") if hs6 == "4202.31" else Decimal(gap)


def test_two_calls_that_agree_but_name_an_unstated_deciding_fact_ask_when_duty_differs():
    a = ans("4202.31", runner_up="4202.32", decisive_unknown="whether the outer surface is leather or textile")
    b = ans("4202.31", runner_up="4202.32", decisive_unknown=None)
    d = decide(classify_pair(a, b)[0], classify_pair(a, b)[1], L, pair("5.00"), Decimal("40"))
    assert d.band == "ask" and d.triggers == ["T1"] and d.questions[0].trigger == "T1"
    assert "does not say whether the outer surface is leather or textile" in d.questions[0].help
    assert {o.value for o in d.questions[0].options} == {"4202.31", "4202.32"}


def test_an_unstated_fact_with_the_same_duty_is_check_not_high_and_asks_nothing():
    a = ans("6203.42", runner_up="6204.62", decisive_unknown="whether the jeans are for men or women")
    d = decide(classify_pair(a, ans("6203.42"))[0], classify_pair(a, ans("6203.42"))[1], L, flat, Decimal("40"))
    assert d.questions == [] and d.band == "check" and "does not say whether the jeans are for men or women" in d.headline


def test_a_stated_listing_stays_high():
    a, b = ans("6912.00", decisive_unknown=None), ans("6912.00", decisive_unknown=None)
    d = decide(classify_pair(a, b)[0], classify_pair(a, b)[1], L, flat, Decimal("40"))
    assert d.band == "high" and d.questions == []


# ---------------------------------------------------------------- goods outside the closed list are paused, never forced into a code (cls-v4)
def test_a_product_outside_the_list_is_paused_not_forced_into_a_code():
    raw = classify(Fake(ans("none", reason="Chocolate confectionery, chapter 18"), ans("none", reason="Cocoa preparation")), L, CANDS)
    d = decide(raw.a, raw.b, L, flat, Decimal("20"))
    assert d.hs6 == "none" and d.triggers == ["T5"] and d.questions == [] and d.band == "check"
    assert "could not match" in d.paused_reason and "standard checkout" in d.paused_reason.lower()


def test_none_is_accepted_by_the_closed_list_check_but_other_codes_are_not():
    assert classify(Fake(ans("none"), ans("none")), L, CANDS).errors == []
    assert classify(Fake(ans("9999.99"), ans("9999.99"), ans("9999.99"), ans("9999.99")), L, CANDS).errors != []


def test_one_call_saying_none_and_one_giving_a_code_is_a_check_with_the_code_kept():
    raw = classify(Fake(ans("none"), ans("6912.00")), L, CANDS)
    d = decide(raw.a, raw.b, L, lambda h, o: Decimal("7.60"), Decimal("38"))
    assert d.hs6 == "6912.00" and d.band == "check" and d.questions == [] and d.paused_reason is None and d.runner_up is None


# ---------------------------------------------------------------- the national line is picked twice and asked about when it matters (cls-v4)
LINES = [{"code": "6302.31.30", "rate": "11.9", "description": "Other bed linen > Of cotton > Napped"},
         {"code": "6302.31.70", "rate": "3.8", "description": "Other bed linen > Of cotton > Not napped"},
         {"code": "6302.31.90", "rate": "6.7", "description": "Other bed linen > Of cotton > Other"}]


def line(code, runner_up=None, unknown=None):
    return {"reason": "r", "code": code, "runner_up": runner_up, "decisive_unknown": unknown}


def test_two_agreeing_line_picks_are_agreed_and_carry_the_labels():
    from landfall_classifier import pick_national

    r = pick_national(Fake(line("6302.31.70"), line("6302.31.70")), L, "6302.31", LINES)
    assert r.code == "6302.31.70" and r.agreed and r.decisive_unknown is None
    assert r.labels["6302.31.70"] == "Not napped (3.8%)"


def test_two_different_line_picks_are_not_agreed_and_keep_both():
    from landfall_classifier import pick_national

    r = pick_national(Fake(line("6302.31.30"), line("6302.31.90")), L, "6302.31", LINES)
    assert not r.agreed and r.code == "6302.31.30" and r.runner_up == "6302.31.90"


def test_a_code_outside_the_list_or_one_failed_call_never_becomes_the_answer():
    from landfall_classifier import pick_national

    r = pick_national(Fake("junk", "junk", line("6302.31.70"), line("9999.99.99"), line("9999.99.99")), L, "6302.31", LINES)
    assert r.code == "6302.31.70" and not r.agreed  # the second call never produced a valid line
    assert pick_national(Fake("x", "x", "x", "x"), L, "6302.31", LINES) is None


def result(code, runner_up, agreed=True, unknown=None):
    from landfall_classifier import NationalResult

    return NationalResult(code=code, reason="r", runner_up=runner_up, agreed=agreed, decisive_unknown=unknown,
                          labels={"6302.31.70": "Not napped (3.8%)", "6302.31.30": "Napped (11.9%)", "6302.31.90": "Other (6.7%)"})


RATE = {"6302.31.30": Decimal("4.76"), "6302.31.70": Decimal("1.52"), "6302.31.90": Decimal("2.68")}  # duty on a 40 dollar item


def run_decide(nat, hs="6302.31"):
    both = [ans(hs, "GB"), ans(hs, "GB")]
    raw = classify(Fake(*both), L, {**CANDS, hs: "bed linen of cotton"})
    return decide(raw.a, raw.b, L, flat, Decimal("40"), national=lambda h: nat, quote_line=lambda c, o: RATE[c])


def test_an_uncertain_line_with_materially_different_duty_asks_the_seller():
    d = run_decide(result("6302.31.70", "6302.31.30", agreed=False, unknown="whether the fabric is napped"))
    q = next(x for x in d.questions if x.id == "q_line")
    assert q.trigger == "T1" and "does not say whether the fabric is napped" in q.help and d.band == "ask"
    assert {o.value for o in q.options} == {"6302.31.70", "6302.31.30"} and [o.is_ai_pick for o in q.options] == [True, False]
    assert q.options[1].impact == Decimal("3.24")  # what choosing the other line does to the duty


def test_an_uncertain_line_with_the_same_duty_does_not_bother_the_seller():
    d = run_decide(result("6302.31.70", "6302.31.90", agreed=False))  # 1.52 against 2.68: inside the one dollar tolerance
    assert not any(x.id == "q_line" for x in d.questions)


def test_an_agreed_line_with_nothing_unstated_asks_nothing_even_if_other_lines_differ():
    d = run_decide(result("6302.31.70", "6302.31.30", agreed=True))
    assert not any(x.id == "q_line" for x in d.questions)


def test_a_line_that_cannot_be_priced_makes_the_recommendation_a_check():
    a, b = ans("6302.31", "GB"), ans("6302.31", "GB")
    raw = classify(Fake(a, b), L, {**CANDS, "6302.31": "bed linen of cotton"})
    d = decide(raw.a, raw.b, L, flat, Decimal("40"), national=lambda h: result("6302.31.70", "6302.31.30", agreed=False), quote_line=lambda c, o: None)
    assert d.band == "check" and not any(x.id == "q_line" for x in d.questions)
