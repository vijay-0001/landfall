"""Wide coverage: the whole tariff is searchable. The model first picks up to three headings from the full heading menu, then the usual
two-call classification runs on the 6-digit codes under those headings only."""
import json

import pytest
from landfall_classifier import Listing
from landfall_classifier.candidates import all_headings, describe, heading_menu, load_candidates
from landfall_classifier.wide import classify_wide, select_headings

needs_whole = pytest.mark.skipif(len(all_headings()) < 1000, reason="the whole-tariff recordings are fetched at seed or deploy time (tools/fetch_hts_all.py)")


@needs_whole
def test_the_whole_tariff_is_available_to_the_classifier():
    assert len(all_headings()) > 1000
    menu = heading_menu()
    assert "9503" in menu and "toy" in menu["9503"].lower() or "tricycles" in menu["9503"].lower()
    assert "3304" in menu and "8517" in menu
    toys = load_candidates(headings=["9503"])
    assert toys and all(k.startswith("9503") for k in toys)
    assert "9503" in {k[:4] for k in load_candidates(headings=["9503", "6912"])} and "6912.00" in load_candidates(headings=["6912"])
    assert describe("6912.00") and describe("9503.00")  # any code can be described, not just the old core list


class Script:
    """Answers the heading menu with the given headings, then the classification calls with the given answer."""

    def __init__(self, heads, answer):
        self.heads, self.answer, self.systems = heads, answer, []

    def complete(self, system, user, max_tokens=600):
        self.systems.append(system)
        if "heading menu" in system.lower():
            return json.dumps({"reason": "a toy", "headings": self.heads})
        return json.dumps(self.answer)


ANSWER = {"reason": "a toy car", "hs6": "9503.00", "runner_up": None, "decisive_unknown": None, "origin_reason": "label", "origin": "CN",
          "signals": [{"kind": "label_photo", "text": "Made in China", "points_to": "CN"}]}


@needs_whole
def test_select_headings_keeps_only_real_headings_in_order_and_at_most_three():
    llm = Script(["9503", "0000", "9503", "9504", "9505", "9506"], ANSWER)
    heads, err = select_headings(llm, Listing(title="Toy car", description="Die-cast toy car"))
    assert heads == ["9503", "9504", "9505"] and err is None


@needs_whole
def test_classify_wide_runs_the_two_calls_on_the_chosen_headings_only():
    llm = Script(["9503"], ANSWER)
    raw, cands = classify_wide(llm, Listing(title="Toy car", description="Die-cast toy car", shop_country="GB"))
    assert raw.a.hs6 == "9503.00" and raw.b.hs6 == "9503.00" and not raw.errors
    assert cands and all(k.startswith("9503") for k in cands)
    classify_systems = [s for s in llm.systems if "heading menu" not in s.lower()]
    assert len(classify_systems) == 2 and all("  9503.00 " in s and "  6912.00 " not in s for s in classify_systems)  # the narrowed list, not the whole tariff


def test_when_the_heading_step_fails_the_core_list_is_the_fallback():
    llm = Script([], ANSWER)
    raw, cands = classify_wide(llm, Listing(title="Mug", description="A mug"))
    assert "6912.00" in cands  # the old core list


class Retry:
    """First heading pass names toys; both classification calls say none; the second pass (told to try different headings) names 9504, which fits."""

    def __init__(self):
        self.menu_calls = 0

    def complete(self, system, user, max_tokens=600):
        if "heading menu" in system.lower():
            self.menu_calls += 1
            return json.dumps({"reason": "r", "headings": ["9503"] if self.menu_calls == 1 else ["9504"]})
        if "  9503.00 " in system:
            return json.dumps({**ANSWER, "hs6": "none"})
        return json.dumps({**ANSWER, "hs6": "9504.40"})


@needs_whole
def test_when_both_calls_find_nothing_a_second_heading_pass_is_tried():
    llm = Retry()
    raw, cands = classify_wide(llm, Listing(title="Stone mug", description="A mug carved from stone"))
    assert llm.menu_calls == 2 and raw.a.hs6 == "9504.40" and all(k.startswith("9504") for k in cands)
