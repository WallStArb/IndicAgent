"""Regression guard tests for PERF-03: plugin state threading via explicit parameter.

These tests verify that:
1. Concurrent dispatch on the same plugin instance with different state dicts
   produces isolated state — no cross-contamination between bars.
2. The incremental path (compute_next) is gated on the state parameter being
   truthy, not on plugin._state.

If either test fails, the pre-dispatch plugin._state race has been reintroduced.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from src.intelligence.pipeline.executor import _timed_plugin_call


class MockIncrementalPlugin:
    """Minimal plugin that supports incremental compute.

    compute_full increments state["counter"] from 0 (or existing value).
    compute_next increments state["counter"] by 1 from existing value.
    Both record which path was taken in state["path"].
    """

    name = "mock_incremental"
    supports_incremental = True
    _state: dict = {}

    def compute_full(self, frames):
        self._state.setdefault("counter", 0)
        self._state["counter"] += 1
        self._state["path"] = "full"
        return {"counter": self._state["counter"], "path": "full"}

    def compute_next(self, windows, *, state=None):
        if state is None:
            state = {}
        state.setdefault("counter", 0)
        state["counter"] += 1
        state["path"] = "next"
        return {"counter": state["counter"]}


class MockFullOnlyPlugin:
    """Plugin with supports_incremental=False — always takes compute_full path."""

    name = "mock_full_only"
    supports_incremental = False
    _state: dict = {}

    def compute_full(self, frames, *, state=None):
        return {"result": "full"}

    def compute_next(self, windows, *, state=None):
        raise AssertionError("compute_next must not be called on non-incremental plugin")


class TestConcurrentDispatchDoesNotShareState:
    """Concurrent dispatch on the same plugin instance must not share state dicts."""

    def test_concurrent_dispatch_does_not_share_state(self):
        """Two concurrent _timed_plugin_call invocations on the same plugin instance
        with different state dicts must produce isolated state counters.

        Before PERF-03, the pre-dispatch plugin._state = ... assignment could be
        overwritten by a second bar before the first thread fired, causing both
        bars to see the same (wrong) state. After PERF-03, state is passed as
        an explicit parameter so each invocation gets its own dict reference.
        """
        plugin = MockIncrementalPlugin()
        frames = {}

        state_a = {"counter": 0}
        state_b = {"counter": 0}

        # Run two concurrent calls on the same plugin instance using a thread pool.
        with ThreadPoolExecutor(max_workers=2) as pool:
            future_a = pool.submit(_timed_plugin_call, plugin, frames, state_a)
            future_b = pool.submit(_timed_plugin_call, plugin, frames, state_b)
            result_a, _ = future_a.result()
            result_b, _ = future_b.result()

        # Each state dict must have been incremented exactly once from its own
        # starting value — isolation means no cross-bar counter bleed.
        assert (
            state_a["counter"] == 1
        ), f"state_a counter should be 1 after one compute call, got {state_a['counter']}"
        assert (
            state_b["counter"] == 1
        ), f"state_b counter should be 1 after one compute call, got {state_b['counter']}"

        # Each result should reflect its own isolated counter.
        assert result_a.get("counter") == 1, f"result_a counter mismatch: {result_a}"
        assert result_b.get("counter") == 1, f"result_b counter mismatch: {result_b}"

    def test_plugin_instance_state_attr_unchanged_by_dispatch(self):
        """The plugin instance's _state attribute must NOT be mutated by the executor.

        After PERF-03, plugin._state is never assigned in executor.py. The plugin
        instance starts with an empty _state dict and the executor does not touch it.
        """
        plugin = MockIncrementalPlugin()
        plugin._state = {}  # Explicit empty start
        frames = {}

        state = {"counter": 5}
        _timed_plugin_call(plugin, frames, state)

        # plugin._state should still be the original empty dict — executor did not touch it.
        assert (
            plugin._state == {}
        ), f"plugin._state should be unmodified by executor, got {plugin._state}"


class TestStateParamDrivesIncrementalGating:
    """The incremental path is gated on the state parameter, not plugin._state."""

    def test_state_param_drives_incremental_gating(self):
        """Umbrella: empty state -> compute_full; non-empty state -> compute_next."""
        plugin = MockIncrementalPlugin()
        frames = {}

        # Empty state must take compute_full path.
        result_full, _ = _timed_plugin_call(plugin, frames, {})
        assert result_full.get("path") == "full"

        # Non-empty state must take compute_next path.
        state_full = {"counter": 5}
        _timed_plugin_call(plugin, frames, state_full)
        assert state_full.get("path") == "next"
        assert state_full["counter"] == 6

    def test_empty_state_takes_compute_full_path(self):
        """When state={}, _timed_plugin_call must call compute_full (not compute_next).

        Rationale: empty state means no prior computation — full recompute required.
        """
        plugin = MockIncrementalPlugin()
        frames = {}

        result, duration_ms = _timed_plugin_call(plugin, frames, {})

        assert (
            result.get("path") == "full"
        ), f"Empty state should trigger compute_full, but path was {result.get('path')}"
        assert isinstance(duration_ms, float)

    def test_nonempty_state_takes_compute_next_path(self):
        """When state has prior data, _timed_plugin_call must call compute_next.

        This is the incremental path — existing state drives the faster update.
        After PERF-03 this gating uses the state parameter, not plugin._state.
        """
        plugin = MockIncrementalPlugin()
        frames = {}

        state = {"counter": 5}
        result, duration_ms = _timed_plugin_call(plugin, frames, state)

        assert (
            state.get("path") == "next"
        ), f"Non-empty state should trigger compute_next, but path was {state.get('path')}"
        assert state["counter"] == 6, f"counter should increment to 6, got {state['counter']}"

    def test_non_incremental_plugin_always_takes_compute_full(self):
        """Plugin with supports_incremental=False always uses compute_full regardless of state."""
        plugin = MockFullOnlyPlugin()
        frames = {}

        # Even with a populated state, compute_next must not be called.
        state = {"some": "data", "counter": 99}
        result, duration_ms = _timed_plugin_call(plugin, frames, state)

        assert result == {"result": "full"}

    def test_state_gating_ignores_plugin_instance_state(self):
        """The gating decision must use the state parameter, not plugin._state.

        Pre-PERF-03 bug: if plugin._state was truthy (from a prior bar assignment)
        but the state parameter was empty, compute_next would fire incorrectly.
        After PERF-03: only the state parameter matters for gating.
        """
        plugin = MockIncrementalPlugin()
        # Simulate a plugin instance that has stale _state from a prior bar
        # (this would happen in the pre-PERF-03 code path).
        plugin._state = {"stale": True, "counter": 99}

        frames = {}
        state = {}  # Fresh state for this bar — should trigger compute_full

        result, _ = _timed_plugin_call(plugin, frames, state)

        assert (
            result.get("path") == "full"
        ), "Empty state parameter should force compute_full even if plugin._state is truthy"
