"""The rule form: a field survives only with a quote that is really in the notice and a value that passes its rule check.

Runs on the recorded text of FR 2026-21600 (CBP, 22 Oct 2026) and a fake model. No network.
"""
import json
from pathlib import Path

import pytest
from landfall_rules import federal_register as fr
from landfall_rules.draft import draft_rule, normalise

FIX = Path(__file__).parent / "fixtures"
TEXT = (FIX / "2026-21600.txt").read_text(encoding="utf-8")
DATE_Q = "The compliance date for 19 CFR 145.12(a)(2)(v) and (vi) is January 20, 2027."
MEASURE_Q = "mandating the formal entry of merchandise arriving through the international postal network"


class Fake:
    def __init__(self, reply: dict | str):
        self.reply, self.seen = reply, []

    def complete(self, system, user, max_tokens=600):
        self.seen.append((system, user))
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)


def form(**over):
    base = {n: {"value": None, "quote": None} for n in ["destination", "code_pattern", "origin_scope", "measure", "rate", "valid_from", "valid_to"]}
    base.update(over)
    return {"relevant": True, "title": "Formal entry for postal parcels", "fields": base}


def test_good_fields_keep_their_quotes_and_missing_ones_stay_blank():
    d = draft_rule(Fake(form(
        destination={"value": "US", "quote": "U.S. Customs and Border Protection (CBP) will extend the compliance date"},
        measure={"value": "process_requirement", "quote": MEASURE_Q},
        valid_from={"value": "2027-01-20", "quote": DATE_Q})), "title", TEXT)
    assert d.relevant and d.model == "claude-haiku-5-5" and d.prompt_version == "rule-v2"
    assert d.fields["valid_from"] == {"value": "2027-01-20", "quote": DATE_Q}
    assert d.fields["destination"]["value"] == "US"
    assert d.fields["rate"] == {"value": None, "quote": None} and d.fields["valid_to"] == {"value": None, "quote": None}
    assert d.dropped == []


def test_a_quote_that_is_not_in_the_notice_blanks_the_field():
    d = draft_rule(Fake(form(origin_scope={"value": "GB", "quote": "All goods of the United Kingdom shall pay ten percent"})), "t", TEXT)
    assert d.fields["origin_scope"] == {"value": None, "quote": None}
    assert d.dropped == ["origin_scope: quote not found in the notice"]


def test_a_real_sentence_that_does_not_contain_the_value_is_not_evidence():
    """The first real run showed rate 50 backed by a sentence about products of Canada. The quote must contain the value."""
    d = draft_rule(Fake(form(
        rate={"value": "50", "quote": MEASURE_Q}, valid_from={"value": "2027-01-21", "quote": DATE_Q},
        origin_scope={"value": "CA", "quote": MEASURE_Q}, destination={"value": "GB", "quote": MEASURE_Q},
        code_pattern={"value": "4202", "quote": MEASURE_Q}, measure={"value": "additional_duty", "quote": MEASURE_Q})), "t", TEXT)
    assert [f for f, v in d.fields.items() if v["value"]] == []
    assert len(d.dropped) == 6 and all("does not contain" in x for x in d.dropped)


def test_supported_values_pass_the_content_check():
    q_rate = "an additional 10 percent ad valorem duty"
    from landfall_rules.draft import _supports, quote_dates
    assert _supports("rate", "10", q_rate) and _supports("rate", "7.5", "a 7.5% duty") and not _supports("rate", "1", q_rate)
    assert quote_dates("effective on or after 12:01 a.m. on July 24, 2026 and 1 March 2027 and 2027-05-06") == {"2026-07-24", "2027-03-01", "2027-05-06"}
    assert _supports("code_pattern", "4202", "products of subheading 4202.31.60 of the HTSUS") and not _supports("code_pattern", "6912", "subheading 4202.31")
    assert _supports("origin_scope", "GB", "articles the product of the United Kingdom") and _supports("destination", "US", "entered into the United States")
    assert _supports("measure", "additional_duty", "an additional duty") and not _supports("measure", "additional_duty", "a filing deadline")


def test_value_without_quote_and_quote_without_value_are_blanked():
    d = draft_rule(Fake(form(rate={"value": "10", "quote": None}, valid_to={"value": None, "quote": DATE_Q})), "t", TEXT)
    assert d.fields["rate"]["value"] is None and d.fields["valid_to"]["value"] is None and len(d.dropped) == 2


def test_a_real_quote_with_an_invalid_value_is_blanked():
    d = draft_rule(Fake(form(valid_from={"value": "20 January 2027", "quote": DATE_Q}, rate={"value": "ten", "quote": DATE_Q},
                             destination={"value": "France", "quote": DATE_Q})), "t", TEXT)
    assert [f for f, v in d.fields.items() if v["value"]] == []
    assert len(d.dropped) == 3


def test_a_quote_survives_line_wraps_page_markers_and_smart_quotes():
    wrapped = "The compliance date for 19 CFR 145.12(a)(2)(v)\n and (vi) is\nJanuary 20, 2027."
    assert normalise(wrapped) in normalise(TEXT)
    assert normalise("[[Page 66639]] It’s") == "it's"
    d = draft_rule(Fake(form(valid_from={"value": "2027-01-20", "quote": wrapped})), "t", TEXT)
    assert d.fields["valid_from"]["value"] == "2027-01-20"


def test_not_relevant_is_not_queued_and_junk_is_an_error():
    assert draft_rule(Fake({"relevant": False}), "t", TEXT).relevant is False
    with pytest.raises(ValueError):
        draft_rule(Fake("I cannot help with that"), "t", TEXT)


def test_the_notice_text_reaches_the_model_and_the_prompt_forbids_inventing():
    f = Fake({"relevant": False})
    draft_rule(f, "Some title", TEXT)
    system, user = f.seen[0]
    assert "Some title" in user and "January 20, 2027" in user
    assert "Never invent a quote" in system


def test_prefilter_keeps_trade_notices_and_drops_noise():
    docs = json.loads((FIX / "fr_list_cbp.json").read_text(encoding="utf-8"))["results"]
    kept = {d["document_number"] for d in docs if fr.is_candidate(d)}
    assert {"2026-21570", "2026-21600"} <= kept
    assert "2026-20650" not in {d["document_number"] for d in [{"document_number": "2026-20650", "type": "Proposed Rule", "title": "Low-Value Shipments", "abstract": ""}] if fr.is_candidate(d)}
    assert not kept & {"2026-21405", "2026-21406", "2026-21407", "2026-21408", "2026-21853"}  # lab accreditations and a permit fee
