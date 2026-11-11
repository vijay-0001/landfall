"""API tests never reach the internet: Easyship is switched off unless a test hands one in."""
import pytest
from landfall_api.services import catalogue, shipment


@pytest.fixture(autouse=True)
def no_live_easyship(monkeypatch):
    monkeypatch.setattr(shipment, "easyship_client", lambda: None)


@pytest.fixture(autouse=True)
def no_live_uk_tariff(monkeypatch):
    def offline(path):
        raise OSError("tests never reach the UK Trade Tariff")

    monkeypatch.setattr(catalogue, "uk_get", offline)
