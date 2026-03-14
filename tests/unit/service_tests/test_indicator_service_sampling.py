"""Tests verifying modulo sampling behavior in indicator_service._run_i1_plugins.

The sampling logic:
    _i1_call_counts[(plugin_name, tier)] += 1
    if _i1_call_counts[(plugin_name, tier)] % PLUGIN_METRICS_SAMPLE_RATE == 0:
        record_plugin_execution(...)  # success, sampled

Errors are always recorded without sampling.
"""

from collections import defaultdict
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service():
    """Construct IndicatorService bypassing __init__ for isolated unit tests."""
    from services.indicator_service import IndicatorService

    svc = IndicatorService.__new__(IndicatorService)
    svc._i1_call_counts = defaultdict(int)
    svc.logger = MagicMock()
    return svc


def _make_mock_plugin(return_value=None):
    """Return a plugin mock that succeeds and returns a feature dict."""
    p = MagicMock()
    p._state = {}
    p.compute_full = MagicMock(return_value=return_value or {"feat": 1.0})
    return p


# ---------------------------------------------------------------------------
# Success-path sampling tests
# ---------------------------------------------------------------------------


class TestSuccessPathSampling:
    """Verify 1-in-10 modulo sampling for successful plugin calls."""

    def test_exactly_10_calls_records_once(self):
        """After 10 calls to the same plugin, exactly 1 success metric is recorded."""
        from src.core.service_utils import PLUGIN_METRICS_SAMPLE_RATE

        assert PLUGIN_METRICS_SAMPLE_RATE == 10

        recorded = []
        counter = defaultdict(int)

        def sampling_loop(n_calls):
            for _ in range(n_calls):
                counter[("PluginA", "I1")] += 1
                if counter[("PluginA", "I1")] % PLUGIN_METRICS_SAMPLE_RATE == 0:
                    recorded.append(counter[("PluginA", "I1")])

        sampling_loop(10)
        assert recorded == [10], f"Expected [10], got {recorded}"

    def test_25_calls_records_at_10_and_20(self):
        """25 successful calls should record at counts 10 and 20 (not at 25)."""
        from src.core.service_utils import PLUGIN_METRICS_SAMPLE_RATE

        recorded = []
        counter = defaultdict(int)

        for _ in range(25):
            counter[("PluginA", "I1")] += 1
            if counter[("PluginA", "I1")] % PLUGIN_METRICS_SAMPLE_RATE == 0:
                recorded.append(counter[("PluginA", "I1")])

        assert recorded == [10, 20], f"Expected [10, 20], got {recorded}"
        assert len(recorded) == 2

    def test_sampling_skips_between_multiples(self):
        """Calls between multiples of SAMPLE_RATE are NOT recorded."""
        from src.core.service_utils import PLUGIN_METRICS_SAMPLE_RATE

        recorded_counts = []
        counter = defaultdict(int)

        for _ in range(PLUGIN_METRICS_SAMPLE_RATE * 3):
            counter[("P", "I1")] += 1
            cnt = counter[("P", "I1")]
            if cnt % PLUGIN_METRICS_SAMPLE_RATE == 0:
                recorded_counts.append(cnt)

        # Only multiples of SAMPLE_RATE are recorded
        assert all(c % PLUGIN_METRICS_SAMPLE_RATE == 0 for c in recorded_counts)
        assert len(recorded_counts) == 3

    def test_per_plugin_counters_are_independent(self):
        """Each (plugin, tier) pair has its own counter — one does not affect another."""
        from src.core.service_utils import PLUGIN_METRICS_SAMPLE_RATE

        counter = defaultdict(int)
        recorded = defaultdict(list)

        plugin_keys = [("PluginA", "I1"), ("PluginB", "I1"), ("PluginC", "I1")]

        for _ in range(25):
            for key in plugin_keys:
                counter[key] += 1
                if counter[key] % PLUGIN_METRICS_SAMPLE_RATE == 0:
                    recorded[key].append(counter[key])

        # Each plugin independently records at 10 and 20
        for key in plugin_keys:
            assert recorded[key] == [
                10,
                20,
            ], f"Plugin {key}: expected [10, 20], got {recorded[key]}"

    def test_first_call_never_records(self):
        """The very first call (count=1) should NOT trigger a metric record."""
        from src.core.service_utils import PLUGIN_METRICS_SAMPLE_RATE

        counter = defaultdict(int)
        counter[("P", "I1")] += 1  # first call
        assert counter[("P", "I1")] % PLUGIN_METRICS_SAMPLE_RATE != 0


# ---------------------------------------------------------------------------
# Error-path recording tests (no sampling)
# ---------------------------------------------------------------------------


class TestErrorPathAlwaysRecorded:
    """Verify error calls are always recorded without any sampling gate."""

    def test_error_records_on_every_call(self):
        """Simulate error path: errors recorded on each of N calls."""
        # The error path does NOT increment _i1_call_counts;
        # record_plugin_execution is called directly without any modulo check.
        error_records = []

        def fake_record(plugin, symbol, tf, duration, status, tier):
            if status == "error":
                error_records.append((plugin, status))

        n_errors = 7
        for i in range(n_errors):
            # Simulates: except Exception: record_plugin_execution(..., "error", ...)
            fake_record("PluginA", "ES", "1m", 0.001, "error", "I1")

        assert (
            len(error_records) == n_errors
        ), f"All {n_errors} errors must be recorded; got {len(error_records)}"

    def test_error_count_independent_of_success_counter(self):
        """Error counter is separate; many successes don't suppress error recording."""
        success_counter = defaultdict(int)
        error_records = []
        success_records = []

        from src.core.service_utils import PLUGIN_METRICS_SAMPLE_RATE

        key = ("PluginA", "I1")

        # 9 successes (counter=9, no record yet) then 1 error
        for _ in range(9):
            success_counter[key] += 1
            if success_counter[key] % PLUGIN_METRICS_SAMPLE_RATE == 0:
                success_records.append("success")

        # Error — always recorded
        error_records.append("error")

        assert len(success_records) == 0  # no success recorded yet (counter=9)
        assert len(error_records) == 1  # error always recorded


# ---------------------------------------------------------------------------
# Integration: actual service method wiring
# ---------------------------------------------------------------------------


class TestIndicatorServiceSamplingIntegration:
    """Verify _run_i1_plugins uses _i1_call_counts with modulo sampling."""

    def test_run_i1_plugins_increments_call_counts(self):
        """_run_i1_plugins must increment _i1_call_counts for each successful call."""
        import asyncio

        from services.indicator_service import IndicatorService

        svc = IndicatorService.__new__(IndicatorService)
        svc._i1_call_counts = defaultdict(int)
        svc.logger = MagicMock()
        svc._i1_plugin_states = {}
        svc._i1_plugin_states_locks = {}
        svc._instrument_map = {}
        svc.plugin_skipped_total = MagicMock()

        mock_plugin = _make_mock_plugin({"rsi_14": 55.0})

        # Patch I1_PLUGINS to one plugin and inject it into the plugin cache
        svc._i1_plugin_cache = {"TestPlugin": mock_plugin}

        frames = {"main": MagicMock()}

        with patch("services.indicator_service.I1_PLUGINS", ["TestPlugin"]):
            with patch("services.indicator_service.record_plugin_execution") as mock_rec:
                # Run 10 times — should record exactly once at call 10
                for _ in range(10):
                    asyncio.run(svc._run_i1_plugins(frames, "ES", "1m"))

        assert svc._i1_call_counts[("TestPlugin", "I1")] == 10

        # record_plugin_execution called exactly once (at count=10, success)
        success_calls = [c for c in mock_rec.call_args_list if c.args[4] == "success"]
        assert len(success_calls) == 1

    def test_run_i1_plugins_records_errors_without_sampling(self):
        """Errors in _run_i1_plugins trigger record_plugin_execution on every failure."""
        import asyncio

        from services.indicator_service import IndicatorService

        svc = IndicatorService.__new__(IndicatorService)
        svc._i1_call_counts = defaultdict(int)
        svc.logger = MagicMock()
        svc._i1_plugin_states = {}
        svc._i1_plugin_states_locks = {}
        svc._instrument_map = {}
        svc.plugin_skipped_total = MagicMock()

        error_plugin = MagicMock()
        error_plugin._state = {}
        error_plugin.compute_full = MagicMock(side_effect=ValueError("plugin crash"))

        svc._i1_plugin_cache = {"ErrorPlugin": error_plugin}

        frames = {"main": MagicMock()}

        with patch("services.indicator_service.I1_PLUGINS", ["ErrorPlugin"]):
            with patch("services.indicator_service.record_plugin_execution") as mock_rec:
                for _ in range(5):
                    asyncio.run(svc._run_i1_plugins(frames, "ES", "1m"))

        error_calls = [c for c in mock_rec.call_args_list if c.args[4] == "error"]
        assert len(error_calls) == 5, f"All 5 errors must be recorded; got {len(error_calls)}"
        # Error path must NOT increment call count
        assert svc._i1_call_counts[("ErrorPlugin", "I1")] == 0
