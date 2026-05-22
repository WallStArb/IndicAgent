"""Tests for PluginObserver integration and frame pre-validation in PluginExecutor (Task 5)."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor


def _make_executor(observer=None):
    """Build a PluginExecutor with a NoOpPluginObserver (default) or provided observer."""
    from src.intelligence.pipeline.executor import PluginExecutor
    from src.observability.plugin_observer import NoOpPluginObserver

    pool = ThreadPoolExecutor(max_workers=2)
    return (
        PluginExecutor(
            thread_pool=pool,
            plugin_cache={},
            instrument_map={},
            circuit_breakers={},
            observer=observer or NoOpPluginObserver(),
        ),
        pool,
    )


def test_executor_accepts_observer_kwarg():
    """PluginExecutor.__init__ accepts observer keyword argument."""
    from src.intelligence.pipeline.executor import PluginExecutor
    from src.observability.plugin_observer import NoOpPluginObserver

    pool = ThreadPoolExecutor(max_workers=1)
    executor = PluginExecutor(
        thread_pool=pool,
        plugin_cache={},
        instrument_map={},
        circuit_breakers={},
        observer=NoOpPluginObserver(),
    )
    assert executor._observer is not None
    pool.shutdown(wait=False)


def test_executor_defaults_to_noop_observer():
    """PluginExecutor defaults to NoOpPluginObserver when observer=None."""
    from src.intelligence.pipeline.executor import PluginExecutor
    from src.observability.plugin_observer import NoOpPluginObserver

    pool = ThreadPoolExecutor(max_workers=1)
    executor = PluginExecutor(
        thread_pool=pool,
        plugin_cache={},
        instrument_map={},
        circuit_breakers={},
    )
    assert isinstance(executor._observer, NoOpPluginObserver)
    pool.shutdown(wait=False)


def test_warmup_skip_calls_observer():
    """Plugins with min_lookback > frame length trigger record_warmup_skip on the observer."""
    from src.intelligence.pipeline.executor import PluginExecutor
    from src.observability.plugin_observer import NoOpPluginObserver

    skip_calls = []

    class SpyObserver(NoOpPluginObserver):
        def record_warmup_skip(self, plugin_name, tier):
            skip_calls.append((plugin_name, tier))

    pool = ThreadPoolExecutor(max_workers=1)
    spy = SpyObserver()
    executor = PluginExecutor(
        thread_pool=pool,
        plugin_cache={},
        instrument_map={},
        circuit_breakers={},
        observer=spy,
    )

    # Build a plugin with min_lookback > available bars
    import pandas as pd

    class ShortPlugin:
        name = "ShortPlugin"
        supports_incremental = False
        min_lookback = 100  # requires 100 bars
        allows_partial_output = False
        inputs = ()
        outputs = frozenset(["x"])

        def compute_full(self, frames, *, state=None):
            return {"x": 1.0}

    frames = {"main": pd.DataFrame({"close": [1.0, 2.0]})}  # only 2 bars
    executor._plugin_cache = {"ShortPlugin": ShortPlugin()}

    # Use run_tier with explicit tier_plugins to bypass TIER_I1 list dependency
    async def _run():
        import asyncio

        lock = threading.Lock()
        loop = asyncio.get_running_loop()
        return await executor.run_tier(
            tier_key="i1",
            tier_plugins=("ShortPlugin",),
            plugin_states={},
            lock=lock,
            symbol="ES",
            tf="1m",
            frames=frames,
            loop=loop,
            shadow_cache={},
        )

    asyncio.run(_run())
    pool.shutdown(wait=False)

    # ShortPlugin should have been skipped via warmup guard
    assert any(name == "ShortPlugin" for name, _ in skip_calls)


def test_allows_partial_output_opt_out():
    """Plugins with allows_partial_output=True are NOT skipped even when bars < min_lookback."""
    from src.intelligence.pipeline.executor import PluginExecutor
    from src.observability.plugin_observer import NoOpPluginObserver

    skip_calls = []
    execute_calls = []

    class SpyObserver(NoOpPluginObserver):
        def record_warmup_skip(self, plugin_name, tier):
            skip_calls.append(plugin_name)

    pool = ThreadPoolExecutor(max_workers=1)
    spy = SpyObserver()
    executor = PluginExecutor(
        thread_pool=pool,
        plugin_cache={},
        instrument_map={},
        circuit_breakers={},
        observer=spy,
    )

    import pandas as pd

    class PartialPlugin:
        name = "PartialPlugin"
        supports_incremental = False
        min_lookback = 100
        allows_partial_output = True  # opt out of warmup skip
        inputs = ()
        outputs = frozenset(["x"])

        def compute_full(self, frames, *, state=None):
            execute_calls.append("executed")
            return {"x": 1.0}

    frames = {"main": pd.DataFrame({"close": [1.0, 2.0]})}
    executor._plugin_cache = {"PartialPlugin": PartialPlugin()}

    # Use run_tier with explicit tier_plugins to bypass TIER_I1 list dependency
    async def _run():
        import asyncio

        lock = threading.Lock()
        loop = asyncio.get_running_loop()
        return await executor.run_tier(
            tier_key="i1",
            tier_plugins=("PartialPlugin",),
            plugin_states={},
            lock=lock,
            symbol="ES",
            tf="1m",
            frames=frames,
            loop=loop,
            shadow_cache={},
        )

    asyncio.run(_run())
    pool.shutdown(wait=False)

    assert "PartialPlugin" not in skip_calls
    assert len(execute_calls) > 0
