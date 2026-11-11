"""Easyship adapter. Delivered duty paid, test mode only, and it can never buy a label."""
from .easyship import (
    EasyshipClient,
    LabelPurchaseRefused,
    ShippingError,
    build_rates_request,
    build_shipment_request,
    duty_from_rate,
    parse_shipment,
)

__all__ = ["EasyshipClient", "LabelPurchaseRefused", "ShippingError", "build_rates_request", "build_shipment_request", "duty_from_rate", "parse_shipment"]
