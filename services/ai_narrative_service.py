#!/usr/bin/env python3
"""
AI Narrative Service — I8 LLM synthesis of trading signals into human-readable narratives

Subscribes to signals:SYMBOL:TF:aggregated stream. For each selected signal,
builds a structured prompt, calls Ollama (qwen3:8b), and publishes a narrative
to narratives:SYMBOL:TF stream and narrative:SYMBOL:TF:latest hash.

Version: 1.0.0
Last Updated: 2026-02-19
Status: Production Ready
"""

from __future__ import annotations

import asyncio
import json
import logging  # noqa: F401  # used in _setup_logging (added in Task 2)
import os
import signal
import sys
import time
import urllib.request
from asyncio import to_thread
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from logging.handlers import RotatingFileHandler  # noqa: E402

import redis.asyncio as redis  # noqa: E402
import structlog  # noqa: E402

from src.config.settings import Settings  # noqa: E402
from src.core.stream_keys import narratives as sk_narratives  # noqa: E402
from src.core.stream_keys import signals_aggregated  # noqa: E402
from src.observability.metrics import counter, gauge, start_metrics_server  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a professional futures trading analyst. "
    "Given a market signal, write a concise 2-3 sentence trading narrative. "
    "Be specific about price levels and directional bias. No disclaimers."
)


# ---------------------------------------------------------------------------
# Pure helper functions (no I/O — easy to test)
# ---------------------------------------------------------------------------

def parse_aggregated_signal(fields: dict[bytes, bytes]) -> dict[str, Any] | None:
    """Parse a signals:aggregated stream message into a typed signal dict.

    Returns None if direction is 0 (no actionable signal to narrate).
    """
    def _get(key: str, default: str = "") -> str:
        raw = fields.get(key.encode(), b"")
        return (raw.decode() if isinstance(raw, bytes) else str(raw)).strip() or default

    direction = int(float(_get("direction", "0")))
    if direction == 0:
        return None

    return {
        "symbol": _get("symbol"),
        "timeframe": _get("timeframe"),
        "timestamp": _get("timestamp"),
        "direction": direction,
        "direction_label": "Bullish" if direction > 0 else "Bearish",
        "confidence": float(_get("confidence", "0.0")),
        "confluence_score": float(_get("confluence_score", "0.0")),
        "setup_plugin": _get("setup_plugin"),
        "signal_type": _get("signal_type"),
        "entry_price": _get("entry_price"),
        "stop_loss": _get("stop_loss"),
        "targets": _get("targets"),
        "regime_context": _get("regime_context"),
        "supporting_factors": _get("supporting_factors"),
    }


def build_narrative_prompt(signal: dict[str, Any]) -> str:
    """Build the Ollama user message from a parsed signal dict."""
    confidence_pct = f"{signal['confidence']:.0%}"
    return (
        f"/no_think\n\n"
        f"Symbol: {signal['symbol']}, Timeframe: {signal['timeframe']}\n"
        f"Setup: {signal['setup_plugin']} — {signal['direction_label']} (confidence {confidence_pct})\n"
        f"Entry: {signal['entry_price']} | Stop: {signal['stop_loss']} | Targets: {signal['targets']}\n"
        f"Regime: {signal['regime_context']}\n"
        f"Factors: {signal['supporting_factors']}"
    )
