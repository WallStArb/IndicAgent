"""Tests for the canonical per-bar dispatch helper ``incremental_compute``.

This helper is the batch/replay counterpart of ``executor._timed_plugin_call``
(executor.py:152-168). It gates ``compute_next`` vs ``compute_full`` on
``supports_incremental`` and a truthy ``state``. The replay (and any other
batch path) relies on it to (a) seed state on the first bar via ``compute_full``
and (b) switch to incremental ``compute_next`` thereafter, persisting
``result["_state"]`` between calls.

Covered:
- Branch selection: incremental plugin uses compute_next once seeded; full-recompute
  plugin always uses compute_full.
- State seeding: empty state -> compute_full; persisted ``_state`` -> compute_next.
- End-to-end numerical equivalence through the helper: per-bar incremental output
  equals ``compute_full`` on the same sliding window (the mixin_equivalence
  contract, exercised through the dispatch path the replay uses).
- PERF-03 ``_state`` contract: an incremental plugin returning a non-empty result
  without ``_state`` raises ``ValueError`` (loud crash over silent state loss).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.intelligence.features.i1_indicators.historical_volatility import (
    HistoricalVolatilityPlugin,
)
from src.intelligence.plugins.mixins import incremental_compute


def _make_ohlcv(n: int = 60, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0001, 0.005, n)
    close = 5000.0 * np.cumprod(1 + returns)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "close": close,
            "volume": rng.lognormal(10, 0.5, n).astype(float),
        }
    )


class _RecordingIncremental(HistoricalVolatilityPlugin):
    """Records which dispatch branch the helper selected."""

    def __init__(self) -> None:
        super().__init__()
        self.full_calls = 0
        self.next_calls = 0

    def compute_full(self, frames, *, state=None):  # type: ignore[override]
        self.full_calls += 1
        return super().compute_full(frames)

    def compute_next(self, frames, *, state=None):  # type: ignore[override]
        self.next_calls += 1
        return super().compute_next(frames, state=state)


class _FullRecomputePlugin:
    """Non-incremental plugin: always takes the compute_full branch."""

    supports_incremental: bool = False
    name = "full_recompute_fake"

    def __init__(self) -> None:
        self.full_calls = 0

    def compute_full(self, frames, *, state=None):  # noqa: D401
        self.full_calls += 1
        return {"out": 1.0}

    def compute_next(self, frames, *, state=None):  # pragma: no cover - never called
        raise AssertionError("non-incremental plugin must not reach compute_next")


class _BrokenIncrementalPlugin:
    """Incremental plugin that violates the _state contract on incremental path."""

    supports_incremental: bool = True
    name = "broken_incremental_fake"

    def compute_full(self, frames, *, state=None):
        return {"out": 1.0, "_state": {"seeded": True}}

    def compute_next(self, frames, *, state=None):
        # Non-empty result WITHOUT _state -> contract violation.
        return {"out": 2.0}


class TestIncrementalComputeDispatch:
    def test_empty_state_takes_full_branch(self):
        plugin = _RecordingIncremental()
        out = incremental_compute(plugin, {"main": _make_ohlcv()}, state={})
        assert plugin.full_calls == 1
        assert plugin.next_calls == 0
        assert "_state" in out  # seeding attaches state for the caller to persist

    def test_seeded_state_takes_next_branch(self):
        plugin = _RecordingIncremental()
        frames = {"main": _make_ohlcv()}
        # Seed on the first bar.
        seeded = incremental_compute(plugin, frames, state={})
        state = seeded["_state"]
        assert state, "seeded state must be non-empty for an incremental plugin"
        # Second bar with persisted state -> incremental branch.
        incremental_compute(plugin, frames, state=state)
        assert plugin.full_calls == 1
        assert plugin.next_calls == 1

    def test_full_recompute_plugin_never_uses_next(self):
        plugin = _FullRecomputePlugin()
        # Even with a populated state, a non-incremental plugin uses compute_full.
        out = incremental_compute(plugin, {"main": _make_ohlcv()}, state={"x": 1})
        assert plugin.full_calls == 1
        assert out == {"out": 1.0}

    def test_replay_loop_equivalence_incremental_matches_full(self):
        """The replay's seed-then-incremental loop must match per-window compute_full."""
        plugin = HistoricalVolatilityPlugin()
        full_plugin = HistoricalVolatilityPlugin()
        bars = _make_ohlcv(80)
        window = 50  # fixed sliding window, like the replay's capped deque
        state: dict = {}
        for end in range(window, len(bars) + 1):
            frames = {"main": bars.iloc[end - window : end]}
            out = incremental_compute(plugin, frames, state=state)
            state = out.get("_state", state)  # caller write-back, as the replay does
            reference = full_plugin.compute_full(frames)["hv_20"]
            assert (
                out["hv_20"] == reference
            ), f"incremental dispatch diverged from full at window end={end}"

    def test_broken_incremental_raises_state_contract_error(self):
        plugin = _BrokenIncrementalPlugin()
        # Seed first (compute_full returns valid _state).
        seeded = incremental_compute(plugin, {"main": _make_ohlcv()}, state={})
        state = seeded["_state"]
        # Incremental call returns non-empty result without _state -> loud crash.
        try:
            incremental_compute(plugin, {"main": _make_ohlcv()}, state=state)
        except ValueError as error:
            assert "_state" in str(error)
        else:
            raise AssertionError("expected ValueError for missing _state on incremental result")
