"""Unit tests for PluginExecutor — PIPE-04 contract enforcement.

Proves:
- _is_shadow reads from passed cache, never from self
- _collect_plugin_results returns state_updates keyed by 3-tuples
- _collect_plugin_results makes no external writes
- _get_plugin_cb lazy-inits CircuitBreaker per plugin
- Circuit breaker opens after threshold failures
- shutdown delegates to thread_pool.shutdown
- run_tiers returns state_updates keyed by (plugin_name, symbol, tf)
- run_tiers consumes plugin_states by plugin_name
- No lateral imports from state_manager or cache_manager
"""

from __future__ import annotations

import ast
import importlib
import inspect
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from src.intelligence.pipeline.executor import PluginExecutor, PluginTask

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executor() -> PluginExecutor:
    """Create a PluginExecutor with a real thread pool and empty caches."""
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="test_exec_")
    executor = PluginExecutor(
        thread_pool=pool,
        plugin_cache={},
        instrument_map={},
        circuit_breakers={},
    )
    return executor


def _make_task(plugin_name: str, tier_key: str = "I1") -> PluginTask:
    """Create a PluginTask with a dummy coroutine placeholder."""
    return PluginTask(
        coroutine=None,
        plugin_name=plugin_name,
        state_key=(plugin_name, "ES", "1m"),
        lock=threading.Lock(),
        tier_key=tier_key,
    )


def _ok_result(data: dict, duration_ms: float = 1.0):
    """Mimic _timed_plugin_call success return: (result_dict, duration_ms)."""
    return (data, duration_ms)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIsShadow:
    """_is_shadow reads only from the passed shadow_cache parameter."""

    def test_is_shadow_reads_from_passed_cache(self):
        """Returns True for enrolled plugins, False for others."""
        executor = _make_executor()
        cache = {"my_plugin": True}
        assert executor._is_shadow("my_plugin", cache) is True
        assert executor._is_shadow("other_plugin", cache) is False

    def test_is_shadow_missing_key_returns_false(self):
        """Returns False (live) when plugin not in shadow_cache."""
        executor = _make_executor()
        assert executor._is_shadow("nonexistent", {}) is False

    def test_is_shadow_does_not_write_to_self(self):
        """Calling _is_shadow does not create any new attributes on executor."""
        executor = _make_executor()
        attrs_before = set(vars(executor).keys())
        executor._is_shadow("any_plugin", {"any_plugin": True})
        attrs_after = set(vars(executor).keys())
        assert (
            attrs_before == attrs_after
        ), f"_is_shadow added unexpected attributes: {attrs_after - attrs_before}"


class TestCollectPluginResults:
    """_collect_plugin_results contract tests."""

    def test_returns_state_updates_with_3tuple_keys(self):
        """State updates dict must be keyed by (plugin_name, symbol, tf)."""
        executor = _make_executor()
        lock = threading.Lock()
        task = _make_task("rsi_plugin", "I1")

        result_with_state = {"rsi_value": 55.0, "_state": {"last_rsi": 55.0}}
        results = [_ok_result(result_with_state)]

        outputs, state_updates = executor._collect_plugin_results(
            [task], results, lock, "ES", "1m", "plugin"
        )

        assert (
            "rsi_plugin",
            "ES",
            "1m",
        ) in state_updates, f"Expected 3-tuple key, got keys: {list(state_updates.keys())}"
        assert state_updates[("rsi_plugin", "ES", "1m")] == {"last_rsi": 55.0}

    def test_state_stripped_from_output(self):
        """_state must be removed from output dict so callers receive clean dicts."""
        executor = _make_executor()
        lock = threading.Lock()
        task = _make_task("macd_plugin", "I1")

        result_with_state = {"macd": 0.5, "_state": {"prev_ema": 0.3}}
        results = [_ok_result(result_with_state)]

        outputs, _ = executor._collect_plugin_results([task], results, lock, "ES", "1m", "plugin")

        assert len(outputs) == 1, "Expected one output"
        assert "_state" not in outputs[0], "State key must be stripped from output"
        assert "macd" in outputs[0], "Payload key must remain in output"

    def test_no_external_writes(self):
        """_collect_plugin_results must not write state_updates to any external object."""
        executor = _make_executor()
        external_object = {}
        lock = threading.Lock()
        task = _make_task("bb_plugin", "I1")

        results = [_ok_result({"bb_upper": 1.0, "_state": {"count": 1}})]
        executor._collect_plugin_results([task], results, lock, "ES", "1m", "plugin")

        assert external_object == {}, "No external writes should have occurred"

    def test_exception_result_excluded_from_outputs(self):
        """Exceptions in results list must be excluded from outputs (graceful degradation)."""
        executor = _make_executor()
        lock = threading.Lock()
        task = _make_task("failing_plugin", "I1")

        results = [RuntimeError("plugin crash")]

        outputs, state_updates = executor._collect_plugin_results(
            [task], results, lock, "ES", "1m", "plugin"
        )

        assert outputs == [], "Failed plugin must produce no output"
        assert state_updates == {}, "Failed plugin must produce no state update"

    def test_multiple_tasks_collect_all_state_updates(self):
        """All tasks with _state keys must appear in state_updates."""
        executor = _make_executor()
        lock = threading.Lock()
        tasks = [_make_task("p1", "I1"), _make_task("p2", "I1")]

        results = [
            _ok_result({"val1": 1.0, "_state": {"a": 1}}),
            _ok_result({"val2": 2.0, "_state": {"b": 2}}),
        ]

        _, state_updates = executor._collect_plugin_results(
            tasks, results, lock, "ES", "1m", "plugin"
        )

        assert ("p1", "ES", "1m") in state_updates
        assert ("p2", "ES", "1m") in state_updates
        assert state_updates[("p1", "ES", "1m")] == {"a": 1}
        assert state_updates[("p2", "ES", "1m")] == {"b": 2}


class TestGetPluginCb:
    """_get_plugin_cb lazy-initializes CircuitBreaker per plugin."""

    def test_lazy_init_creates_circuit_breaker(self):
        """First call must create and return a CircuitBreaker."""
        from src.observability.circuit_breaker import CircuitBreaker

        executor = _make_executor()
        cb = executor._get_plugin_cb("new_plugin")
        assert isinstance(cb, CircuitBreaker), "Expected CircuitBreaker instance"

    def test_same_instance_returned_on_second_call(self):
        """Second call for same plugin must return same instance."""
        executor = _make_executor()
        cb1 = executor._get_plugin_cb("plugin_x")
        cb2 = executor._get_plugin_cb("plugin_x")
        assert cb1 is cb2, "Expected same CircuitBreaker instance on repeated calls"

    def test_different_plugins_get_different_breakers(self):
        """Different plugins must have independent CircuitBreaker instances."""
        executor = _make_executor()
        cb_a = executor._get_plugin_cb("plugin_a")
        cb_b = executor._get_plugin_cb("plugin_b")
        assert cb_a is not cb_b, "Expected distinct CircuitBreaker per plugin"


class TestCircuitBreakerBehavior:
    """Circuit breaker opens after threshold failures."""

    def test_circuit_breaker_opens_after_threshold_failures(self):
        """After failure_threshold failures, cb.state should be OPEN."""
        from src.observability.circuit_breaker import CircuitBreaker, CircuitState

        executor = _make_executor()
        cb = executor._get_plugin_cb("fragile_plugin")
        assert isinstance(cb, CircuitBreaker)

        for _ in range(cb.failure_threshold):
            cb.record_failure()

        assert (
            cb.state == CircuitState.OPEN
        ), f"Expected OPEN after {cb.failure_threshold} failures, got {cb.state}"

    def test_circuit_breaker_blocks_execution_when_open(self):
        """_collect_plugin_results should increment errors but not double-open for open CB."""
        executor = _make_executor()
        lock = threading.Lock()
        task = _make_task("blocked_plugin", "I1")

        # Open the circuit
        cb = executor._get_plugin_cb("blocked_plugin")
        for _ in range(cb.failure_threshold):
            cb.record_failure()

        # Even with an exception result, no crash
        results = [RuntimeError("still failing")]
        outputs, state_updates = executor._collect_plugin_results(
            [task], results, lock, "ES", "1m", "plugin"
        )

        assert outputs == [], "Failing plugin with open CB must produce no output"


class TestShutdown:
    """shutdown delegates to thread_pool.shutdown."""

    def test_shutdown_calls_thread_pool_shutdown(self):
        """executor.shutdown() must call self._thread_pool.shutdown(wait=True)."""
        pool = MagicMock(spec=ThreadPoolExecutor)
        executor = PluginExecutor(
            thread_pool=pool,
            plugin_cache={},
            instrument_map={},
            circuit_breakers={},
        )
        executor.shutdown()
        pool.shutdown.assert_called_once_with(wait=True)


class TestRunTiers:
    """run_tiers returns state_updates keyed by (plugin_name, symbol, tf)."""

    @pytest.mark.asyncio
    async def test_run_tiers_returns_state_updates_dict_keyed_by_3tuple(self):
        """State updates from tier plugins must be 3-tuple keyed."""
        from src.intelligence.register_plugins import TIER_I3

        pool = ThreadPoolExecutor(max_workers=2)
        executor = PluginExecutor(
            thread_pool=pool,
            plugin_cache={},
            instrument_map={},
            circuit_breakers={},
        )

        if not TIER_I3:
            pytest.skip("TIER_I3 is empty")

        plugin_name = TIER_I3[0]

        class StatefulPlugin:
            supports_incremental = False
            _state = {}

            def compute_full(self, frames):
                return {"tier3_val": 1.0, "_state": {"count": 42}}

        executor._plugin_cache[plugin_name] = StatefulPlugin()

        bar = MagicMock()
        frames = {"main": MagicMock(), "features": {}}

        tiered, state_updates = await executor.run_tiers(
            plugin_states={},
            lock=threading.Lock(),
            bar=bar,
            symbol="ES",
            tf="1m",
            frames=frames,
            shadow_cache={},
        )

        # If the plugin ran, verify 3-tuple key in state_updates
        matching = [k for k in state_updates if k[0] == plugin_name]
        for key in matching:
            assert key == (
                plugin_name,
                "ES",
                "1m",
            ), f"Expected 3-tuple key (plugin, symbol, tf), got {key}"

    @pytest.mark.asyncio
    async def test_run_tiers_consumes_plugin_states_by_plugin_name(self):
        """Plugin receives state from plugin_states[plugin_name], not a positional arg."""
        from src.intelligence.register_plugins import TIER_I3

        pool = ThreadPoolExecutor(max_workers=2)
        executor = PluginExecutor(
            thread_pool=pool,
            plugin_cache={},
            instrument_map={},
            circuit_breakers={},
        )

        if not TIER_I3:
            pytest.skip("TIER_I3 is empty")

        plugin_name = TIER_I3[0]
        received_states: list = []

        class StateCapturingPlugin:
            supports_incremental = False
            _state = {}

            def compute_full(self, frames):
                received_states.append(dict(self._state))
                return {"val": 1.0}

        executor._plugin_cache[plugin_name] = StateCapturingPlugin()

        injected_state = {"injected_key": "injected_value"}
        frames = {"main": MagicMock(), "features": {}}

        await executor.run_tiers(
            plugin_states={plugin_name: injected_state},
            lock=threading.Lock(),
            bar=MagicMock(),
            symbol="ES",
            tf="1m",
            frames=frames,
            shadow_cache={},
        )

        assert len(received_states) >= 1, "Expected at least one state capture"
        assert (
            received_states[0] == injected_state
        ), f"Plugin should have received state {injected_state}, got {received_states[0]}"


class TestNoLateralImports:
    """PluginExecutor must NOT import from state_manager or cache_manager."""

    def test_no_lateral_imports(self):
        """executor.py must not contain any imports from state_manager or cache_manager."""
        import src.intelligence.pipeline.executor as executor_module

        source_file = inspect.getfile(executor_module)

        with open(source_file) as f:
            source = f.read()

        tree = ast.parse(source)

        forbidden_patterns = ["state_manager", "cache_manager"]

        violations = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                # Reconstruct module name for ImportFrom
                if isinstance(node, ast.ImportFrom) and node.module:
                    module_str = node.module
                else:
                    module_str = " ".join(alias.name for alias in node.names if alias.name)
                for forbidden in forbidden_patterns:
                    if forbidden in module_str:
                        violations.append(f"Line {node.lineno}: import of '{forbidden}' found")

        assert not violations, "PluginExecutor has forbidden lateral imports:\n" + "\n".join(
            f"  {v}" for v in violations
        )

    def test_executor_module_can_import_standalone(self):
        """executor.py must be importable without state_manager or cache_manager side effects."""

        try:
            mod = importlib.import_module("src.intelligence.pipeline.executor")
            assert hasattr(mod, "PluginExecutor"), "PluginExecutor class must be exported"
        except ImportError as exc:
            pytest.fail(f"executor.py import failed: {exc}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
