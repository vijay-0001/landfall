"""Where a parcel can be shipped to, and how each country is priced.

A ship-to country maps to a pricing destination (US, GB, EU, AU, CA) and, for the EU and Canada, a region (member state or province) that decides the
VAT or sales tax. Each destination has its own currency, thresholds and data source; Landfall never converts currency, so a product needs a seller-set
price in the destination currency to be sold there.
"""
from __future__ import annotations

DEST_CURRENCY = {"US": "USD", "GB": "GBP", "EU": "EUR", "AU": "AUD", "CA": "CAD"}
DEST_LABEL = {"US": "United States", "GB": "United Kingdom", "EU": "European Union", "AU": "Australia", "CA": "Canada"}
# Flat shipping the seller charges per order, per destination currency (seller-set, not converted).
SHIPPING = {"USD": "14.00", "GBP": "11.00", "EUR": "12.00", "AUD": "19.00", "CAD": "18.00"}

# EU member states: ISO-2 -> (register member-state code, name). Greece is EL in the register (TEDB), GR in ISO.
EU_STATES = {
    "AT": ("AT", "Austria"), "BE": ("BE", "Belgium"), "BG": ("BG", "Bulgaria"), "HR": ("HR", "Croatia"), "CY": ("CY", "Cyprus"), "CZ": ("CZ", "Czechia"),
    "DK": ("DK", "Denmark"), "EE": ("EE", "Estonia"), "FI": ("FI", "Finland"), "FR": ("FR", "France"), "DE": ("DE", "Germany"), "GR": ("EL", "Greece"),
    "HU": ("HU", "Hungary"), "IE": ("IE", "Ireland"), "IT": ("IT", "Italy"), "LV": ("LV", "Latvia"), "LT": ("LT", "Lithuania"), "LU": ("LU", "Luxembourg"),
    "MT": ("MT", "Malta"), "NL": ("NL", "Netherlands"), "PL": ("PL", "Poland"), "PT": ("PT", "Portugal"), "RO": ("RO", "Romania"), "SK": ("SK", "Slovakia"),
    "SI": ("SI", "Slovenia"), "ES": ("ES", "Spain"), "SE": ("SE", "Sweden"),
}
CA_PROVINCES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick", "NL": "Newfoundland and Labrador", "NS": "Nova Scotia", "NT": "Northwest Territories",
    "NU": "Nunavut", "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec", "SK": "Saskatchewan", "YT": "Yukon",
}
EU_DEFAULT_STATE = "DE"  # decision D-007: EU quotes default to Germany (19% VAT) when no member state is given
CA_DEFAULT_PROVINCE = "ON"
AVAILABLE = ("US", "GB", "EU", "AU")  # destinations whose rules and data are in the register today; AU and CA join as they are built


def countries(available: tuple[str, ...] | None = None) -> list[dict]:
    """Every ship-to country as {country, name, destination, currency, region, region_label}."""
    ok = available or AVAILABLE
    out = []
    for code, name, dest in (("US", "United States", "US"), ("GB", "United Kingdom", "GB"), ("AU", "Australia", "AU"), ("CA", "Canada", "CA")):
        if dest in ok:
            out.append({"country": code, "name": name, "destination": dest, "currency": DEST_CURRENCY[dest], "region": CA_DEFAULT_PROVINCE if dest == "CA" else None})
    if "EU" in ok:
        for iso, (state, name) in sorted(EU_STATES.items(), key=lambda kv: kv[1][1]):
            out.append({"country": iso, "name": name, "destination": "EU", "currency": "EUR", "region": state})
    return out


def resolve(country: str) -> dict | None:
    return next((c for c in countries() if c["country"] == country.upper().strip()), None)
