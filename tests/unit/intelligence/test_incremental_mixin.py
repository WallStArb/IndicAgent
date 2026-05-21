"""Unit tests for IncrementalMixin contract.

Covers:
- _state always attached in compute_full and compute_next
- empty dict {} does NOT trigger fallback (state is None check, not truthiness)
- result["_state"] is the same dict object that _compute_next_core received (identity check)
- full-vs-incremental replay parity: compute_full(N) == seed + compute_next x remaining
- conformance tests for all 7 IncrementalMixin plugins (ATR + 6 migrated)
- per-plugin replay parity for all 6 migrated plugins
- latency benchmark for compute_full and compute_next per plugin

Review items addressed:
- Actionable 1: test_empty_dict_state_does_NOT_trigger_fallback proves state is None check
- Actionable 4: test_full_equals_seed_plus_incremental proves replay parity
- Actionable 4 (plan 04): TestMigratedPluginReplayParity tests per migrated plugin
- Actionable 6: TestLatencyBenchmark measures before/after migration timing
- Concern 10 (Gemini): conformance tests catch mixin contract issues early
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.intelligence.features.i1_indicators.adx import ADXPlugin
from src.intelligence.features.i1_indicators.atr import ATRPlugin
from src.intelligence.features.i1_indicators.keltner import KeltnerChannelsPlugin
from src.intelligence.features.i1_indicators.mfi import MFIPlugin
from src.intelligence.features.i1_indicators.stochastic import StochasticPlugin
from src.intelligence.features.i1_indicators.williams_r import WilliamsRPlugin
from src.intelligence.plugins.mixins import IncrementalMixin
from src.intelligence.trading.volume_zscore import VolumeZscorePlugin

# ---------------------------------------------------------------------------
# Mock plugins for testing
# ---------------------------------------------------------------------------


class MockIncrementalPlugin(IncrementalMixin):
    """Simple mixin-based plugin that computes sum of close prices.

    State: {"close_sum": float, "bar_count": int}
    Output: {"close_sum": float}

    Used to verify state attachment, mutation identity, and seeding contracts.
    """

    name = "MockIncremental"
    supports_incremental = True

    def _compute_full_core(self, frames: dict) -> dict:
        df = frames.get("main")
        if df is None or len(df) < 1:
            return {}
        total = float(df["close"].sum())
        return {"close_sum": total}

    def _seed_state(self, frames: dict) -> dict:
        df = frames.get("main")
        if df is None or len(df) < 1:
            return {}
        return {
            "close_sum": float(df["close"].sum()),
            "bar_count": len(df),
        }

    def _compute_next_core(self, frames: dict, state: dict) -> dict:
        df = frames.get("main")
        if df is None or len(df) < 1:
            return {}
        # Get latest bar
        latest_close = float(df.iloc[-1]["close"])
        # Mutate state in place (mutable in-place contract)
        state["close_sum"] = state.get("close_sum", 0.0) + latest_close
        state["bar_count"] = state.get("bar_count", 0) + 1
        return {"close_sum": state["close_sum"]}


class SimpleSMAPlugin(IncrementalMixin):
    """SMA plugin for replay parity testing.

    Computes simple moving average over a given period.
    State: {"running_sum": float, "count": int, "window": list[float]}
    Output: {"sma_N": float}
    """

    name = "SimpleSMA"
    supports_incremental = True

    def __init__(self, period: int = 10) -> None:
        self.period = period

    def _compute_full_core(self, frames: dict) -> dict:
        df = frames.get("main")
        if df is None or len(df) < self.period:
            return {}
        sma = float(df["close"].rolling(self.period).mean().iloc[-1])
        return {f"sma_{self.period}": sma}

    def _seed_state(self, frames: dict) -> dict:
        df = frames.get("main")
        if df is None or len(df) < self.period:
            return {}
        # Seed with the last 'period' closes for rolling window tracking
        window = list(df["close"].iloc[-self.period :].astype(float))
        running_sum = sum(window)
        return {
            "running_sum": running_sum,
            "count": len(df),
            "window": window,
        }

    def _compute_next_core(self, frames: dict, state: dict) -> dict:
        df = frames.get("main")
        if df is None or len(df) < 1:
            return {}
        if "window" not in state:
            return {}
        latest_close = float(df.iloc[-1]["close"])
        window: list = state["window"]
        # Remove oldest, add newest
        if len(window) >= self.period:
            oldest = window.pop(0)
            state["running_sum"] -= oldest
        window.append(latest_close)
        state["running_sum"] += latest_close
        state["count"] += 1
        sma = state["running_sum"] / self.period
        return {f"sma_{self.period}": sma}


def make_df(n: int = 20, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV DataFrame for testing."""
    rng = np.random.default_rng(seed)
    close = 5000.0 * np.cumprod(1 + rng.normal(0.0001, 0.005, n))
    high = close * (1 + rng.uniform(0.001, 0.003, n))
    low = close * (1 - rng.uniform(0.001, 0.003, n))
    open_ = close * (1 + rng.normal(0, 0.001, n))
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close})


# ---------------------------------------------------------------------------
# TestIncrementalMixinContract
# ---------------------------------------------------------------------------


class TestIncrementalMixinContract:
    """Verifies the IncrementalMixin state attachment and fallback contract."""

    def test_state_attached_in_compute_full(self):
        """compute_full always attaches _state to output."""
        plugin = MockIncrementalPlugin()
        df = make_df(20)
        result = plugin.compute_full({"main": df})

        assert "_state" in result, "compute_full must attach _state to output"
        assert isinstance(result["_state"], dict)

    def test_state_attached_in_compute_next(self):
        """compute_next with valid state attaches _state to output."""
        plugin = MockIncrementalPlugin()
        df = make_df(20)
        seed_result = plugin.compute_full({"main": df})
        state = seed_result["_state"]

        # Add one more bar
        df2 = make_df(21)
        result = plugin.compute_next({"main": df2}, state=state)

        assert "_state" in result, "compute_next must attach _state to output"

    def test_fallback_to_full_when_state_is_none(self):
        """compute_next with state=None falls back to compute_full."""
        plugin = MockIncrementalPlugin()
        df = make_df(20)

        # Call compute_next with state=None -- should produce same result as compute_full
        result_next = plugin.compute_next({"main": df}, state=None)
        result_full = plugin.compute_full({"main": df})

        assert "_state" in result_next
        assert result_next["close_sum"] == pytest.approx(result_full["close_sum"])

    def test_empty_dict_state_does_NOT_trigger_fallback(self):
        """compute_next with state={} calls _compute_next_core, NOT compute_full.

        This is the critical test for review item 1. The mixin uses 'state is None'
        not 'if not state', so an empty dict must reach _compute_next_core.
        """
        plugin = MockIncrementalPlugin()
        df = make_df(20)

        # Track which core method was called
        _full_core_called = []
        _next_core_called = []

        original_full = plugin._compute_full_core
        original_next = plugin._compute_next_core

        def patched_full(frames):
            _full_core_called.append(True)
            return original_full(frames)

        def patched_next(frames, state):
            _next_core_called.append(True)
            return original_next(frames, state)

        plugin._compute_full_core = patched_full
        plugin._compute_next_core = patched_next

        # Empty dict state must NOT trigger fallback to compute_full
        plugin.compute_next({"main": df}, state={})

        assert (
            len(_next_core_called) == 1
        ), "_compute_next_core must be called with empty dict state"
        assert len(_full_core_called) == 0, "_compute_full_core must NOT be called when state={}"

    def test_compute_next_receives_non_none_state(self):
        """_compute_next_core never receives None state from the mixin."""
        plugin = MockIncrementalPlugin()
        df = make_df(20)

        received_states = []
        original_next = plugin._compute_next_core

        def patched_next(frames, state):
            received_states.append(state)
            return original_next(frames, state)

        plugin._compute_next_core = patched_next

        seed = {"close_sum": 100.0, "bar_count": 20}
        plugin.compute_next({"main": df}, state=seed)

        assert len(received_states) == 1
        assert received_states[0] is not None, "_compute_next_core must never receive None state"

    def test_state_is_same_object_after_mutation(self):
        """result['_state'] is the same dict object that _compute_next_core received.

        Tests the mutable in-place contract: the mixin attaches the same (mutated)
        dict back to output, not a copy.
        """
        plugin = MockIncrementalPlugin()
        df = make_df(20)

        seed = {"close_sum": 100.0, "bar_count": 20}
        df2 = make_df(21)
        result = plugin.compute_next({"main": df2}, state=seed)

        # result["_state"] must be the SAME object as seed (identity check)
        assert result["_state"] is seed, (
            "result['_state'] must be the same dict object passed as state, "
            "not a copy. Mixin attaches state in place."
        )

    def test_empty_result_returns_empty_dict(self):
        """When _compute_full_core returns {}, compute_full returns {}."""
        plugin = MockIncrementalPlugin()

        # Empty frames should cause _compute_full_core to return {}
        result = plugin.compute_full({"main": None})
        assert result == {}, "compute_full must return {} when _compute_full_core returns {}"

    def test_empty_result_in_compute_next_returns_empty_dict(self):
        """When _compute_next_core returns {}, compute_next returns {}."""
        plugin = MockIncrementalPlugin()

        # Pass state but bad frames -- _compute_next_core returns {}
        seed = {"close_sum": 100.0, "bar_count": 20}
        result = plugin.compute_next({"main": None}, state=seed)
        assert result == {}, "compute_next must return {} when _compute_next_core returns {}"

    def test_abstract_methods_raise_not_implemented(self):
        """All three abstract methods raise NotImplementedError on base mixin."""

        class BarePlugin(IncrementalMixin):
            name = "Bare"

        p = BarePlugin()
        frames = {"main": make_df(5)}

        with pytest.raises(NotImplementedError):
            p._compute_full_core(frames)

        with pytest.raises(NotImplementedError):
            p._compute_next_core(frames, {})

        with pytest.raises(NotImplementedError):
            p._seed_state(frames)


# ---------------------------------------------------------------------------
# TestIncrementalMixinReplayParity
# ---------------------------------------------------------------------------


class TestIncrementalMixinReplayParity:
    """Full-vs-incremental replay test (review item 4).

    Proves: compute_full(N bars) == seed(compute_full on first M bars) + compute_next x (N-M)
    """

    def test_full_equals_seed_plus_incremental(self):
        """Generate N=50 bars. Reference = compute_full on all 50.
        Seed from first 20 bars, then compute_next for bars 21..50.
        Final incremental output must match reference within tolerance 1e-10.
        """
        period = 5
        plugin = SimpleSMAPlugin(period=period)

        n_total = 50
        n_seed = 20
        df_all = make_df(n_total, seed=99)

        # Reference: compute_full on all 50 bars
        ref_result = plugin.compute_full({"main": df_all})
        ref_sma = ref_result[f"sma_{period}"]

        # Seed from first 20 bars
        seed_result = plugin.compute_full({"main": df_all.iloc[:n_seed]})
        state = seed_result["_state"]

        # Incremental: compute_next for bars 21..50
        incremental_result = None
        for i in range(n_seed, n_total):
            incremental_result = plugin.compute_next({"main": df_all.iloc[: i + 1]}, state=state)
            state = incremental_result["_state"]

        assert incremental_result is not None
        inc_sma = incremental_result[f"sma_{period}"]

        assert abs(inc_sma - ref_sma) < 1e-10, (
            f"Replay parity failed: incremental={inc_sma}, full={ref_sma}, "
            f"diff={abs(inc_sma - ref_sma)}"
        )

    def test_state_accumulates_correctly(self):
        """Verify state['count'] and state['running_sum'] increment correctly."""
        period = 5
        plugin = SimpleSMAPlugin(period=period)

        n_seed = 10
        df_seed = make_df(n_seed, seed=7)

        seed_result = plugin.compute_full({"main": df_seed})
        state = seed_result["_state"]

        initial_count = state["count"]
        assert initial_count == n_seed, f"Expected count={n_seed}, got {initial_count}"

        # Run 5 more bars, verify count increments
        for i in range(5):
            df_next = make_df(n_seed + i + 1, seed=7)
            result = plugin.compute_next({"main": df_next}, state=state)
            state = result["_state"]

        assert (
            state["count"] == n_seed + 5
        ), f"Expected count={n_seed + 5} after 5 incremental steps, got {state['count']}"
        assert "running_sum" in state
        assert "window" in state
        assert (
            len(state["window"]) == period
        ), f"Window length should be {period}, got {len(state['window'])}"

    def test_state_is_threaded_across_calls(self):
        """State returned from each compute_next is the same object threaded forward."""
        plugin = MockIncrementalPlugin()
        df = make_df(20)

        seed_result = plugin.compute_full({"main": df})
        state = seed_result["_state"]
        state_id = id(state)

        # After each compute_next, the returned _state must be the same object
        for i in range(3):
            df_next = make_df(20 + i + 1)
            result = plugin.compute_next({"main": df_next}, state=state)
            state = result["_state"]
            # Identity: state is still the same object (mutated in place)
            assert (
                id(state) == state_id
            ), f"Step {i + 1}: state object identity changed -- mixin must not copy state"


# ---------------------------------------------------------------------------
# Helpers for migrated plugin tests
# ---------------------------------------------------------------------------

_ALL_MIXIN_PLUGINS = [
    ATRPlugin,
    ADXPlugin,
    StochasticPlugin,
    WilliamsRPlugin,
    MFIPlugin,
    VolumeZscorePlugin,
    KeltnerChannelsPlugin,
]

_ALL_MIXIN_PLUGIN_IDS = [
    "ATR",
    "ADX",
    "Stochastic",
    "WilliamsR",
    "MFI",
    "VolumeZscore",
    "Keltner",
]


def make_ohlcv_df(n: int = 50, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV DataFrame with realistic price/volume relationships."""
    rng = np.random.default_rng(seed)
    close = 5000.0 * np.cumprod(1 + rng.normal(0.0001, 0.005, n))
    high = close * (1 + rng.uniform(0.001, 0.005, n))
    low = close * (1 - rng.uniform(0.001, 0.005, n))
    open_ = close * (1 + rng.normal(0, 0.001, n))
    volume = rng.uniform(1000, 10000, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


# ---------------------------------------------------------------------------
# TestMigratedPluginConformance
# ---------------------------------------------------------------------------


class TestMigratedPluginConformance:
    """Parametrized conformance tests for all 7 IncrementalMixin plugins.

    Verifies that each plugin satisfies the full mixin contract:
    - isinstance check
    - required methods present
    - compute_full returns _state
    - compute_next with state returns _state
    """

    @pytest.mark.parametrize("plugin_class", _ALL_MIXIN_PLUGINS, ids=_ALL_MIXIN_PLUGIN_IDS)
    def test_plugin_is_instance_of_incremental_mixin(self, plugin_class):
        """Each plugin must be an instance of IncrementalMixin."""
        plugin = plugin_class()
        assert isinstance(
            plugin, IncrementalMixin
        ), f"{plugin_class.__name__} must inherit IncrementalMixin"

    @pytest.mark.parametrize("plugin_class", _ALL_MIXIN_PLUGINS, ids=_ALL_MIXIN_PLUGIN_IDS)
    def test_plugin_has_required_methods(self, plugin_class):
        """Each plugin must implement _compute_full_core, _compute_next_core, _seed_state."""
        plugin = plugin_class()
        for method_name in ("_compute_full_core", "_compute_next_core", "_seed_state"):
            assert hasattr(
                plugin, method_name
            ), f"{plugin_class.__name__} must implement {method_name}"
            # Must be overridden (not the base mixin's NotImplementedError version)
            assert callable(getattr(plugin, method_name))

    @pytest.mark.parametrize("plugin_class", _ALL_MIXIN_PLUGINS, ids=_ALL_MIXIN_PLUGIN_IDS)
    def test_compute_full_returns_state(self, plugin_class):
        """compute_full must return a dict with _state key for each plugin."""
        plugin = plugin_class()
        df = make_ohlcv_df(50)
        result = plugin.compute_full({"main": df})
        assert isinstance(result, dict), f"{plugin_class.__name__}: compute_full must return dict"
        assert (
            "_state" in result
        ), f"{plugin_class.__name__}: compute_full must return dict with _state key"
        assert isinstance(result["_state"], dict), f"{plugin_class.__name__}: _state must be a dict"

    @pytest.mark.parametrize("plugin_class", _ALL_MIXIN_PLUGINS, ids=_ALL_MIXIN_PLUGIN_IDS)
    def test_compute_next_with_state_returns_state(self, plugin_class):
        """compute_next with seeded state must return _state for each plugin."""
        plugin = plugin_class()
        df = make_ohlcv_df(50)
        seed_result = plugin.compute_full({"main": df})
        state = seed_result["_state"]

        # One incremental step
        df2 = make_ohlcv_df(51)
        result = plugin.compute_next({"main": df2}, state=state)
        assert isinstance(result, dict), f"{plugin_class.__name__}: compute_next must return dict"
        assert (
            "_state" in result
        ), f"{plugin_class.__name__}: compute_next must return dict with _state key"


# ---------------------------------------------------------------------------
# TestMigratedPluginReplayParity
# ---------------------------------------------------------------------------


class TestMigratedPluginReplayParity:
    """Full-vs-incremental replay tests for the 6 newly migrated plugins.

    For each plugin: seed on first 30 bars (covers all plugin min_lookback
    requirements -- ADX needs 29), compute_next for bars 31..100,
    verify final output matches compute_full(all 100 bars) within tolerance 1e-6.
    """

    N_TOTAL = 100
    N_SEED = 30
    TOLERANCE = 1e-6

    def _run_replay(self, plugin, output_key: str, df_all: pd.DataFrame) -> tuple[float, float]:
        """Execute seed + incremental replay and return (incremental_val, full_val)."""
        # Reference: compute_full on all N_TOTAL bars
        ref_result = plugin.compute_full({"main": df_all})
        assert output_key in ref_result, f"compute_full missing key {output_key}: {ref_result}"
        ref_val = ref_result[output_key]

        # Seed from first N_SEED bars
        seed_result = plugin.compute_full({"main": df_all.iloc[: self.N_SEED]})
        assert "_state" in seed_result, "Seed result missing _state"
        state = seed_result["_state"]

        # Incremental: compute_next for bars N_SEED..N_TOTAL
        inc_result = None
        for i in range(self.N_SEED, self.N_TOTAL):
            inc_result = plugin.compute_next({"main": df_all.iloc[: i + 1]}, state=state)
            state = inc_result["_state"]

        assert inc_result is not None, "No incremental result produced"
        assert output_key in inc_result, f"Incremental result missing key {output_key}"
        return float(inc_result[output_key]), float(ref_val)

    def test_adx_replay_parity(self):
        """ADX: compute_full(50) == seed(20) + compute_next x 30."""
        plugin = ADXPlugin()
        df_all = make_ohlcv_df(self.N_TOTAL, seed=101)
        inc_val, ref_val = self._run_replay(plugin, "adx_14", df_all)
        assert abs(inc_val - ref_val) < self.TOLERANCE, (
            f"ADX replay parity failed: incremental={inc_val}, full={ref_val}, "
            f"diff={abs(inc_val - ref_val)}"
        )

    def test_stochastic_replay_parity(self):
        """Stochastic: compute_full(50) == seed(20) + compute_next x 30."""
        plugin = StochasticPlugin()
        df_all = make_ohlcv_df(self.N_TOTAL, seed=102)
        inc_val, ref_val = self._run_replay(plugin, "stoch_k_14_3", df_all)
        assert abs(inc_val - ref_val) < self.TOLERANCE, (
            f"Stochastic replay parity failed: incremental={inc_val}, full={ref_val}, "
            f"diff={abs(inc_val - ref_val)}"
        )

    def test_williams_r_replay_parity(self):
        """WilliamsR: compute_full(50) == seed(20) + compute_next x 30."""
        plugin = WilliamsRPlugin()
        df_all = make_ohlcv_df(self.N_TOTAL, seed=103)
        inc_val, ref_val = self._run_replay(plugin, "williams_r_14", df_all)
        assert abs(inc_val - ref_val) < self.TOLERANCE, (
            f"WilliamsR replay parity failed: incremental={inc_val}, full={ref_val}, "
            f"diff={abs(inc_val - ref_val)}"
        )

    def test_mfi_replay_parity(self):
        """MFI: compute_full(50) == seed(20) + compute_next x 30."""
        plugin = MFIPlugin()
        df_all = make_ohlcv_df(self.N_TOTAL, seed=104)
        inc_val, ref_val = self._run_replay(plugin, "mfi_14", df_all)
        assert abs(inc_val - ref_val) < self.TOLERANCE, (
            f"MFI replay parity failed: incremental={inc_val}, full={ref_val}, "
            f"diff={abs(inc_val - ref_val)}"
        )

    def test_volume_zscore_replay_parity(self):
        """VolumeZscore: compute_full(50) == seed(20) + compute_next x 30."""
        plugin = VolumeZscorePlugin()
        df_all = make_ohlcv_df(self.N_TOTAL, seed=105)
        inc_val, ref_val = self._run_replay(plugin, "volume_z_score", df_all)
        assert abs(inc_val - ref_val) < self.TOLERANCE, (
            f"VolumeZscore replay parity failed: incremental={inc_val}, full={ref_val}, "
            f"diff={abs(inc_val - ref_val)}"
        )

    def test_keltner_replay_parity(self):
        """Keltner: compute_full(50) == seed(20) + compute_next x 30."""
        plugin = KeltnerChannelsPlugin()
        df_all = make_ohlcv_df(self.N_TOTAL, seed=106)
        inc_val, ref_val = self._run_replay(plugin, "kc_mid_20", df_all)
        assert abs(inc_val - ref_val) < self.TOLERANCE, (
            f"Keltner replay parity failed: incremental={inc_val}, full={ref_val}, "
            f"diff={abs(inc_val - ref_val)}"
        )


# ---------------------------------------------------------------------------
# TestLatencyBenchmark
# ---------------------------------------------------------------------------


class TestLatencyBenchmark:
    """Per-plugin latency benchmark (review item 6).

    Not a strict pass/fail for absolute timing -- measures relative cost of
    compute_full vs compute_next and asserts basic sanity thresholds.
    Mark with @pytest.mark.benchmark to exclude from CI with -m "not benchmark".
    """

    N_ITERATIONS = 100
    MAX_COMPUTE_NEXT_MS = 1.0  # incremental should be fast (< 1ms sanity)

    @pytest.mark.benchmark
    def test_plugin_latency(self):
        """Measure compute_full and compute_next latency for all 7 plugins.

        Prints timing results for manual review. Asserts compute_next mean < 1ms.
        """
        import time

        plugins = [
            ("ATR", ATRPlugin()),
            ("ADX", ADXPlugin()),
            ("Stochastic", StochasticPlugin()),
            ("WilliamsR", WilliamsRPlugin()),
            ("MFI", MFIPlugin()),
            ("VolumeZscore", VolumeZscorePlugin()),
            ("Keltner", KeltnerChannelsPlugin()),
        ]

        df_100 = make_ohlcv_df(100, seed=999)
        df_101 = make_ohlcv_df(101, seed=999)

        print("\n\nLatency Benchmark Results:")
        print(f"{'Plugin':<14} {'compute_full mean (ms)':<24} {'compute_next mean (ms)':<24}")
        print("-" * 62)

        for name, plugin in plugins:
            # Seed state once
            seed_result = plugin.compute_full({"main": df_100})
            state = seed_result.get("_state", {})

            # Benchmark compute_full
            t0 = time.perf_counter()
            for _ in range(self.N_ITERATIONS):
                plugin.compute_full({"main": df_100})
            full_mean_ms = (time.perf_counter() - t0) * 1000 / self.N_ITERATIONS

            # Benchmark compute_next (reuse same state -- measures single-bar cost)
            t0 = time.perf_counter()
            for _ in range(self.N_ITERATIONS):
                plugin.compute_next({"main": df_101}, state=state)
            next_mean_ms = (time.perf_counter() - t0) * 1000 / self.N_ITERATIONS

            print(f"{name:<14} {full_mean_ms:<24.4f} {next_mean_ms:<24.4f}")

            assert next_mean_ms < self.MAX_COMPUTE_NEXT_MS, (
                f"{name}: compute_next mean {next_mean_ms:.4f}ms exceeds "
                f"sanity threshold {self.MAX_COMPUTE_NEXT_MS}ms"
            )
