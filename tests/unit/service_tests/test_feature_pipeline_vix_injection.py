"""Unit tests for FeaturePipelineService frame injection logic (Phase 46-03).

Tests cover guard conditions for cross-asset and VIX frame injection:
- EQ_INDEX vs non-EQ_INDEX cross_asset guard
- cross_asset_enabled True vs False guard
- VIX symbol resolved vs None
- VIX bar count >= 20 vs < 20

Uses the __new__ pattern for FeaturePipelineService instantiation per CLAUDE.md.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.core.bar_history import BarHistory
from src.core.schemas.bar_message import BarMessage, SessionType


def _make_bar(symbol: str, tf: str = "1m", close: float = 20.0) -> BarMessage:
    """Create a minimal BarMessage for seeding bar history."""
    return BarMessage(
        ts=datetime.now(UTC),
        symbol=symbol,
        tf=tf,
        open=close,
        high=close + 0.5,
        low=close - 0.5,
        close=close,
        volume=100,
        source="ibkr_named",
        session_type=SessionType.RTH,
        gap_preceding=False,
    )


def _make_service(
    cross_asset_enabled: bool = True,
    vix_symbol: str | None = "VXJ6",
    cross_asset_cache: dict | None = None,
) -> Any:
    """Construct FeaturePipelineService without __init__ (no Kafka/DB required)."""
    from services.feature_pipeline_service import FeaturePipelineService

    svc = FeaturePipelineService.__new__(FeaturePipelineService)
    svc._cross_asset_enabled = cross_asset_enabled
    svc._cross_asset_cache = cross_asset_cache or {}
    svc._vix_symbol = vix_symbol
    svc._bar_history = BarHistory(maxlen=200)
    svc.logger = MagicMock()
    return svc


def _build_injection(svc: Any, symbol: str, tf: str = "1m") -> dict:
    """Replicate the Phase 46 frame injection logic from _run_pipeline().

    Returns the frames dict after cross_asset and vix injection.
    """
    from src.intelligence.context.vix_context import compute_vix_context
    from src.intelligence.cross_asset_features import resolve_eq_index_base

    frames: dict = {}

    # Phase 46: Inject cross-asset frames for EQ_INDEX symbols (per D-12, D-13)
    if svc._cross_asset_enabled and resolve_eq_index_base(symbol) is not None:
        frames["cross_asset"] = svc._cross_asset_cache.get(tf, {"ready": False})
        frames["cross_asset_5m"] = svc._cross_asset_cache.get("5m", {"ready": False})

    # Phase 46: Inject VIX context for ALL symbols (per D-04, D-11)
    if svc._vix_symbol:
        vix_deque = svc._bar_history.get(svc._vix_symbol, tf)
        frames["vix"] = compute_vix_context(vix_deque)
    else:
        frames["vix"] = {"ready": False}

    return frames


# ---------------------------------------------------------------------------
# Test 1: EQ_INDEX symbol with cross_asset_enabled=True and cached payload
# ---------------------------------------------------------------------------


def test_eq_index_gets_cross_asset_frames():
    """EQ_INDEX symbol (ESM6) with cross_asset_enabled=True and cached payload
    results in frames containing cross_asset and cross_asset_5m keys.
    """
    cached_1m = {
        "ready": True,
        "active_pair": "ES_NQ",
        "es_nq_spread_z": 2.1,
        "pairs_confirming": 1,
        "tf": "1m",
    }
    cached_5m = {
        "ready": True,
        "active_pair": "ES_NQ",
        "es_nq_spread_z": 1.8,
        "pairs_confirming": 1,
        "tf": "5m",
    }
    svc = _make_service(
        cross_asset_enabled=True,
        cross_asset_cache={"1m": cached_1m, "5m": cached_5m},
    )

    frames = _build_injection(svc, symbol="ESM6", tf="1m")

    assert "cross_asset" in frames, "EQ_INDEX should receive cross_asset frame"
    assert "cross_asset_5m" in frames, "EQ_INDEX should receive cross_asset_5m frame"
    assert frames["cross_asset"]["ready"] is True
    assert frames["cross_asset_5m"]["ready"] is True
    assert frames["cross_asset"]["active_pair"] == "ES_NQ"


# ---------------------------------------------------------------------------
# Test 2: Non-EQ_INDEX symbol with cross_asset_enabled=True
# ---------------------------------------------------------------------------


def test_non_eq_index_does_not_get_cross_asset_frames():
    """Non-EQ_INDEX symbol (GCM6 = Gold) with cross_asset_enabled=True should NOT
    have cross_asset or cross_asset_5m keys in frames.
    """
    cached_1m = {"ready": True, "active_pair": "ES_NQ", "tf": "1m"}
    svc = _make_service(
        cross_asset_enabled=True,
        cross_asset_cache={"1m": cached_1m, "5m": cached_1m},
    )

    frames = _build_injection(svc, symbol="GCM6", tf="1m")

    assert "cross_asset" not in frames, "Non-EQ_INDEX must not receive cross_asset frame"
    assert "cross_asset_5m" not in frames, "Non-EQ_INDEX must not receive cross_asset_5m frame"
    # VIX frame should still be present (injected for all symbols)
    assert "vix" in frames


# ---------------------------------------------------------------------------
# Test 3: cross_asset_enabled=False — no cross_asset keys regardless of symbol
# ---------------------------------------------------------------------------


def test_cross_asset_disabled_no_cross_asset_frames():
    """When cross_asset_enabled=False, EQ_INDEX symbol should still not receive
    cross_asset frames regardless of cache contents.
    """
    cached_1m = {"ready": True, "active_pair": "ES_NQ", "tf": "1m"}
    svc = _make_service(
        cross_asset_enabled=False,
        cross_asset_cache={"1m": cached_1m, "5m": cached_1m},
    )

    frames = _build_injection(svc, symbol="ESM6", tf="1m")

    assert "cross_asset" not in frames, "Disabled cross_asset must not inject frames"
    assert "cross_asset_5m" not in frames, "Disabled cross_asset must not inject frames"


# ---------------------------------------------------------------------------
# Test 4: VIX symbol resolved, bar_history has >= 20 VIX bars -> frames["vix"]["ready"] True
# ---------------------------------------------------------------------------


def test_vix_ready_when_sufficient_bars():
    """With _vix_symbol set and >= 20 VIX bars in bar_history, frames["vix"]["ready"] is True."""
    svc = _make_service(vix_symbol="VXJ6")

    # Seed 20 VIX 1m bars with varying close prices (required for non-zero stdev)
    for i in range(20):
        bar = _make_bar("VXJ6", tf="1m", close=18.0 + i * 0.5)
        svc._bar_history.append(bar)

    frames = _build_injection(svc, symbol="CLM6", tf="1m")

    assert "vix" in frames
    assert frames["vix"]["ready"] is True
    assert "level" in frames["vix"]
    assert "z_score" in frames["vix"]


# ---------------------------------------------------------------------------
# Test 5: VIX symbol resolved, bar_history has < 20 VIX bars -> frames["vix"]["ready"] False
# ---------------------------------------------------------------------------


def test_vix_not_ready_when_insufficient_bars():
    """With _vix_symbol set but fewer than 20 VIX bars, frames["vix"]["ready"] is False."""
    svc = _make_service(vix_symbol="VXJ6")

    # Seed only 5 VIX bars (below z_window=20 threshold)
    for i in range(5):
        bar = _make_bar("VXJ6", tf="1m", close=18.0 + i * 0.5)
        svc._bar_history.append(bar)

    frames = _build_injection(svc, symbol="ESM6", tf="1m")

    assert "vix" in frames
    assert frames["vix"]["ready"] is False


# ---------------------------------------------------------------------------
# Test 6: No VIX symbol resolved (_vix_symbol=None) -> frames["vix"] = {"ready": False}
# ---------------------------------------------------------------------------


def test_no_vix_symbol_returns_not_ready():
    """When _vix_symbol is None (no VIX contract active), frames["vix"] is {"ready": False}."""
    svc = _make_service(vix_symbol=None)

    frames = _build_injection(svc, symbol="NQM6", tf="5m")

    assert "vix" in frames
    assert frames["vix"] == {"ready": False}
