"""Settings from the environment. A local .env at the repo root is read for development; it is never logged or committed."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def load_env() -> None:
    root = Path(__file__).resolve().parents[3]
    f = root / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip())


def env(name: str, default: str | None = None) -> str | None:
    load_env()
    return os.environ.get(name, default)
