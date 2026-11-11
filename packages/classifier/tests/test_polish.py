"""Seller-facing text: whole sentences, real country names, no stray capitals."""
from decimal import Decimal

from landfall_classifier.rules import country_name
from landfall_classifier.text import lower_first, shorten


def test_shorten_cuts_at_a_sentence_then_a_word_never_mid_word():
    s = "A mug is a drinking vessel. It falls under heading 6912 because it is household ware. The nearest wrong candidate is 6914."
    assert shorten(s, 60) == "A mug is a drinking vessel."
    assert shorten(s, 200) == s
    one = "Ceramic tableware kitchenware other household articles and toilet articles other than of porcelain or china"
    out = shorten(one, 40)
    assert out.endswith("…") and len(out) <= 40 and not out[:-1].endswith(" ") and one.startswith(out[:-1])
    assert out[:-1].split()[-1] in one.split()  # ends on a whole word
    assert shorten("", 10) == "" and shorten("short", 10) == "short"


def test_lower_first_only_touches_an_ordinary_capital():
    assert lower_first("Whether the leather is reptile") == "whether the leather is reptile"
    assert lower_first("USITC lists it") == "USITC lists it" and lower_first("") == ""


def test_country_names_cover_common_origins_not_just_the_register_ones():
    assert country_name("IS") == "Iceland" and country_name("CN") == "China" and country_name("ID") == "Indonesia" and country_name("MX") == "Mexico"
    assert country_name("ZZ") == "ZZ"  # unknown stays as given rather than inventing a name
    assert Decimal("1")


def test_a_missing_fact_is_not_prefixed_twice():
    from landfall_classifier.text import missing_fact

    assert missing_fact("the listing does not state the material (ceramic, stone, or other).") == "the material (ceramic, stone, or other)"
    assert missing_fact("Whether the outer leather is reptile leather") == "whether the outer leather is reptile leather"
    assert missing_fact("The listing does not specify whether it is glazed") == "whether it is glazed"


# ---------------------------------------------------------------- regulated goods are never priced, and the seller is told why (T5)
def _decide_for(title, description):
    from landfall_classifier import Listing, ModelAnswer, decide

    a = ModelAnswer.model_validate({"hs6": "6913.90", "reason": "a vase", "origin": "PK", "origin_reason": "made in Pakistan", "signals": []})
    return decide(a, a, Listing(title=title, description=description, shop_country="GB"), lambda hs6, origin: None, Decimal("40"))


def test_goods_landfall_will_not_price_say_so_with_the_plain_reason():
    cases = (("Uranium Vase", "Vase made from radioactive uranium found in mines.", "radioactive material", "dangerous goods"),
             ("Moon Rock Mug", "Mug made of rocks stolen from the Museum of Peace.", "stolen or looted goods", "unlawful"),
             ("Hunting rifle", "Antique rifle, fully working.", "weapons and explosives", "licences"),
             ("Carved tusk", "Hand carved elephant ivory tusk.", "protected wildlife", "treaty"),
             ("Designer bag", "A fake designer handbag.", "counterfeit goods", "seized"))
    for title, desc, cat, reason_bit in cases:
        d = _decide_for(title, desc)
        assert d.hs6 == "none" and d.triggers == ["T5"] and d.band == "check", title
        assert d.headline == f"Landfall will not price this: {cat}", title
        assert cat in d.paused_reason and reason_bit in d.paused_reason.lower() and reason_bit in d.code_reason.lower(), title
        assert "outside ceramics" not in (d.headline + d.paused_reason).lower()


def test_ordinary_listings_are_not_caught_by_the_regulated_screen():
    for title, desc in (("Gunmetal grey mug", "Stoneware mug in a gunmetal glaze."), ("Pistachio dish", "A ceramic dish."), ("Ivory linen napkins", "Cream napkins in ivory.")):
        d = _decide_for(title, desc)
        assert d.paused_reason is None, title
