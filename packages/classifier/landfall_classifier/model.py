"""Haiku client. Rules (CLAUDE.md): claude-haiku-5-5 only, thinking disabled, read only `text` blocks, no temperature."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Protocol

MODEL = "claude-haiku-5-5"


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latencies: list[float] = field(default_factory=list)


class LLM(Protocol):
    def complete(self, system: str, user: str, max_tokens: int = 600) -> str: ...


class HaikuClient:
    model = MODEL

    def __init__(self, api_key: str):
        import anthropic

        self._c = anthropic.Anthropic(api_key=api_key, timeout=30.0, max_retries=2)
        self.usage = Usage()

    def complete(self, system: str, user: str, max_tokens: int = 600) -> str:
        t = time.time()
        r = self._c.messages.create(
            model=MODEL, max_tokens=max_tokens, thinking={"type": "disabled"},
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        self.usage.calls += 1
        self.usage.input_tokens += r.usage.input_tokens
        self.usage.output_tokens += r.usage.output_tokens
        self.usage.cache_read_tokens += getattr(r.usage, "cache_read_input_tokens", 0) or 0
        self.usage.cache_write_tokens += getattr(r.usage, "cache_creation_input_tokens", 0) or 0
        self.usage.latencies.append(time.time() - t)
        return "".join(b.text for b in r.content if b.type == "text")


    def complete_images(self, system: str, text: str, blocks: list[dict], max_tokens: int = 300) -> str:
        """One call with images: the photos are sent as they are and nothing is kept here. Same model, thinking off."""
        t = time.time()
        r = self._c.messages.create(
            model=MODEL, max_tokens=max_tokens, thinking={"type": "disabled"},
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": [*blocks, {"type": "text", "text": text}]}],
        )
        self.usage.calls += 1
        self.usage.input_tokens += r.usage.input_tokens
        self.usage.output_tokens += r.usage.output_tokens
        self.usage.latencies.append(time.time() - t)
        return "".join(b.text for b in r.content if b.type == "text")


def parse_json(text: str) -> dict:
    """First JSON object in the reply. Raises ValueError if there is none."""
    i = text.find("{")
    if i < 0:
        raise ValueError("no JSON object in model reply")
    obj, _ = json.JSONDecoder().raw_decode(text[i:])  # the first object only; trailing prose or a second object is ignored
    if not isinstance(obj, dict):
        raise ValueError("model reply is not a JSON object")
    return obj
