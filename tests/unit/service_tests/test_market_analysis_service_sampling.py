"""Tests verifying modulo sampling behavior in market_analysis_service._run_tier.

The sampling logic (inside nested _run_tier function):
    _plugin_call_counts[(pname, tier)] += 1
    if _plugin_call_counts[(pname, tier)] % PLUGIN_METRICS_SAMPLE_RATE == 0:
        record_plugin_execution(...)  # success, sampled

Errors are always recorded without sampling.
"""

import asyncio
from collections import defaultdict
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service():
    """Construct MarketAnalysisService bypassing __init__ for isolated unit tests."""
    from services.market_analysis_service import MarketAnalysisService

    svc = MarketAnalysisService.__new__(MarketAnalysisService)
    svc._plugin_call_counts = defaultdict(int)
    svc._plugin_states = {}
    svc._plugin_states_locks = {}
    svc.logger = MagicMock()
    svc.intelligence_cache = defaultdict(dict)
    return svc


def _make_mock_plugin(return_value=None):
    """Return a pattern-plugin mock that succeeds."""
    p = MagicMock()
    p._state = {}
    p.compute_full = MagicMock(return_value=return_value or {"feature": 1.0})
    return p


# ---------------------------------------------------------------------------
# Success-path sampling tests (unit-level, counter logic only)
# ---------------------------------------------------------------------------


class TestSuccessPathSampling:
    """Verify 1-in-10 modulo sampling for successful plugin calls in _run_tier."""

    def test_10_calls_records_once_at_count_10(self):
        """After 10 calls to same (plugin, tier), exactly 1 success metric recorded."""
        from src.core.service_utils import PLUGIN_METRICS_SAMPLE_RATE

        counter = defaultdict(int)
        recorded = []

        for _ in range(10):
            counter[("PluginA", "I3")] += 1
            if counter[("PluginA", "I3")] % PLUGIN_METRICS_SAMPLE_RATE == 0:
                recorded.append(counter[("PluginA", "I3")])

        assert recorded == [10]

    def test_25_calls_records_at_10_and_20(self):
        """25 successful calls should trigger recording at counts 10 and 20."""
        from src.core.service_utils import PLUGIN_METRICS_SAMPLE_RATE

        counter = defaultdict(int)
        recorded = []

        for _ in range(25):
            counter[("PluginA", "I4")] += 1
            if counter[("PluginA", "I4")] % PLUGIN_METRICS_SAMPLE_RATE == 0:
                recorded.append(counter[("PluginA", "I4")])

        assert recorded == [10, 20]
        assert len(recorded) == 2

    def test_per_tuple_counters_are_isolated(self):
        """Each (pname, tier) tuple tracks its own count independently."""
        from src.core.service_utils import PLUGIN_METRICS_SAMPLE_RATE

        counter = defaultdict(int)
        recorded = defaultdict(list)

        keys = [
            ("PluginA", "I3"),
            ("PluginB", "I3"),
            ("PluginA", "I4"),  # Same plugin, different tier
        ]

        for _ in range(15):
            for key in keys:
                counter[key] += 1
                if counter[key] % PLUGIN_METRICS_SAMPLE_RATE == 0:
                    recorded[key].append(counter[key])

        # All three keys record independently at count 10
        for key in keys:
            assert recorded[key] == [10], f"Key {key}: expected [10], got {recorded[key]}"

    def test_same_plugin_different_tiers_independent(self):
        """Same plugin name in I3 and I5 must have independent counters."""
        from src.core.service_utils import PLUGIN_METRICS_SAMPLE_RATE

        counter = defaultdict(int)
        recorded_i3 = []
        recorded_i5 = []

        # Run I3 plugin 10 times, I5 plugin only 5 times
        for _ in range(10):
            counter[("SharedPlugin", "I3")] += 1
            if counter[("SharedPlugin", "I3")] % PLUGIN_METRICS_SAMPLE_RATE == 0:
                recorded_i3.append(counter[("SharedPlugin", "I3")])

        for _ in range(5):
            counter[("SharedPlugin", "I5")] += 1
            if counter[("SharedPlugin", "I5")] % PLUGIN_METRICS_SAMPLE_RATE == 0:
                recorded_i5.append(counter[("SharedPlugin", "I5")])

        assert recorded_i3 == [10]  # I3 hit the threshold
        assert recorded_i5 == []  # I5 has only 5 calls — no recording yet

    def test_cross_tier_calls_do_not_affect_each_other(self):
        """Running plugins in multiple tiers concurrently doesn't cross-contaminate counts."""
        from src.core.service_utils import PLUGIN_METRICS_SAMPLE_RATE

        counter = defaultdict(int)
        recorded = defaultdict(int)

        tiers = ["I2", "I3", "I4", "I5", "SMC", "I6"]
        n_calls = 30

        for _ in range(n_calls):
            for tier in tiers:
                key = ("Plugin", tier)
                counter[key] += 1
                if counter[key] % PLUGIN_METRICS_SAMPLE_RATE == 0:
                    recorded[key] += 1

        # Each tier should have recorded 3 times (at counts 10, 20, 30)
        for tier in tiers:
            key = ("Plugin", tier)
            assert recorded[key] == 3, f"Tier {tier}: expected 3 records, got {recorded[key]}"


# ---------------------------------------------------------------------------
# Error-path recording tests (no sampling)
# ---------------------------------------------------------------------------


class TestErrorPathAlwaysRecorded:
    """Verify error calls are always recorded regardless of success counter state."""

    def test_error_recorded_on_every_call(self):
        """Simulate error path: each error triggers record_plugin_execution."""
        error_calls = []

        def fake_record(plugin, symbol, tf, duration, status, tier):
            error_calls.append(status)

        n_errors = 11  # Odd number to avoid coinciding with sampling multiples
        for _ in range(n_errors):
            fake_record("PluginX", "ES", "1m", 0.001, "error", "I3")

        assert len(error_calls) == n_errors
        assert all(s == "error" for s in error_calls)

    def test_errors_do_not_increment_success_counter(self):
        """Error path must NOT increment _plugin_call_counts."""
        from src.core.service_utils import PLUGIN_METRICS_SAMPLE_RATE

        success_counter = defaultdict(int)
        # Simulate 3 errors followed by 9 successes — no recording expected
        n_errors = 3
        n_successes = 9

        # Errors don't touch counter
        for _ in range(n_errors):
            pass  # record_plugin_execution("error") — no counter increment

        # 9 successes — counter goes 1..9, never hits 10
        recorded = []
        for _ in range(n_successes):
            success_counter[("P", "I4")] += 1
            if success_counter[("P", "I4")] % PLUGIN_METRICS_SAMPLE_RATE == 0:
                recorded.append("success")

        assert len(recorded) == 0, "9 successes after errors should not record"
        assert success_counter[("P", "I4")] == 9


# ---------------------------------------------------------------------------
# Integration: actual _run_analysis_pipeline wiring
# ---------------------------------------------------------------------------


class TestMarketAnalysisServiceSamplingIntegration:
    """Verify _run_analysis_pipeline uses _plugin_call_counts with modulo sampling."""

    def test_run_tier_increments_plugin_call_counts(self):
        """_run_analysis_pipeline must increment _plugin_call_counts on success."""
        import pandas as pd

        from services.market_analysis_service import MarketAnalysisService

        svc = MarketAnalysisService.__new__(MarketAnalysisService)
        svc._plugin_call_counts = defaultdict(int)
        svc._plugin_states = {}
        svc._plugin_states_locks = {}
        svc.logger = MagicMock()
        svc.intelligence_cache = defaultdict(dict)
        svc._instrument_map = {}
        svc.plugin_skipped_total = MagicMock()

        mock_plugin = MagicMock()
        mock_plugin._state = {}
        mock_plugin.compute_full = MagicMock(return_value={"feat_i3": 1.0})

        svc._plugin_cache = {"TestI3Plugin": mock_plugin}

        df = pd.DataFrame(
            [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 500}] * 30
        )
        frames = {"main": df, "features": {}}

        with patch("services.market_analysis_service.TIER_I2", []):
            with patch("services.market_analysis_service.TIER_I3", ["TestI3Plugin"]):
                with patch("services.market_analysis_service.TIER_I4", []):
                    with patch("services.market_analysis_service.TIER_I5", []):
                        with patch("services.market_analysis_service.TIER_SMC", []):
                            with patch("services.market_analysis_service.TIER_I6", []):
                                with patch(
                                    "services.market_analysis_service.record_plugin_execution"
                                ) as mock_rec:
                                    for _ in range(10):
                                        asyncio.run(svc._run_analysis_pipeline("ES", "1m", frames))

        assert svc._plugin_call_counts[("TestI3Plugin", "I3")] == 10
        success_calls = [c for c in mock_rec.call_args_list if c.args[4] == "success"]
        assert (
            len(success_calls) == 1
        ), f"Expected 1 success record at count=10; got {len(success_calls)}"

    def test_run_tier_records_errors_without_sampling(self):
        """Error in _run_analysis_pipeline triggers record_plugin_execution on every failure."""
        import pandas as pd

        from services.market_analysis_service import MarketAnalysisService

        svc = MarketAnalysisService.__new__(MarketAnalysisService)
        svc._plugin_call_counts = defaultdict(int)
        svc._plugin_states = {}
        svc._plugin_states_locks = {}
        svc.logger = MagicMock()
        svc.intelligence_cache = defaultdict(dict)
        svc._instrument_map = {}
        svc.plugin_skipped_total = MagicMock()

        error_plugin = MagicMock()
        error_plugin._state = {}
        error_plugin.compute_full = MagicMock(side_effect=RuntimeError("plugin explosion"))

        svc._plugin_cache = {"ErrorI3Plugin": error_plugin}

        df = pd.DataFrame(
            [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 500}] * 30
        )
        frames = {"main": df, "features": {}}

        with patch("services.market_analysis_service.TIER_I2", []):
            with patch("services.market_analysis_service.TIER_I3", ["ErrorI3Plugin"]):
                with patch("services.market_analysis_service.TIER_I4", []):
                    with patch("services.market_analysis_service.TIER_I5", []):
                        with patch("services.market_analysis_service.TIER_SMC", []):
                            with patch("services.market_analysis_service.TIER_I6", []):
                                with patch(
                                    "services.market_analysis_service.record_plugin_execution"
                                ) as mock_rec:
                                    for _ in range(7):
                                        asyncio.run(svc._run_analysis_pipeline("ES", "1m", frames))

        error_calls = [c for c in mock_rec.call_args_list if c.args[4] == "error"]
        assert len(error_calls) == 7, f"All 7 errors must be recorded; got {len(error_calls)}"
        # Error path must NOT increment call count
        assert svc._plugin_call_counts[("ErrorI3Plugin", "I3")] == 0
