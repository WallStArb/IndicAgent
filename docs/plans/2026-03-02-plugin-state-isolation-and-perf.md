# Plugin State Isolation, Cache, and Metrics Sampling

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix per-symbol plugin state bleed in `market_analysis_service` and `indicator_service`, eliminate per-bar registry lookups via a plugin reference cache, and reduce Prometheus write pressure via sampled metrics.

**Architecture:**
- Each plugin singleton (e.g. `MomentumAccelPlugin`) has a single `_state` dict that all symbols/timeframes currently share. Fix: swap `p._state` to a per-`(pname, symbol, timeframe)` namespace before each `compute_full()` and save it back after (to handle both mutation _and_ full reassignment patterns).
- Plugin reference cache: build `_plugin_cache: dict[str, plugin]` once at `__init__`, indexed by plugin name, so `_run_tier` reads from a dict instead of calling `registry.get_pattern()` on every bar.
- Prometheus sampling: count invocations per `(pname, tier)`, record success metrics only every `_METRICS_SAMPLE_RATE = 10` calls; always record errors.
- Apply all three fixes identically in both `market_analysis_service.py` (I2-I6) and `indicator_service.py` (I1).

**Tech Stack:** Python 3.11, pytest, `unittest.mock`, existing service architecture (no new deps)

---

### Task 1: Plugin reference cache — `market_analysis_service.py`

**Files:**
- Modify: `services/market_analysis_service.py`
- Test: `tests/unit/service_tests/test_market_analysis_service.py`

**Step 1: Write the failing test**

Add to `tests/unit/service_tests/test_market_analysis_service.py`:

```python
class TestPluginCache:
    """Plugin reference cache — eliminates per-bar registry.get_pattern() calls."""

    def test_plugin_cache_populated_at_init(self):
        """_plugin_cache must contain all I2-I6 plugin names after __init__."""
        from services.market_analysis_service import MarketAnalysisService
        from src.intelligence.register_plugins import (
            TIER_I2, TIER_I3, TIER_I4, TIER_I5, TIER_SMC, TIER_I6,
        )

        svc = MarketAnalysisService()
        all_names = TIER_I2 + TIER_I3 + TIER_I4 + TIER_I5 + TIER_SMC + TIER_I6
        for name in all_names:
            assert name in svc._plugin_cache, f"_plugin_cache missing: {name}"

    def test_run_tier_does_not_call_registry_get_pattern(self):
        """_run_tier must use _plugin_cache — NOT call registry.get_pattern() on each bar."""
        import pandas as pd
        from unittest.mock import patch, MagicMock
        from services.market_analysis_service import MarketAnalysisService
        from src.intelligence.plugins import registry

        svc = MarketAnalysisService()
        frames = {
            "main": pd.DataFrame(
                [{"open": 100.0, "high": 101.0, "low": 99.0,
                  "close": 100.5, "volume": 500}] * 30
            ),
            "features": {},
        }

        with patch.object(registry, "get_pattern") as mock_get:
            svc._run_analysis_pipeline("ES", "1m", frames)

        mock_get.assert_not_called()
```

**Step 2: Run test to verify it fails**

```
.venv/bin/pytest tests/unit/service_tests/test_market_analysis_service.py::TestPluginCache -v
```
Expected: FAIL — `AttributeError: 'MarketAnalysisService' object has no attribute '_plugin_cache'`

**Step 3: Add `_plugin_cache` to `MarketAnalysisService.__init__`**

In `services/market_analysis_service.py`, after `registry.validate_tier(...)` calls (around line 87), add:

```python
# Build plugin reference cache — eliminates per-bar registry lookups
all_tier_names = TIER_I2 + TIER_I3 + TIER_I4 + TIER_I5 + TIER_SMC + TIER_I6
self._plugin_cache: dict[str, Any] = {n: registry.get_pattern(n) for n in all_tier_names}
```

**Step 4: Replace `registry.get_pattern(pname)` in `_run_tier`**

In `_run_analysis_pipeline` > nested `_run_tier` (line ~185), change:

```python
# OLD:
p = registry.get_pattern(pname)
```
to:
```python
# NEW:
p = self._plugin_cache[pname]
```

**Step 5: Run test to verify it passes**

```
.venv/bin/pytest tests/unit/service_tests/test_market_analysis_service.py::TestPluginCache -v
```
Expected: PASS (both tests green)

**Step 6: Run full unit suite to confirm no regressions**

```
.venv/bin/pytest tests/unit/ -q
```
Expected: same pass count as before (965+)

**Step 7: Commit**

```bash
git add services/market_analysis_service.py tests/unit/service_tests/test_market_analysis_service.py
git commit -m "perf(market-analysis): cache plugin references at init, skip registry lookup per bar"
```

---

### Task 2: Per-symbol state isolation — `market_analysis_service.py`

**Files:**
- Modify: `services/market_analysis_service.py`
- Test: `tests/unit/service_tests/test_market_analysis_service.py`

**Step 1: Write the failing test**

Add to `tests/unit/service_tests/test_market_analysis_service.py`:

```python
class TestPluginStateIsolation:
    """Plugin _state must be namespaced per (plugin, symbol, timeframe)."""

    def test_state_is_keyed_per_symbol(self):
        """Running the same plugin for ES and NQ must produce independent state dicts."""
        import pandas as pd
        from services.market_analysis_service import MarketAnalysisService

        svc = MarketAnalysisService()

        def make_frames(rsi_prev, rsi_curr):
            df = pd.DataFrame(
                [{"open": 100.0, "high": 101.0, "low": 99.0,
                  "close": 100.5, "volume": 500}] * 30
            )
            return {
                "main": df,
                "features": {"rsi_14": rsi_curr, "macd_12_26_9": 0.5, "roc_14": 0.3},
                "prev_features": {"rsi_14": rsi_prev, "macd_12_26_9": 0.4, "roc_14": 0.2},
            }

        # Run ES:1m — rsi accel = 5.0
        svc._run_analysis_pipeline("ES", "1m", make_frames(50.0, 55.0))
        # Run NQ:1m — rsi accel = -3.0
        svc._run_analysis_pipeline("NQ", "1m", make_frames(60.0, 57.0))

        pname = "evt_MomentumAcceleration"
        es_state = svc._plugin_states.get((pname, "ES", "1m"), {})
        nq_state = svc._plugin_states.get((pname, "NQ", "1m"), {})

        # States must be separate dicts
        assert es_state is not nq_state
        # ES accumulated rsi_accel = 5.0, NQ = -3.0
        assert es_state.get("prev_rsi_accel") == pytest.approx(5.0, abs=0.01)
        assert nq_state.get("prev_rsi_accel") == pytest.approx(-3.0, abs=0.01)

    def test_state_accumulates_across_bars_same_symbol(self):
        """Calling the same symbol twice must accumulate state in the same dict."""
        import pandas as pd
        from services.market_analysis_service import MarketAnalysisService

        svc = MarketAnalysisService()
        pname = "evt_MomentumAcceleration"

        def run(rsi_prev, rsi_curr):
            df = pd.DataFrame(
                [{"open": 100.0, "high": 101.0, "low": 99.0,
                  "close": 100.5, "volume": 500}] * 30
            )
            svc._run_analysis_pipeline("ES", "1m", {
                "main": df,
                "features": {"rsi_14": rsi_curr, "macd_12_26_9": 0.5, "roc_14": 0.3},
                "prev_features": {"rsi_14": rsi_prev, "macd_12_26_9": 0.4, "roc_14": 0.2},
            })
            return svc._plugin_states.get((pname, "ES", "1m"), {}).copy()

        state_after_bar1 = run(50.0, 55.0)   # accel = +5.0
        state_after_bar2 = run(55.0, 53.0)   # accel = -2.0

        assert state_after_bar1.get("prev_rsi_accel") == pytest.approx(5.0, abs=0.01)
        assert state_after_bar2.get("prev_rsi_accel") == pytest.approx(-2.0, abs=0.01)
```

**Step 2: Run test to verify it fails**

```
.venv/bin/pytest tests/unit/service_tests/test_market_analysis_service.py::TestPluginStateIsolation -v
```
Expected: FAIL — `AttributeError: 'MarketAnalysisService' object has no attribute '_plugin_states'`

**Step 3: Add `_plugin_states` to `__init__`**

After the `_plugin_cache` line in `__init__`:

```python
# Per-(plugin, symbol, timeframe) state namespace — prevents cross-symbol state bleed
self._plugin_states: dict[tuple[str, str, str], dict] = {}
```

**Step 4: Apply state swap in `_run_tier`**

The nested `_run_tier` function lives inside `_run_analysis_pipeline(self, symbol, timeframe, frames)`.
It captures `symbol` and `timeframe` via closure. Replace the loop body:

```python
# OLD:
p = self._plugin_cache[pname]
out = p.compute_full(frames)

# NEW:
p = self._plugin_cache[pname]
state_key = (pname, symbol, timeframe)
p._state = self._plugin_states.setdefault(state_key, {})
out = p.compute_full(frames)
self._plugin_states[state_key] = p._state  # capture full reassignments (e.g. GARCH, HMM)
```

**Step 5: Run test to verify it passes**

```
.venv/bin/pytest tests/unit/service_tests/test_market_analysis_service.py::TestPluginStateIsolation -v
```
Expected: PASS (both tests green)

**Step 6: Run full unit suite**

```
.venv/bin/pytest tests/unit/ -q
```
Expected: same pass count

**Step 7: Commit**

```bash
git add services/market_analysis_service.py tests/unit/service_tests/test_market_analysis_service.py
git commit -m "fix(market-analysis): isolate plugin _state per (plugin, symbol, timeframe)"
```

---

### Task 3: Prometheus sampling — `market_analysis_service.py`

**Files:**
- Modify: `services/market_analysis_service.py`
- Test: `tests/unit/service_tests/test_market_analysis_service.py`

**Step 1: Write the failing test**

Add to `tests/unit/service_tests/test_market_analysis_service.py`:

```python
class TestPrometheusSampling:
    """record_plugin_execution is called at sampled rate for successes, always for errors."""

    def test_success_metrics_sampled_at_rate_10(self):
        """Success metrics recorded only every 10th call, not every call."""
        import pandas as pd
        from unittest.mock import patch
        from services.market_analysis_service import MarketAnalysisService

        svc = MarketAnalysisService()
        df = pd.DataFrame(
            [{"open": 100.0, "high": 101.0, "low": 99.0,
              "close": 100.5, "volume": 500}] * 30
        )
        frames = {"main": df, "features": {}, "prev_features": {}}

        with patch(
            "services.market_analysis_service.record_plugin_execution"
        ) as mock_record:
            for _ in range(10):
                svc._run_analysis_pipeline("ES", "1m", frames)

        # With 42 plugins × 10 calls = 420 total success invocations
        # At rate=10, we expect 42 recorded (every 10th)
        # But we only care that it's less than total, i.e. sampled
        success_calls = [
            c for c in mock_record.call_args_list if c.args[4] == "success"
        ]
        total_plugin_invocations = len(
            list(svc._plugin_cache.keys())
        ) * 10
        assert len(success_calls) < total_plugin_invocations, (
            "Expected sampling: fewer success records than total invocations"
        )
        # Exactly 1-in-10 should be recorded
        assert len(success_calls) == len(svc._plugin_cache) * 1  # 1 per plugin at call 10

    def test_error_metrics_always_recorded(self):
        """Error metrics are recorded on every failure — never sampled."""
        import pandas as pd
        from unittest.mock import patch, MagicMock
        from services.market_analysis_service import MarketAnalysisService

        svc = MarketAnalysisService()

        # Make one plugin always raise
        boom_name = list(svc._plugin_cache.keys())[0]
        mock_plugin = MagicMock()
        mock_plugin.compute_full.side_effect = RuntimeError("boom")
        svc._plugin_cache[boom_name] = mock_plugin

        df = pd.DataFrame(
            [{"open": 100.0, "high": 101.0, "low": 99.0,
              "close": 100.5, "volume": 500}] * 30
        )
        frames = {"main": df, "features": {}, "prev_features": {}}

        with patch(
            "services.market_analysis_service.record_plugin_execution"
        ) as mock_record:
            for _ in range(5):
                svc._run_analysis_pipeline("ES", "1m", frames)

        error_calls = [
            c for c in mock_record.call_args_list
            if c.args[4] == "error" and c.args[0] == boom_name
        ]
        assert len(error_calls) == 5, "Errors must be recorded on every invocation"
```

**Step 2: Run test to verify it fails**

```
.venv/bin/pytest tests/unit/service_tests/test_market_analysis_service.py::TestPrometheusSampling -v
```
Expected: FAIL — tests fail because no sampling exists yet

**Step 3: Add module-level constant and call counter to `market_analysis_service.py`**

At the top of `services/market_analysis_service.py`, after imports:
```python
_METRICS_SAMPLE_RATE = 10  # record 1 in 10 success executions; errors always recorded
```

In `__init__`, after `_plugin_states`:
```python
self._plugin_call_counts: dict[tuple[str, str], int] = defaultdict(int)
```

(`defaultdict` is already imported at line 21.)

**Step 4: Apply sampling in `_run_tier`**

Replace the existing `record_plugin_execution` calls inside `_run_tier`:

```python
# OLD (success path):
record_plugin_execution(
    pname, symbol, timeframe, time.time() - t0, "success", tier
)

# OLD (error path):
record_plugin_execution(
    pname, symbol, timeframe, time.time() - t0, "error", tier
)
```

```python
# NEW — replace both:
except Exception as exc:
    self.logger.warning(f"{tier} plugin failed", plugin=pname, error=str(exc))
    record_plugin_execution(pname, symbol, timeframe, time.time() - t0, "error", tier)
else:
    self._plugin_call_counts[(pname, tier)] += 1
    if self._plugin_call_counts[(pname, tier)] % _METRICS_SAMPLE_RATE == 0:
        record_plugin_execution(pname, symbol, timeframe, time.time() - t0, "success", tier)
```

The full `_run_tier` loop body becomes:

```python
for pname in plugins:
    t0 = time.time()
    try:
        p = self._plugin_cache[pname]
        state_key = (pname, symbol, timeframe)
        p._state = self._plugin_states.setdefault(state_key, {})
        out = p.compute_full(frames)
        self._plugin_states[state_key] = p._state
        results.update(out)
    except Exception as exc:
        self.logger.warning(f"{tier} plugin failed", plugin=pname, error=str(exc))
        record_plugin_execution(pname, symbol, timeframe, time.time() - t0, "error", tier)
    else:
        self._plugin_call_counts[(pname, tier)] += 1
        if self._plugin_call_counts[(pname, tier)] % _METRICS_SAMPLE_RATE == 0:
            record_plugin_execution(
                pname, symbol, timeframe, time.time() - t0, "success", tier
            )
```

**Step 5: Run test to verify it passes**

```
.venv/bin/pytest tests/unit/service_tests/test_market_analysis_service.py::TestPrometheusSampling -v
```
Expected: PASS

**Step 6: Run full unit suite**

```
.venv/bin/pytest tests/unit/ -q
```
Expected: same pass count

**Step 7: Commit**

```bash
git add services/market_analysis_service.py tests/unit/service_tests/test_market_analysis_service.py
git commit -m "perf(market-analysis): sample Prometheus success metrics 1-in-10, errors always recorded"
```

---

### Task 4: Plugin cache + state isolation + sampling — `indicator_service.py`

**Files:**
- Modify: `services/indicator_service.py`
- Test: `tests/unit/service_tests/test_indicator_service.py`

**Step 1: Write the failing tests**

Add to `tests/unit/service_tests/test_indicator_service.py`:

```python
class TestIndicatorServicePluginOptimizations:
    """Plugin cache, state isolation, and metrics sampling for I1 plugins."""

    def test_i1_plugin_cache_populated_at_init(self):
        """_i1_plugin_cache must contain all I1 plugin names after __init__."""
        from services.indicator_service import IndicatorService, I1_PLUGINS

        svc = IndicatorService()
        for name in I1_PLUGINS:
            assert name in svc._i1_plugin_cache, f"_i1_plugin_cache missing: {name}"

    def test_i1_state_keyed_per_symbol_timeframe(self):
        """I1 plugin state must be namespaced per (plugin, symbol, timeframe)."""
        import pandas as pd
        from collections import OrderedDict
        from datetime import datetime, timedelta
        from unittest.mock import patch, MagicMock
        from services.indicator_service import IndicatorService

        svc = IndicatorService()

        # Build minimal bar history for two symbols
        for sym in ("ES", "NQ"):
            key = f"{sym}:1m"
            svc.bar_history[key] = OrderedDict()
            for i in range(130):
                ts = datetime(2026, 2, 28, 9, 0, 0) + timedelta(minutes=i)
                svc.bar_history[key][ts.isoformat()] = {
                    "timestamp": ts, "open": 100.0, "high": 101.0,
                    "low": 99.0, "close": 100.5, "volume": 500,
                }
            svc._df_cache[key] = None

        df = pd.DataFrame(list(svc.bar_history["ES:1m"].values()))
        frames = {"main": df}

        # Run for ES, then NQ
        svc._run_i1_plugins(frames, "ES", "1m")
        svc._run_i1_plugins(frames, "NQ", "1m")

        # Each plugin should have separate state dicts for ES vs NQ
        pname = I1_PLUGINS[0]  # check first I1 plugin
        es_state = svc._i1_plugin_states.get((pname, "ES", "1m"))
        nq_state = svc._i1_plugin_states.get((pname, "NQ", "1m"))
        # Both should exist and be different objects
        assert es_state is not None
        assert nq_state is not None
        assert es_state is not nq_state

    def test_i1_success_metrics_sampled(self):
        """I1 success metrics sampled at _METRICS_SAMPLE_RATE, errors always recorded."""
        import pandas as pd
        from collections import OrderedDict
        from datetime import datetime, timedelta
        from unittest.mock import patch
        from services.indicator_service import IndicatorService, I1_PLUGINS

        svc = IndicatorService()
        key = "ES:1m"
        svc.bar_history[key] = OrderedDict()
        for i in range(130):
            ts = datetime(2026, 2, 28, 9, 0, 0) + timedelta(minutes=i)
            svc.bar_history[key][ts.isoformat()] = {
                "timestamp": ts, "open": 100.0, "high": 101.0,
                "low": 99.0, "close": 100.5, "volume": 500,
            }
        df = pd.DataFrame(list(svc.bar_history[key].values()))
        frames = {"main": df}

        with patch(
            "services.indicator_service.record_plugin_execution"
        ) as mock_record:
            for _ in range(10):
                svc._run_i1_plugins(frames, "ES", "1m")

        success_calls = [c for c in mock_record.call_args_list if c.args[4] == "success"]
        assert len(success_calls) < len(I1_PLUGINS) * 10, "Expected sampling"
        assert len(success_calls) == len(I1_PLUGINS) * 1  # 1-in-10
```

**Step 2: Run tests to verify they fail**

```
.venv/bin/pytest tests/unit/service_tests/test_indicator_service.py::TestIndicatorServicePluginOptimizations -v
```
Expected: FAIL — `AttributeError: 'IndicatorService' object has no attribute '_i1_plugin_cache'`

**Step 3: Add module-level constant and three new attrs to `IndicatorService.__init__`**

At top of `services/indicator_service.py`, after imports, add:
```python
_METRICS_SAMPLE_RATE = 10
```

In `IndicatorService.__init__`, after `registry.validate_tier(I1_PLUGINS, "I1")`:

```python
# I1 plugin reference cache and per-symbol state isolation
self._i1_plugin_cache: dict[str, Any] = {
    n: registry.get_indicator(n) for n in I1_PLUGINS
}
self._i1_plugin_states: dict[tuple[str, str, str], dict] = {}
self._i1_call_counts: dict[tuple[str, str], int] = defaultdict(int)
```

(`defaultdict` is already imported at line 20.)

**Step 4: Update `_run_i1_plugins` signature and body**

Change signature from:
```python
def _run_i1_plugins(self, frames: dict[str, Any]) -> dict[str, Any]:
```
to:
```python
def _run_i1_plugins(self, frames: dict[str, Any], symbol: str, timeframe: str) -> dict[str, Any]:
```

Replace the loop body:

```python
# OLD:
for plugin_name in I1_PLUGINS:
    t0 = time.time()
    try:
        p = registry.get_indicator(plugin_name)
        result = p.compute_full(frames)
        features.update(result)
        record_plugin_execution(plugin_name, "", "", time.time() - t0, "success", "I1")
    except Exception as e:
        self.logger.warning("I1 plugin failed", plugin=plugin_name, error=str(e))
        record_plugin_execution(plugin_name, "", "", time.time() - t0, "error", "I1")
return features
```

```python
# NEW:
for plugin_name in I1_PLUGINS:
    t0 = time.time()
    try:
        p = self._i1_plugin_cache[plugin_name]
        state_key = (plugin_name, symbol, timeframe)
        p._state = self._i1_plugin_states.setdefault(state_key, {})
        result = p.compute_full(frames)
        self._i1_plugin_states[state_key] = p._state
        features.update(result)
    except Exception as e:
        self.logger.warning("I1 plugin failed", plugin=plugin_name, error=str(e))
        record_plugin_execution(plugin_name, symbol, timeframe, time.time() - t0, "error", "I1")
    else:
        self._i1_call_counts[(plugin_name, "I1")] += 1
        if self._i1_call_counts[(plugin_name, "I1")] % _METRICS_SAMPLE_RATE == 0:
            record_plugin_execution(
                plugin_name, symbol, timeframe, time.time() - t0, "success", "I1"
            )
return features
```

**Step 5: Update the one call site of `_run_i1_plugins`**

In `_process_single_bar` (line ~252), change:
```python
# OLD:
features = self._run_i1_plugins(frames)
```
to:
```python
# NEW:
features = self._run_i1_plugins(frames, symbol, timeframe)
```

**Step 6: Run the new tests**

```
.venv/bin/pytest tests/unit/service_tests/test_indicator_service.py::TestIndicatorServicePluginOptimizations -v
```
Expected: PASS (all 3 green)

**Step 7: Run full unit suite**

```
.venv/bin/pytest tests/unit/ -q
```
Expected: same pass count as before

**Step 8: Commit**

```bash
git add services/indicator_service.py tests/unit/service_tests/test_indicator_service.py
git commit -m "fix(indicator): plugin cache, per-symbol state isolation, sampled Prometheus metrics"
```

---

### Task 5: Lint and final verification

**Step 1: Run ruff from project root**

```
.venv/bin/ruff check .
```
Expected: `All checks passed.` (0 errors)

If ruff reports issues, fix them before proceeding.

**Step 2: Run full test suite one final time**

```
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -20
```
Expected: all previously passing tests still pass; 9 new tests added.

**Step 3: Commit (if ruff fix required any changes)**

Only if ruff auto-fixes were applied:
```bash
git add -u
git commit -m "style: ruff fixes for plugin optimization changes"
```
