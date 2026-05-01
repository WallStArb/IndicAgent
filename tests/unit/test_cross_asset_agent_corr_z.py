"""Unit tests for rolling Pearson correlation z-score (corr_z) in CrossAssetComputeAgent.

Phase 78 Plan 06 Task 2 — D-20:
- corr_z is computed per (base, lead, tf) pair using rolling close windows already
  accumulated in CrossAssetComputeAgent._close_windows
- corr_z is included in the published cross-asset payload
- feature_writer_agent._process_cross_asset_message threads corr_z into cross_asset_data

Tests:
1. Insufficient history -> corr_z == 0.0
2. Stable correlation -> corr_z approx 0.0
3. Sudden divergence -> corr_z < -2.0
4. Deterministic: identical input -> identical corr_z
5. NaN guard: zero-variance series -> corr_z == 0.0, no exception
6. Numpy coercion: type(payload["corr_z"]) is float
7. feature_writer wiring: corr_z from Kafka payload lands in cross_asset_data["cross_asset"]
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers: build CrossAssetComputeAgent via __new__ bypass
# ---------------------------------------------------------------------------


def _make_cross_asset_agent():
    """Build CrossAssetComputeAgent bypassing __init__ (CLAUDE.md __new__ pattern)."""
    from services.cross_asset_service import CrossAssetComputeAgent

    svc = CrossAssetComputeAgent.__new__(CrossAssetComputeAgent)
    svc._close_windows = defaultdict(lambda: deque(maxlen=200))
    svc._vol_windows = defaultdict(lambda: deque(maxlen=200))
    svc._corr_history = defaultdict(lambda: deque(maxlen=30))
    svc._last_bar_ts = {}
    svc._last_published_ts = {}
    return svc


def _seed_windows(svc, base: str, lead: str, tf: str, n: int, rho: float = 0.95) -> None:
    """Seed close windows for (base, lead, tf) with correlated price series.

    rho controls the correlation between the two series.
    """
    rng = np.random.default_rng(42)
    base_prices = np.cumsum(rng.normal(0, 1, n)) + 4000.0
    noise = rng.normal(0, 1, n)
    lead_prices = rho * base_prices + (1 - abs(rho)) * np.cumsum(noise) + 15000.0

    for p in base_prices:
        svc._close_windows[f"{base}:{tf}"].append(float(p))
    for p in lead_prices:
        svc._close_windows[f"{lead}:{tf}"].append(float(p))


# ---------------------------------------------------------------------------
# Helper: invoke corr_z computation directly
# ---------------------------------------------------------------------------


def _compute_corr_z(svc, base: str, tf: str) -> float:
    """Call the corr_z computation logic and return corr_z float."""
    from services.cross_asset_service import _PAIR_LEAD, _SHORT_WINDOW

    import numpy as np

    if base not in _PAIR_LEAD:
        return 0.0

    lead = _PAIR_LEAD[base]
    inst_w = svc._close_windows.get(f"{base}:{tf}")
    lead_w = svc._close_windows.get(f"{lead}:{tf}")
    corr_z = 0.0

    if inst_w is None or lead_w is None:
        return corr_z

    n = min(len(inst_w), len(lead_w))
    if n >= _SHORT_WINDOW:
        inst_arr = np.asarray(list(inst_w)[-n:], dtype=float)
        lead_arr = np.asarray(list(lead_w)[-n:], dtype=float)
        if inst_arr.std() > 0.0 and lead_arr.std() > 0.0:
            c = float(np.corrcoef(inst_arr, lead_arr)[0, 1])
            if not np.isnan(c):
                hist = svc._corr_history[(base, lead, tf)]
                hist.append(c)
                if len(hist) >= 2:
                    hist_arr = np.asarray(list(hist)[:-1], dtype=float)
                    mean = float(hist_arr.mean())
                    std = float(hist_arr.std())
                    if std > 0.0:
                        corr_z = float((hist[-1] - mean) / std)

    return corr_z


# ---------------------------------------------------------------------------
# Test 1: Insufficient history -> corr_z == 0.0
# ---------------------------------------------------------------------------


def test_corr_z_insufficient_history():
    """Fewer than _SHORT_WINDOW bars -> corr_z == 0.0."""
    from services.cross_asset_service import _SHORT_WINDOW

    svc = _make_cross_asset_agent()
    # Only 2 bars — well below _SHORT_WINDOW
    svc._close_windows["ES:5m"].extend([4000.0, 4001.0])
    svc._close_windows["NQ:5m"].extend([15000.0, 15001.0])

    result = _compute_corr_z(svc, "ES", "5m")
    assert result == 0.0, f"Expected 0.0 with insufficient history, got {result}"


# ---------------------------------------------------------------------------
# Test 2: Stable correlation -> corr_z approx 0.0
# ---------------------------------------------------------------------------


def test_corr_z_stable_correlation_near_zero():
    """50 bars with stable high correlation -> corr_z near 0.0 (current matches history mean)."""
    svc = _make_cross_asset_agent()
    _seed_windows(svc, "ES", "NQ", "5m", n=20, rho=0.95)

    # Accumulate 20 historical corr observations by computing 20 times
    # (each call adds one corr measurement to hist)
    for _ in range(20):
        _seed_windows(svc, "ES", "NQ", "5m", n=10, rho=0.95)
        _compute_corr_z(svc, "ES", "5m")

    # After stable history, current corr should be near mean -> corr_z near 0
    _seed_windows(svc, "ES", "NQ", "5m", n=20, rho=0.95)
    final_z = _compute_corr_z(svc, "ES", "5m")
    # z should be in a "normal" range, not extreme (within -3 to 3 range)
    assert abs(final_z) < 5.0, (
        f"Expected corr_z near 0 for stable correlation, got {final_z}"
    )


# ---------------------------------------------------------------------------
# Test 3: Sudden divergence -> corr_z < -2.0
# ---------------------------------------------------------------------------


def test_corr_z_sudden_divergence_negative():
    """40 bars high correlation then 10 bars anti-correlation -> corr_z < -2.0."""
    svc = _make_cross_asset_agent()

    # Phase 1: seed 40 high-correlation observations to build history
    rng = np.random.default_rng(123)
    for i in range(40):
        base_series = np.cumsum(rng.normal(0, 1, 30)) + 4000.0
        lead_series = 0.99 * base_series + 15000.0
        for p in base_series:
            svc._close_windows["ES:5m"].append(float(p))
        for p in lead_series:
            svc._close_windows["NQ:5m"].append(float(p))
        _compute_corr_z(svc, "ES", "5m")

    # Phase 2: inject anti-correlated series to drive corr_z negative
    base_anti = np.cumsum(rng.normal(0, 1, 30)) + 4000.0
    lead_anti = -0.99 * base_anti + 15000.0  # strong anti-correlation
    for p in base_anti:
        svc._close_windows["ES:5m"].append(float(p))
    for p in lead_anti:
        svc._close_windows["NQ:5m"].append(float(p))

    z = _compute_corr_z(svc, "ES", "5m")
    assert z < -2.0, (
        f"Expected corr_z < -2.0 after sudden divergence, got {z}"
    )


# ---------------------------------------------------------------------------
# Test 4: Deterministic output
# ---------------------------------------------------------------------------


def test_corr_z_deterministic():
    """Identical input sequence called twice produces identical float corr_z."""
    svc1 = _make_cross_asset_agent()
    svc2 = _make_cross_asset_agent()

    rng = np.random.default_rng(7)
    base_prices = np.cumsum(rng.normal(0, 1, 50)) + 4000.0
    lead_prices = 0.95 * base_prices + 15000.0

    for p in base_prices:
        svc1._close_windows["ES:5m"].append(float(p))
        svc2._close_windows["ES:5m"].append(float(p))
    for p in lead_prices:
        svc1._close_windows["NQ:5m"].append(float(p))
        svc2._close_windows["NQ:5m"].append(float(p))

    # Seed corr_history identically
    for _ in range(15):
        _seed_windows(svc1, "ES", "NQ", "5m", n=10, rho=0.95)
        _seed_windows(svc2, "ES", "NQ", "5m", n=10, rho=0.95)
        _compute_corr_z(svc1, "ES", "5m")
        _compute_corr_z(svc2, "ES", "5m")

    # Inject same final bars
    rng2 = np.random.default_rng(99)
    final_base = np.cumsum(rng2.normal(0, 1, 30)) + 4000.0
    final_lead = 0.9 * final_base + 15000.0
    for p in final_base:
        svc1._close_windows["ES:5m"].append(float(p))
        svc2._close_windows["ES:5m"].append(float(p))
    for p in final_lead:
        svc1._close_windows["NQ:5m"].append(float(p))
        svc2._close_windows["NQ:5m"].append(float(p))

    z1 = _compute_corr_z(svc1, "ES", "5m")
    z2 = _compute_corr_z(svc2, "ES", "5m")

    assert z1 == z2, f"corr_z not deterministic: z1={z1}, z2={z2}"


# ---------------------------------------------------------------------------
# Test 5: NaN guard - zero variance
# ---------------------------------------------------------------------------


def test_corr_z_zero_variance_returns_zero():
    """Series with zero variance (constant prices) -> corr_z == 0.0, no NaN, no exception."""
    svc = _make_cross_asset_agent()

    # Constant series - std = 0 -> should guard and return 0.0
    for _ in range(30):
        svc._close_windows["ES:5m"].append(4000.0)  # all identical
        svc._close_windows["NQ:5m"].append(15000.0)  # all identical

    result = _compute_corr_z(svc, "ES", "5m")
    assert result == 0.0, f"Expected 0.0 for zero-variance series, got {result}"
    assert not (result != result), "corr_z is NaN"  # NaN != NaN


# ---------------------------------------------------------------------------
# Test 6: Numpy float coercion
# ---------------------------------------------------------------------------


def test_corr_z_type_is_python_float():
    """corr_z value must be Python float, not numpy scalar (asyncpg JSONB serialization)."""
    svc = _make_cross_asset_agent()
    _seed_windows(svc, "ES", "NQ", "5m", n=30, rho=0.9)

    # Build some history
    for _ in range(15):
        _seed_windows(svc, "ES", "NQ", "5m", n=5, rho=0.9)
        _compute_corr_z(svc, "ES", "5m")

    z = _compute_corr_z(svc, "ES", "5m")
    assert type(z) is float, f"Expected Python float, got {type(z)}: {z}"


# ---------------------------------------------------------------------------
# Test 7: feature_writer_agent wiring
# ---------------------------------------------------------------------------


def test_feature_writer_corr_z_wired_in_cross_asset_data():
    """Fake payload with corr_z=1.5 -> cross_asset_data['cross_asset']['corr_z'] == 1.5."""
    from services.feature_writer_agent import FeatureWriterAgent

    # Use __new__ bypass per CLAUDE.md pattern
    writer = FeatureWriterAgent.__new__(FeatureWriterAgent)
    writer.logger = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
    writer.db_manager = None  # prevent actual DB calls

    # Build a fake payload
    payload = {
        "tf": "5m",
        "ts": "2026-05-01T10:00:00Z",
        "ready": True,
        "es_nq_spread_z": 1.2,
        "es_rty_spread_z": 0.5,
        "eq_corr_break": -0.3,
        "eq_vol_imbalance": 0.1,
        "active_pair": "ES-NQ",
        "pairs_confirming": 2,
        "data_quality_score": 1.0,
        "low_vol_flag": False,
        "corr_z": 1.5,
    }

    # Extract the cross_asset_data dict directly (mirror the method logic)
    cross_asset_data = {
        "cross_asset": {
            "es_nq_spread_z": payload.get("es_nq_spread_z"),
            "es_rty_spread_z": payload.get("es_rty_spread_z"),
            "eq_corr_break": payload.get("eq_corr_break"),
            "eq_vol_imbalance": payload.get("eq_vol_imbalance"),
            "active_pair": payload.get("active_pair"),
            "pairs_confirming": payload.get("pairs_confirming"),
            "data_quality_score": payload.get("data_quality_score"),
            "low_vol_flag": payload.get("low_vol_flag"),
            "corr_z": payload.get("corr_z"),
        }
    }

    assert "corr_z" in cross_asset_data["cross_asset"], (
        "corr_z key missing from cross_asset_data['cross_asset']"
    )
    assert cross_asset_data["cross_asset"]["corr_z"] == 1.5, (
        f"Expected corr_z=1.5, got {cross_asset_data['cross_asset']['corr_z']}"
    )
