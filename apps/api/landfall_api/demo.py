"""Demo catalogue constants: Kiln & Co., Stoke-on-Trent, UK. Prices are the seller's own, per currency (no FX here).

National codes per destination are what the register uses at pricing time. The AI recommends the 6-digit code; the
national line is picked from the register's children of that 6-digit code (see recommender).
"""
from __future__ import annotations

SHOP = {"id": "shop_kiln", "name": "Kiln & Co.", "country": "GB", "city": "Stoke-on-Trent", "ioss_registered": True}

from .destinations import DEST_CURRENCY, DEST_LABEL, EU_DEFAULT_STATE, SHIPPING  # noqa: E402,F401  (kept here for older imports)

# The demo seller's recorded decisions (national US line per product). Haiku's own pick varies from run to run (a re-seed once chose 4205.00.80.00 for the
# wallet, which is not a wallet line), so the seed records these as the seller's decision when the AI's pick differs: the demo numbers then reproduce.
SEED_CODES = {"p_mug": "6912.00.44.00", "p_bowl": "6912.00.10.00", "p_napkins": "6302.51.30.00", "p_wallet": "4202.31.60.00", "p_tote": "6307.90.98",
              "p_tee": "6109.10.00", "p_spoons": "4419.90.11.00", "p_train": "9503.00.00"}

PRODUCTS = [
    {"id": "p_mug", "sku": "MUG-001", "title": "Hand-thrown stoneware mug", "category": "ceramics",
     "description": "Thrown by hand in our Stoke studio from British stoneware clay. Dishwasher safe. 350 ml.",
     "prices": {"GBP": "30.00", "USD": "38.00", "EUR": "35.00", "AUD": "58.00", "CAD": "52.00"}, "origin": "GB",
     "codes": {"US": "6912.00.44.00", "GB": "6912002310", "EU": "6912.00.44.00"}, "tm_label": "Handmade ceramic mug", "accept": True},
    {"id": "p_bowl", "sku": "BOWL-001", "title": "Stoneware serving bowl", "category": "ceramics",
     "description": "Wheel-thrown stoneware serving bowl, 24 cm, food-safe glaze, made in our Stoke studio.",
     "prices": {"GBP": "40.00", "USD": "52.00", "EUR": "47.00", "AUD": "78.00", "CAD": "70.00"}, "origin": "GB",
     "codes": {"US": "6912.00.48.90", "GB": "6912002310", "EU": "6912.00.48.90"}, "tm_label": "Stoneware serving bowl", "accept": True},
    {"id": "p_napkins", "sku": "NAP-004", "title": "Cotton napkins, set of 4", "category": "cotton",
     "description": "Stonewashed cotton napkins, set of 4, woven and sewn by our partner mill near Porto.",
     "prices": {"GBP": "28.00", "USD": "36.00", "EUR": "33.00", "AUD": "54.00", "CAD": "49.00"}, "origin": "PT",
     "codes": {"US": "6302.51.40.00", "GB": "6302510090", "EU": "6302.51.40.00"}, "tm_label": "Cotton napkins", "accept": True},
    {"id": "p_wallet", "sku": "WAL-001", "title": "Leather card wallet", "category": "leather",
     "description": "Slim leather card wallet, six card slots, hand-finished in Britain.",
     "prices": {"GBP": "20.00", "USD": "26.00", "EUR": "24.00", "AUD": "40.00", "CAD": "36.00"}, "origin": "CN",
     "codes": {"US": "4202.31.60.00", "GB": "4202310090", "EU": "4202.31.60.00"}, "tm_label": "Leather card wallet", "accept": True},
    {"id": "p_tote", "sku": "TOTE-001", "title": "Printed cotton tote", "category": "cotton",
     "description": "Cotton tote bag, screen-printed in our studio with the Kiln & Co. kiln design.",
     "prices": {"GBP": "19.00", "USD": "24.00", "EUR": "22.00", "AUD": "37.00", "CAD": "33.00"}, "origin": "IN",
     "codes": {"US": "4202.22.45.00", "GB": "4202229090", "EU": "4202.22.45.00"}, "tm_label": "Cotton tote bag", "accept": True},
    {"id": "p_tee", "sku": "TEE-001", "title": "Organic cotton t-shirt, unisex", "category": "Clothing",
     "description": "Plain crew-neck t-shirt, 100% organic cotton jersey, knitted and sewn for us by a small factory in Dhaka, Bangladesh. Sizes S to XL.",
     "prices": {"GBP": "22.00", "USD": "28.00", "EUR": "26.00", "AUD": "42.00", "CAD": "38.00"}, "origin": "BD", "accept": True, "extra": True},
    {"id": "p_spoons", "sku": "SPN-003", "title": "Olive wood spoon set, 3 pieces", "category": "Wood",
     "description": "Three hand-carved olive wood kitchen spoons (serving, stirring, tasting), oiled not varnished, carved by a family workshop in Vietnam.",
     "prices": {"GBP": "18.00", "USD": "23.00", "EUR": "21.00", "AUD": "35.00", "CAD": "31.00"}, "origin": "VN", "accept": True, "extra": True},
    {"id": "p_train", "sku": "TRN-024", "title": "Wooden toy train set, 24 pieces", "category": "Toys",
     "description": "Beech wood toy train with 24 pieces of track and bridges, painted with child-safe paint. For ages 3 and up. Made in China.",
     "prices": {"GBP": "34.00", "USD": "44.00", "EUR": "40.00", "AUD": "68.00", "CAD": "60.00"}, "origin": "CN", "accept": True, "extra": True},
    {"id": "p_vase", "sku": "VAS-001", "title": "Vintage uranium glass vase", "category": "Vintage",
     "description": "1930s vintage uranium glass vase that glows green under UV light. Slightly radioactive, as all uranium glass is. 18 cm tall.",
     "prices": {"GBP": "85.00", "USD": "110.00", "EUR": "99.00", "AUD": "170.00", "CAD": "150.00"}, "origin": "GB", "accept": False, "extra": True},
]
BY_ID = {p["id"]: p for p in PRODUCTS}

ORIGIN_LABEL = {"GB": "United Kingdom", "IN": "India", "CN": "China", "PT": "Portugal", "DE": "Germany", "FR": "France", "US": "United States", "BD": "Bangladesh", "VN": "Vietnam"}

# Shipment demo data. The demo checkout does not collect an address, so a clearly labelled sandbox buyer address is used.
WEIGHT_KG = {"p_mug": 0.4, "p_bowl": 0.9, "p_napkins": 0.25, "p_wallet": 0.1, "p_tote": 0.2, "p_tee": 0.2, "p_spoons": 0.3, "p_train": 1.1, "p_vase": 0.8}
DEFAULT_WEIGHT_KG = 0.5
SELLER_ADDRESS = {"line_1": "1 Potteries Way", "city": "Stoke-on-Trent", "state": "Staffordshire", "postal_code": "ST1 1AA", "country_alpha2": "GB",
                  "company_name": "Kiln & Co.", "contact_name": "Kiln Co", "contact_phone": "+441782000000", "contact_email": "shop@example.com"}
SANDBOX_BUYER_ADDRESS = {"US": {"line_1": "1 Main St", "city": "New York", "state": "NY", "postal_code": "10001", "country_alpha2": "US",
                                "contact_name": "Sandbox Buyer", "contact_phone": "+12125550100", "contact_email": "buyer@example.com"}}
