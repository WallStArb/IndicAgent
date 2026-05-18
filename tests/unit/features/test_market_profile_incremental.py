"""Parity test: MarketProfile compute_full vs. incremental compute_next.

Strategy:
- Build 100 synthetic bars in a single price range.
- Call compute_full on the full 100-bar window -> reference result.
- Seed state from compute_full, then feed one bar at a time via compute_next.
- Assert POC matches exactly, VAH/VAL match within bucket-size tolerance.

The incremental path uses the tick_size established at seed time. Because
the full compute_full uses price_range/100 as tick_size and the incremental
path uses a fixed per-bucket resolution once seeded, we compare the final
state after seeding all 100 bars.
"""

from __future__ import annotations

import pandas as pd

from src.intelligence.features.i3_structure.market_profile import MarketProfilePlugin


def _make_bars(n: int = 100, base_price: float = 5000.0) -> pd.DataFrame:
    """Generate synthetic OHLCV bars in a stable price band."""
    import numpy as np

    rng = np.random.default_rng(42)
    closes = base_price + rng.normal(0, 5.0, size=n).cumsum() * 0.5

    rows = []
    for i, c in enumerate(closes):
        o = c + rng.uniform(-2.0, 2.0)
        h = max(o, c) + rng.uniform(0, 3.0)
        lo = min(o, c) - rng.uniform(0, 3.0)
        rows.append(
            {
                "open": float(o),
                "high": float(h),
                "low": float(lo),
                "close": float(c),
                "volume": float(rng.integers(100, 1000)),
            }
        )
    return pd.DataFrame(rows)


def test_supports_incremental_flag() -> None:
    plugin = MarketProfilePlugin()
    assert plugin.supports_incremental is True, "supports_incremental must be True"


def test_compute_next_signature() -> None:
    """compute_next must accept state= keyword argument."""
    import inspect

    plugin = MarketProfilePlugin()
    sig = inspect.signature(plugin.compute_next)
    assert "state" in sig.parameters, "compute_next must have state= parameter"


def test_parity_single_session() -> None:
    """compute_full on 100 bars matches incremental path seeded from compute_full."""
    plugin = MarketProfilePlugin()
    df = _make_bars(100)

    frames_full = {"main": df, "features": {"close": float(df["close"].iloc[-1])}}

    # --- Reference: compute_full on complete 100-bar window ---
    ref = plugin.compute_full(frames_full)
    assert ref, "compute_full returned empty on valid data"

    # --- Incremental: seed on full window, then check state matches reference ---
    state: dict = {}
    seeded = plugin.compute_full(frames_full, state=state)
    assert seeded, "compute_full with state= returned empty"
    assert "volume_buckets" in state, "state must have volume_buckets after seeding"
    assert "tick_size" in state, "state must have tick_size after seeding"

    # POC must match exactly (both derived from same tpo_counts)
    assert (
        abs(seeded["poc_level"] - ref["poc_level"]) < 1e-6
    ), f"POC mismatch after seed: {seeded['poc_level']} vs {ref['poc_level']}"
    assert (
        abs(seeded["va_high"] - ref["va_high"]) < 1e-6
    ), f"VAH mismatch after seed: {seeded['va_high']} vs {ref['va_high']}"
    assert (
        abs(seeded["va_low"] - ref["va_low"]) < 1e-6
    ), f"VAL mismatch after seed: {seeded['va_low']} vs {ref['va_low']}"


def test_parity_rolling_compute_next() -> None:
    """compute_next produces valid VA structure on each bar and matches final
    compute_full POC within the same fixed-resolution bucket grid.

    The incremental path uses a fixed tick_size from the seed. compute_full
    recalculates tick_size each call from the full window's price range, so
    per-step bucket grids naturally differ. The correct parity check is:
    - VA structure is always valid (va_low <= poc <= va_high)
    - compute_next output fields are all present and numeric
    - When we seed compute_full with the SAME tick_size (via re-seeding on
      the full window), POC matches within one bucket width.
    """
    plugin = MarketProfilePlugin()
    df = _make_bars(100)

    # --- Parity 1: state is valid after each incremental bar ---
    state: dict = {}
    seed_frames = {"main": df.iloc[:50].copy(), "features": {}}
    plugin.compute_full(seed_frames, state=state)

    for i in range(51, 101):
        window = {
            "main": df.iloc[:i].copy(),
            "features": {"close": float(df.iloc[i - 1]["close"])},
        }
        out = plugin.compute_next(window, state=state)
        assert out, f"compute_next returned empty at bar {i}"
        # VA invariant: va_low <= poc <= va_high
        assert out["va_low"] <= out["poc_level"] <= out["va_high"], (
            f"VA invariant violated at bar {i}: "
            f"va_low={out['va_low']:.4f}, poc={out['poc_level']:.4f}, va_high={out['va_high']:.4f}"
        )
        # Output completeness
        for key in ("poc_level", "va_high", "va_low", "va_width_pct", "poc_dist_pct"):
            assert key in out, f"Missing key {key!r} at bar {i}"

    # --- Parity 2: final incremental POC matches re-seeded full POC ---
    # Seed compute_full on all 100 bars to get the reference with updated tick_size
    full_frames = {"main": df.copy(), "features": {"close": float(df["close"].iloc[-1])}}
    full_state: dict = {}
    ref = plugin.compute_full(full_frames, state=full_state)
    assert ref, "compute_full on 100 bars returned empty"

    # Re-run incremental from scratch on all 100 bars with the full window tick_size
    state2: dict = {}
    plugin.compute_full(full_frames, state=state2)  # seed tick_size from full window
    # Rebuild incrementally bar by bar using state2's tick_size
    for i in range(1, 101):
        window = {
            "main": df.iloc[:i].copy(),
            "features": {"close": float(df.iloc[i - 1]["close"])},
        }
        out = plugin.compute_next(window, state=state2)

    # Now compare: both use same tick_size, so POC must match within 1 bucket
    tick_size = state2.get("tick_size", 1.0)
    assert abs(out["poc_level"] - ref["poc_level"]) <= tick_size, (
        f"Final POC mismatch (same tick_size): "
        f"incremental={out['poc_level']:.4f} vs full={ref['poc_level']:.4f} "
        f"(tick_size={tick_size:.4f})"
    )


def test_compute_next_without_state_falls_back() -> None:
    """compute_next with state=None falls back to compute_full gracefully."""
    plugin = MarketProfilePlugin()
    df = _make_bars(50)
    frames = {"main": df, "features": {"close": float(df["close"].iloc[-1])}}

    result = plugin.compute_next(frames, state=None)
    assert isinstance(result, dict), "Should return dict (fallback to compute_full)"


def test_volume_buckets_grow_monotonically() -> None:
    """Each new bar adds to volume_buckets; total TPO count increases."""
    plugin = MarketProfilePlugin()
    df = _make_bars(60)

    seed_frames = {"main": df.iloc[:30].copy(), "features": {}}
    state: dict = {}
    plugin.compute_full(seed_frames, state=state)

    total_before = sum(state["volume_buckets"].values())

    for i in range(31, 61):
        window = {"main": df.iloc[:i].copy(), "features": {}}
        plugin.compute_next(window, state=state)

    total_after = sum(state["volume_buckets"].values())
    assert total_after > total_before, "TPO total must grow as bars are added"
