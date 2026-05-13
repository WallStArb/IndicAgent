"""Shared utilities for AI agent prompt builders.

Single source of truth for formatting helpers, label maps, and constants
used across all prompt modules (skeptic, narrative, future risk).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

DIRECTION_LABELS: dict[int, str] = {1: "LONG", -1: "SHORT", 0: "FLAT"}
REGIME_LABELS: dict[int, str] = {0: "Ranging", 1: "Trending Up", 2: "Trending Down"}


def fmt(val: Any, spec: str) -> str:
    """Format a numeric value with the given format spec, or return N/A."""
    if isinstance(val, (int, float)):
        return format(val, spec)
    return "N/A"


def parse_llm_json(raw: str, validator_fn: Callable[[dict], dict | None]) -> dict | None:
    """Try direct JSON parse → brace-counting extract fallback → None on failure.

    Single source of truth for all multiplier agents (moved from skeptic_agent.py).
    validator_fn receives the parsed dict and returns either a normalized dict or None.

    Uses brace-counting instead of a flat regex so nested JSON structures (arrays,
    nested objects) produced by agents like counterfactual_v1 are matched correctly.
    The old JSON_BLOCK_RE = r"\\{[^{}]*\\}" only matched non-nested objects and
    silently returned None whenever the LLM wrapped JSON in explanation text AND
    the JSON contained nested braces.
    """
    try:
        data = json.loads(raw.strip())
        return validator_fn(data)
    except json.JSONDecodeError:
        pass

    # Scan for first '{' then walk chars tracking brace depth.
    start = raw.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(raw[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(raw[start : i + 1])
                    return validator_fn(data)
                except json.JSONDecodeError:
                    pass
    return None


def clamp(val: Any, lo: float, hi: float) -> float:
    """Clamp val to [lo, hi]. max(lo, min(hi, float(val)))."""
    return max(lo, min(hi, float(val)))
