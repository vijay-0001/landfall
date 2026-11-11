"""A recorded UK Trade Tariff for tests (no network)."""
import json
from pathlib import Path

from landfall_register import loaders

FIX = Path(loaders.FIXTURES) / "uk_tariff" / "ondemand"


def recorded_tariff():
    def get(path: str) -> dict:
        kind, ident = path.split("/")
        f = FIX / f"{'heading' if kind == 'headings' else 'commodity'}_{ident}.json"
        if not f.exists():
            raise OSError(f"no recording for {path}")
        return json.loads(f.read_text(encoding="utf-8"))

    return get
