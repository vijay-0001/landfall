"""Tests never reach the live internet: the on-demand US tariff read is switched off for every test run."""
import os

os.environ["LANDFALL_US_ONDEMAND"] = "off"
os.environ["LANDFALL_SEED_STOREFRONT"] = "off"
os.environ["LANDFALL_ALLOW_SIGNUP"] = "1"  # sign-up is closed by default; tests open it
os.environ["LANDFALL_SIGNING_KEY"] = "test-signing-key-not-a-secret"
