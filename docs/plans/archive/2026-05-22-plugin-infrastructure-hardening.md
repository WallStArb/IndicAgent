# Plugin Infrastructure Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate silent failure in the plugin system by enforcing structural contracts, wiring production-grade observability, and migrating 24 incremental plugins from ad-hoc state management to IncrementalMixin.

**Architecture:** Three mutually reinforcing layers: (1) PluginObserver as the single recording surface for all plugin metrics, injected into PluginExecutor; (2) IncrementalMixin owning the _state lifecycle for every incremental plugin; (3) emit_signal() enforcing validate_signal() at construction so invalid signals never enter the pipeline. Frame pre-validation in the executor removes 104 in-plugin df guards.

**Tech Stack:** Python 3.11+, OpenTelemetry SDK (via `src/observability/metrics.py`), pytest, `src/intelligence/plugins/mixins.py` (IncrementalMixin already exists), `src/observability/spans.py` (ATTR constants).

**Spec:** `docs/plans/2026-05-22-plugin-infrastructure-hardening-design.md`

---

## File Structure

**New files:**
- `src/observability/plugin_observer.py` — single recording surface for all plugin metrics
- `tests/unit/intelligence/test_plugin_observer.py`
- `tests/unit/intelligence/test_executor_pre_validation.py`
- `tests/unit/intelligence/test_emit_signal_validation.py`
- `tests/unit/intelligence/test_incremental_mixin_adoption.py` — CI hard block
- `tests/unit/intelligence/mixin_equivalence/` — per-plugin equivalence tests
- `tests/fixtures/legacy_plugins/` — pre-migration snapshots (deleted after phase verification)

**Modified files:**
- `src/observability/metrics.py` — add 5 new instruments, rename `plugin_fallbacks_total`, absorb 3 plugin_validator inline metrics
- `src/core/plugin_validator.py` — replace inline `_pv_meter.create_*` with imports from metrics.py
- `src/intelligence/pipeline/executor.py` — add `PluginCallResult`, inject `PluginObserver`, add frame pre-validation, remove inline metric recording
- `tests/unit/pipeline_helpers.py` — wire no-op observer into `PluginExecutor(...)` call
- `src/intelligence/trading/plugin_utils.py` — add `emit_signal()`
- 24 plugin files — migrate from manual `_state` to IncrementalMixin (listed in Tasks 12–17)

---

### Task 1: Add new OTel metric instruments to metrics.py

**Files:**
- Modify: `src/observability/metrics.py`

- [ ] **Step 1: Write the failing import test**

```python
# tests/unit/test_new_plugin_metrics.py
def test_new_plugin_metric_instruments_exist():
    from src.observability.metrics import (
        PLUGIN_FALLBACK_TOTAL,
        PLUGIN_WARMUP_SKIP_TOTAL,
        PLUGIN_OUTPUT_NULL_TOTAL,
        PLUGIN_STATE_VALIDATION_ERRORS_TOTAL,
        PLUGIN_SIGNAL_EMIT_TOTAL,
        PLUGIN_CONFIDENCE_HISTOGRAM,
    )
    assert PLUGIN_FALLBACK_TOTAL is not None
    assert PLUGIN_WARMUP_SKIP_TOTAL is not None
    assert PLUGIN_OUTPUT_NULL_TOTAL is not None
    assert PLUGIN_STATE_VALIDATION_ERRORS_TOTAL is not None
    assert PLUGIN_SIGNAL_EMIT_TOTAL is not None
    assert PLUGIN_CONFIDENCE_HISTOGRAM is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/test_new_plugin_metrics.py -v
```
Expected: ImportError — `PLUGIN_WARMUP_SKIP_TOTAL` not found.

- [ ] **Step 3: Add instruments to metrics.py**

In `src/observability/metrics.py`, rename the existing `PLUGIN_FALLBACK_TOTAL` and add five new instruments. Place immediately after the existing plugin pipeline metrics block:

```python
# Rename existing:
PLUGIN_FALLBACK_TOTAL = _meter.create_counter(
    "intelligence_pipeline_plugin_fallback_total",
    description="Plugin fallbacks from incremental to full recompute",
)

# New instruments:
PLUGIN_WARMUP_SKIP_TOTAL = _meter.create_counter(
    "intelligence_pipeline_plugin_warmup_skip_total",
    description="Plugin executions skipped — insufficient bars for min_lookback",
)
PLUGIN_OUTPUT_NULL_TOTAL = _meter.create_counter(
    "intelligence_pipeline_plugin_output_null_total",
    description="None/NaN values in plugin output dicts",
)
PLUGIN_STATE_VALIDATION_ERRORS_TOTAL = _meter.create_counter(
    "intelligence_pipeline_plugin_state_validation_errors_total",
    description="Incremental plugin state contract violations",
)
PLUGIN_SIGNAL_EMIT_TOTAL = _meter.create_counter(
    "intelligence_pipeline_plugin_signal_emit_total",
    description="I7 signals emitted via emit_signal()",
)
PLUGIN_CONFIDENCE_HISTOGRAM = _meter.create_histogram(
    "intelligence_pipeline_plugin_confidence_histogram",
    description="I7 signal confidence distribution",
    explicit_bucket_boundaries_advisory=[
        0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95
    ],
)
```

> **OTel histogram note:** The OTel Python SDK accepts `explicit_bucket_boundaries_advisory` on `create_histogram`. If your SDK version uses a different kwarg name, omit it — Prometheus will use default buckets.

- [ ] **Step 4: Find and update the one caller that references the old metric name**

```bash
grep -rn "plugin_fallbacks_total\|PLUGIN_FALLBACK_TOTAL" src/ tests/ --include="*.py"
```

In `src/intelligence/pipeline/executor.py`, the import for `PLUGIN_FALLBACK_TOTAL` — update the imported name if it appears (it was wired but never called in the current code). No call sites currently use it, but the name change must propagate.

- [ ] **Step 5: Run test to verify it passes**

```bash
.venv/bin/pytest tests/unit/test_new_plugin_metrics.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/observability/metrics.py tests/unit/test_new_plugin_metrics.py
git commit -m "feat: add 5 plugin observability instruments; rename plugin_fallbacks_total"
```

---

### Task 2: Move plugin_validator.py inline metrics into metrics.py

**Files:**
- Modify: `src/observability/metrics.py`
- Modify: `src/core/plugin_validator.py`

- [ ] **Step 1: Read what the three inline instruments look like**

In `src/core/plugin_validator.py` (lines 33–46), the three instruments are:
```python
_pv_meter = _otel_metrics.get_meter("indicagent")
_REGISTERED_PLUGINS_GAUGE = _pv_meter.create_up_down_counter(...)
_VALIDATION_STATUS_GAUGE = _pv_meter.create_up_down_counter(...)
_VALIDATION_ERRORS_COUNTER = _pv_meter.create_counter(...)
```

- [ ] **Step 2: Add these to metrics.py as named constants**

In `src/observability/metrics.py`, add at the end of the plugin pipeline metrics section:

```python
PLUGIN_VALIDATOR_REGISTERED_PLUGINS = _meter.create_up_down_counter(
    "plugin_validator_registered_plugins_total",
    description="Total registered plugins per tier",
)
PLUGIN_VALIDATOR_VALIDATION_STATUS = _meter.create_up_down_counter(
    "plugin_validator_validation_status",
    description="Validation result status",
)
PLUGIN_VALIDATOR_ERRORS = _meter.create_counter(
    "plugin_validator_validation_errors_total",
    description="Total validation errors",
)
```

- [ ] **Step 3: Rewrite plugin_validator.py to import from metrics.py**

Remove the `_pv_meter` block (lines 30–46) and replace the import section with:

```python
from opentelemetry import metrics as _otel_metrics  # DELETE THIS LINE

from src.observability.metrics import (
    PLUGIN_VALIDATOR_REGISTERED_PLUGINS as _REGISTERED_PLUGINS_GAUGE,
    PLUGIN_VALIDATOR_VALIDATION_STATUS as _VALIDATION_STATUS_GAUGE,
    PLUGIN_VALIDATOR_ERRORS as _VALIDATION_ERRORS_COUNTER,
)
```

Also remove `import opentelemetry.metrics as _otel_metrics` from the imports — it's now unused. The `PluginValidator.__init__` references via `self._registered_plugins_gauge = _REGISTERED_PLUGINS_GAUGE` still work since the names are aliased identically.

- [ ] **Step 4: Run existing validator tests**

```bash
.venv/bin/pytest tests/unit/ -k "validator" -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/observability/metrics.py src/core/plugin_validator.py
git commit -m "refactor: move plugin_validator inline OTel metrics to metrics.py"
```

---

### Task 3: Add PluginCallResult dataclass to executor.py

**Files:**
- Modify: `src/intelligence/pipeline/executor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_plugin_call_result.py
def test_plugin_call_result_shape():
    from src.intelligence.pipeline.executor import PluginCallResult
    r = PluginCallResult(
        outputs={"rsi_14": 55.0},
        duration_ms=1.2,
        used_incremental=True,
        null_count=0,
        state={"rsi_14": {"avg_gain": 0.5, "avg_loss": 0.3, "prev_close": 5000.0}},
    )
    assert r.outputs == {"rsi_14": 55.0}
    assert r.duration_ms == 1.2
    assert r.used_incremental is True
    assert r.null_count == 0
    assert r.state is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/test_plugin_call_result.py -v
```
Expected: ImportError — `PluginCallResult` not found.

- [ ] **Step 3: Add PluginCallResult to executor.py**

After the existing `PluginTask` dataclass in `executor.py` (around line 74), add:

```python
@dataclass(slots=True)
class PluginCallResult:
    """Structured return from _timed_plugin_call. Replaces (result, duration_ms) tuple."""

    outputs: dict
    duration_ms: float
    used_incremental: bool
    null_count: int
    state: dict | None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/unit/test_plugin_call_result.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/pipeline/executor.py tests/unit/test_plugin_call_result.py
git commit -m "feat: add PluginCallResult dataclass to executor"
```

---

### Task 4: Create PluginObserver

**Files:**
- Create: `src/observability/plugin_observer.py`
- Create: `tests/unit/intelligence/test_plugin_observer.py`

- [ ] **Step 1: Write the test first**

```python
# tests/unit/intelligence/test_plugin_observer.py
from unittest.mock import patch, MagicMock
import math


def _make_result(outputs=None, duration_ms=1.0, used_incremental=False, null_count=0, state=None):
    from src.intelligence.pipeline.executor import PluginCallResult
    return PluginCallResult(
        outputs=outputs or {"rsi_14": 55.0},
        duration_ms=duration_ms,
        used_incremental=used_incremental,
        null_count=null_count,
        state=state,
    )


def test_record_result_records_duration():
    from src.observability.plugin_observer import PluginObserver
    observer = PluginObserver()
    with patch("src.observability.plugin_observer.PLUGIN_DURATION_MS") as mock_hist:
        observer.record_result(_make_result(duration_ms=5.5), "RSI", "i1")
        mock_hist.record.assert_called_once_with(5.5, {"plugin_name": "RSI", "tier": "i1"})


def test_record_result_records_null_count():
    from src.observability.plugin_observer import PluginObserver
    observer = PluginObserver()
    with patch("src.observability.plugin_observer.PLUGIN_OUTPUT_NULL_TOTAL") as mock_ctr:
        observer.record_result(_make_result(null_count=3), "RSI", "i1")
        mock_ctr.add.assert_called_once_with(3, {"plugin_name": "RSI", "tier": "i1"})


def test_record_result_skips_null_count_zero():
    from src.observability.plugin_observer import PluginObserver
    observer = PluginObserver()
    with patch("src.observability.plugin_observer.PLUGIN_OUTPUT_NULL_TOTAL") as mock_ctr:
        observer.record_result(_make_result(null_count=0), "RSI", "i1")
        mock_ctr.add.assert_not_called()


def test_record_result_records_fallback():
    from src.observability.plugin_observer import PluginObserver
    observer = PluginObserver()
    with patch("src.observability.plugin_observer.PLUGIN_FALLBACK_TOTAL") as mock_ctr:
        observer.record_result(
            _make_result(used_incremental=False), "RSI", "i1"
        )
        # used_incremental=False means fallback path — record it
        mock_ctr.add.assert_called_once_with(1, {"plugin_name": "RSI", "tier": "i1"})


def test_record_error_adds_counter():
    from src.observability.plugin_observer import PluginObserver
    observer = PluginObserver()
    with patch("src.observability.plugin_observer.PLUGIN_ERRORS_TOTAL") as mock_ctr:
        observer.record_error("RSI", "i1", "ZeroDivisionError")
        mock_ctr.add.assert_called_once_with(1, {"plugin_name": "RSI", "tier": "i1"})


def test_record_warmup_skip_adds_counter():
    from src.observability.plugin_observer import PluginObserver
    observer = PluginObserver()
    with patch("src.observability.plugin_observer.PLUGIN_WARMUP_SKIP_TOTAL") as mock_ctr:
        observer.record_warmup_skip("RSI", "i1")
        mock_ctr.add.assert_called_once_with(1, {"plugin_name": "RSI", "tier": "i1"})


def test_record_i7_signal_records_emit_and_confidence():
    from src.observability.plugin_observer import PluginObserver
    observer = PluginObserver()
    signal = {"direction": 1, "confidence": 0.72}
    with (
        patch("src.observability.plugin_observer.PLUGIN_SIGNAL_EMIT_TOTAL") as mock_emit,
        patch("src.observability.plugin_observer.PLUGIN_CONFIDENCE_HISTOGRAM") as mock_hist,
    ):
        observer.record_i7_signal(signal, "TrendPlugin")
        mock_emit.add.assert_called_once_with(
            1, {"plugin_name": "TrendPlugin", "direction": "long"}
        )
        mock_hist.record.assert_called_once_with(
            0.72, {"plugin_name": "TrendPlugin"}
        )


def test_noop_observer_has_all_methods():
    from src.observability.plugin_observer import NoOpPluginObserver
    obs = NoOpPluginObserver()
    obs.record_result(MagicMock(), "RSI", "i1")
    obs.record_error("RSI", "i1", "err")
    obs.record_circuit_breaker_change("RSI", MagicMock())
    obs.record_warmup_skip("RSI", "i1")
    obs.record_state_error("RSI")
    obs.record_i7_signal({}, "RSI")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_plugin_observer.py -v
```
Expected: ImportError — `plugin_observer` module not found.

- [ ] **Step 3: Create src/observability/plugin_observer.py**

```python
"""PluginObserver — single recording surface for all plugin pipeline metrics.

All plugin metric recording flows through this class. PluginExecutor holds one
instance, injected at construction. Unit tests inject NoOpPluginObserver.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.observability.metrics import (
    CIRCUIT_BREAKER_STATE,
    PLUGIN_CONFIDENCE_HISTOGRAM,
    PLUGIN_DURATION_MS,
    PLUGIN_ERRORS_TOTAL,
    PLUGIN_FALLBACK_TOTAL,
    PLUGIN_OUTPUT_NULL_TOTAL,
    PLUGIN_SIGNAL_EMIT_TOTAL,
    PLUGIN_STATE_VALIDATION_ERRORS_TOTAL,
    PLUGIN_WARMUP_SKIP_TOTAL,
)

if TYPE_CHECKING:
    from src.intelligence.pipeline.executor import PluginCallResult
    from src.observability.circuit_breaker import CircuitState


class PluginObserver:
    """Records all plugin pipeline metrics to OTel instruments."""

    def record_result(self, result: PluginCallResult, plugin_name: str, tier: str) -> None:
        PLUGIN_DURATION_MS.record(result.duration_ms, {"plugin_name": plugin_name, "tier": tier})
        if result.null_count > 0:
            PLUGIN_OUTPUT_NULL_TOTAL.add(
                result.null_count, {"plugin_name": plugin_name, "tier": tier}
            )
        if not result.used_incremental and hasattr(result, "used_incremental"):
            # Plugin fell back from incremental to full recompute
            PLUGIN_FALLBACK_TOTAL.add(1, {"plugin_name": plugin_name, "tier": tier})

    def record_error(self, plugin_name: str, tier: str, error: str) -> None:
        PLUGIN_ERRORS_TOTAL.add(1, {"plugin_name": plugin_name, "tier": tier})

    def record_circuit_breaker_change(self, plugin_name: str, state: CircuitState) -> None:
        from src.observability.circuit_breaker import CircuitState as CS

        value = 1 if state == CS.OPEN else 0
        CIRCUIT_BREAKER_STATE.set(value, {"plugin_name": plugin_name})

    def record_warmup_skip(self, plugin_name: str, tier: str) -> None:
        PLUGIN_WARMUP_SKIP_TOTAL.add(1, {"plugin_name": plugin_name, "tier": tier})

    def record_state_error(self, plugin_name: str) -> None:
        PLUGIN_STATE_VALIDATION_ERRORS_TOTAL.add(1, {"plugin_name": plugin_name})

    def record_i7_signal(self, signal: dict, plugin_name: str) -> None:
        direction = signal.get("direction", 0)
        direction_label = "long" if direction > 0 else "short" if direction < 0 else "none"
        PLUGIN_SIGNAL_EMIT_TOTAL.add(1, {"plugin_name": plugin_name, "direction": direction_label})
        confidence = signal.get("confidence")
        if isinstance(confidence, (int, float)) and not __import__("math").isnan(confidence):
            PLUGIN_CONFIDENCE_HISTOGRAM.record(float(confidence), {"plugin_name": plugin_name})


class NoOpPluginObserver:
    """No-op observer for unit tests — all methods are silent."""

    def record_result(self, result: object, plugin_name: str, tier: str) -> None:
        pass

    def record_error(self, plugin_name: str, tier: str, error: str) -> None:
        pass

    def record_circuit_breaker_change(self, plugin_name: str, state: object) -> None:
        pass

    def record_warmup_skip(self, plugin_name: str, tier: str) -> None:
        pass

    def record_state_error(self, plugin_name: str) -> None:
        pass

    def record_i7_signal(self, signal: dict, plugin_name: str) -> None:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/intelligence/test_plugin_observer.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/observability/plugin_observer.py tests/unit/intelligence/test_plugin_observer.py
git commit -m "feat: add PluginObserver — single recording surface for plugin metrics"
```

---

### Task 5: Wire PluginObserver into PluginExecutor + replace inline recording

**Files:**
- Modify: `src/intelligence/pipeline/executor.py`
- Modify: `tests/unit/pipeline_helpers.py`

- [ ] **Step 1: Write the pre-validation test**

Create `tests/unit/intelligence/test_executor_pre_validation.py`:

```python
"""CI test: executor skips plugins with insufficient frames and records warmup_skip."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.intelligence.pipeline.executor import PluginExecutor
from src.observability.plugin_observer import NoOpPluginObserver


def _make_executor(observer=None):
    pool = ThreadPoolExecutor(max_workers=2)
    return PluginExecutor(
        thread_pool=pool,
        plugin_cache={},
        instrument_map={},
        circuit_breakers={},
        observer=observer or NoOpPluginObserver(),
    ), pool


def _stub_plugin(name: str, min_lookback: int = 30):
    p = MagicMock()
    p.name = name
    p.min_lookback = min_lookback
    p.supports_incremental = False
    p.capability_tags = frozenset()
    p.compute_full.return_value = {"signal": 1.0}
    return p


def test_pre_validation_skips_short_frames_and_records():
    """Plugin with min_lookback=30 must be skipped when frames["main"] has 10 rows."""
    skips: list[tuple] = []

    class RecordingObserver(NoOpPluginObserver):
        def record_warmup_skip(self, plugin_name, tier):
            skips.append((plugin_name, tier))

    executor, pool = _make_executor(RecordingObserver())
    plugin = _stub_plugin("RSI", min_lookback=30)
    executor._plugin_cache["RSI"] = plugin

    short_df = pd.DataFrame({"open": [1.0] * 10, "high": [1.0] * 10,
                              "low": [1.0] * 10, "close": [1.0] * 10,
                              "volume": [100.0] * 10})
    frames = {"main": short_df}
    lock = threading.Lock()

    result, state_updates = asyncio.get_event_loop().run_until_complete(
        executor.run_i1(
            plugin_states={},
            lock=lock,
            frames=frames,
            symbol="ES",
            tf="1m",
            shadow_cache={},
        )
    )

    assert ("RSI", "i1") in skips, "warmup_skip must be recorded for short frames"
    plugin.compute_full.assert_not_called()
    pool.shutdown(wait=False)


def test_pre_validation_allows_sufficient_frames():
    """Plugin with min_lookback=5 must run when frames["main"] has 30 rows."""
    executor, pool = _make_executor()
    plugin = _stub_plugin("RSI", min_lookback=5)
    executor._plugin_cache["RSI"] = plugin

    from src.intelligence.register_plugins import TIER_I1
    # Temporarily replace TIER_I1 for this test via mock
    import src.intelligence.pipeline.executor as executor_mod
    original = executor_mod.TIER_I1

    try:
        executor_mod.TIER_I1 = ("RSI",)
        df = pd.DataFrame({"open": [1.0] * 30, "high": [1.0] * 30,
                           "low": [1.0] * 30, "close": [1.0] * 30,
                           "volume": [100.0] * 30})
        frames = {"main": df}
        lock = threading.Lock()
        asyncio.get_event_loop().run_until_complete(
            executor.run_i1({}, lock, frames, "ES", "1m", {})
        )
        plugin.compute_full.assert_called_once()
    finally:
        executor_mod.TIER_I1 = original
        pool.shutdown(wait=False)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_executor_pre_validation.py -v
```
Expected: TypeError — `PluginExecutor.__init__()` doesn't accept `observer`.

- [ ] **Step 3: Update PluginExecutor.__init__ to accept observer**

In `executor.py`, update `__init__`:

```python
from src.observability.plugin_observer import NoOpPluginObserver, PluginObserver

class PluginExecutor:
    def __init__(
        self,
        thread_pool: ThreadPoolExecutor,
        plugin_cache: dict,
        instrument_map: dict,
        circuit_breakers: dict,
        observer: PluginObserver | None = None,
    ) -> None:
        self._thread_pool = thread_pool
        self._plugin_cache = plugin_cache
        self._instrument_map = instrument_map
        self._plugin_circuit_breakers: dict[str, CircuitBreaker] = dict(circuit_breakers)
        self._plugin_call_counts: dict = {}
        self._logger = structlog.get_logger(__name__)
        self._observer: PluginObserver = observer if observer is not None else NoOpPluginObserver()

        self._plugin_skipped_total = counter(
            "intelligence_pipeline_plugin_skipped_total",
            "Plugin executions skipped due to asset class mismatch",
        )
```

- [ ] **Step 4: Update _timed_plugin_call to return PluginCallResult**

Replace the current `_timed_plugin_call` function (lines 81–116) with:

```python
def _timed_plugin_call(plugin, frames, state: dict) -> PluginCallResult:
    """Returns PluginCallResult instead of (result, duration_ms) tuple.

    Computes null_count and used_incremental here so _collect_plugin_results
    receives a typed, self-describing result object.
    """
    import math as _math

    t0 = time.perf_counter()
    used_incremental = bool(getattr(plugin, "supports_incremental", False) and state)
    if used_incremental:
        result = plugin.compute_next(frames, state=state)
    else:
        result = plugin.compute_full(frames)
    duration_ms = (time.perf_counter() - t0) * 1000

    if not isinstance(result, dict):
        result = {}

    # Extract _state before computing null_count so it isn't counted
    extracted_state = result.pop("_state", None)

    # Renaissance validation: incremental plugins MUST return state in non-empty results
    if used_incremental and result and extracted_state is None:
        raise ValueError(
            f"{plugin.name}: incremental plugins MUST return _state. "
            f"Pattern: return {{**outputs, '_state': state}}"
        )

    null_count = sum(
        1 for v in result.values()
        if v is None or (isinstance(v, float) and _math.isnan(v))
    )

    return PluginCallResult(
        outputs=result,
        duration_ms=duration_ms,
        used_incremental=used_incremental,
        null_count=null_count,
        state=extracted_state,
    )
```

- [ ] **Step 5: Update _collect_plugin_results to use PluginCallResult and observer**

Replace the method body of `_collect_plugin_results`. The method signature stays the same:

```python
def _collect_plugin_results(
    self,
    tasks: list[PluginTask],
    results: list,
    lock: threading.Lock,
    symbol: str,
    tf: str,
    log_prefix: str = "plugin",
) -> tuple[list[dict], dict]:
    outputs: list[dict] = []
    state_updates: dict[tuple, dict] = {}

    for i, task in enumerate(tasks):
        out = results[i]
        tier = task.tier_key
        cb = self._get_plugin_cb(task.plugin_name)

        if isinstance(out, Exception):
            self._observer.record_error(task.plugin_name, tier, str(out))
            cb.record_failure()
            prev_state = cb.state
            if prev_state != CircuitState.CLOSED:
                self._observer.record_circuit_breaker_change(task.plugin_name, cb.state)
            self._logger.warning(
                f"{log_prefix}.error",
                plugin=task.plugin_name,
                tier=tier,
                error=str(out),
            )
        elif isinstance(out, PluginCallResult):
            self._observer.record_result(out, task.plugin_name, tier)
            result_dict = out.outputs

            if isinstance(result_dict, dict):
                if tier == "smc" and "trend_direction" in result_dict:
                    result_dict["smc_trend_direction"] = result_dict.pop("trend_direction")
                result_dict["_tier_key"] = tier

                if out.state is not None:
                    with lock:
                        state_updates[(task.plugin_name, symbol, tf)] = out.state

                prev_state = cb.state
                cb.record_success()
                if prev_state != CircuitState.CLOSED:
                    self._observer.record_circuit_breaker_change(task.plugin_name, CircuitState.CLOSED)
                    self._logger.info("plugin.circuit_breaker_closed", plugin=task.plugin_name)
                outputs.append(result_dict)

    return outputs, state_updates
```

Also remove the now-unused imports from the top of the executor file:
```python
# Remove these — now owned by PluginObserver:
# CIRCUIT_BREAKER_STATE,
# PLUGIN_ERRORS_TOTAL,
# PLUGIN_DURATION_MS,
```

Keep `FEATURES_COMPUTED_TOTAL` — that one remains in the executor (tier-level metric, not plugin-level).

- [ ] **Step 6: Add frame pre-validation in run_i1, run_tier, and run_i7_plugins**

In `run_i1`, after the `should_skip_plugin` check and before appending to `tasks`:

```python
# Frame pre-validation — replaces 104 in-plugin df guards
df_main = frames.get("main")
if df_main is None or len(df_main) < getattr(plugin, "min_lookback", 0):
    self._observer.record_warmup_skip(plugin_name, "i1")
    continue
```

In `run_tier`, add the same block (tier_key instead of "i1"):

```python
df_main = frames.get("main")
if df_main is None or len(df_main) < getattr(plugin, "min_lookback", 0):
    self._observer.record_warmup_skip(plugin_name, tier_key)
    continue
```

In `run_i7_plugins`, the frame is `plugin_input` so check `plugin_input.get("main")`:

```python
df_main = plugin_input.get("main")
if df_main is None or len(df_main) < getattr(plugin, "min_lookback", 0):
    self._observer.record_warmup_skip(plugin_name, "i7")
    continue
```

- [ ] **Step 7: Update pipeline_helpers.py to inject NoOpPluginObserver**

In `tests/unit/pipeline_helpers.py`, update the PluginExecutor construction:

```python
from src.observability.plugin_observer import NoOpPluginObserver

agent._executor = PluginExecutor(
    thread_pool=agent._thread_pool,
    plugin_cache=agent._plugin_cache,
    instrument_map=agent._instrument_map,
    circuit_breakers={},
    observer=NoOpPluginObserver(),
)
```

- [ ] **Step 8: Run full test suite**

```bash
.venv/bin/pytest tests/unit/ -q
```
Expected: all PASS. Fix any failures before proceeding.

- [ ] **Step 9: Commit**

```bash
git add src/intelligence/pipeline/executor.py tests/unit/pipeline_helpers.py \
        tests/unit/intelligence/test_executor_pre_validation.py
git commit -m "feat: inject PluginObserver into executor; add frame pre-validation; typed PluginCallResult"
```

---

### Task 6: Add emit_signal() to plugin_utils.py

**Files:**
- Modify: `src/intelligence/trading/plugin_utils.py`
- Create: `tests/unit/intelligence/test_emit_signal_validation.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/intelligence/test_emit_signal_validation.py
"""emit_signal() must call validate_signal() at construction and skip empty snapshots."""

import pytest


def _make_trade_frame(with_features: bool = True):
    from unittest.mock import MagicMock
    frame = MagicMock()
    frame.symbol = "ES"
    frame.timeframe = "1m"
    frame.timestamp = "2026-01-01T00:00:00Z"
    frame.entry_price = 5000.0
    frame.zone_low = 4990.0
    frame.zone_high = 5010.0
    frame.features = {"rsi_14": 55.0} if with_features else {}
    return frame


def _minimal_signal_kwargs():
    return dict(
        confidence=0.65,
        entry_type="at_close",
        stop_loss=4980.0,
        target_1=5050.0,
    )


def test_emit_signal_calls_validate_signal():
    """emit_signal() must raise ValueError when the signal is structurally invalid."""
    from src.intelligence.trading.plugin_utils import emit_signal
    from unittest.mock import patch, MagicMock

    frame = _make_trade_frame()

    with patch("src.intelligence.trading.plugin_utils.make_signal_from_frame") as mock_make, \
         patch("src.intelligence.trading.plugin_utils.validate_signal") as mock_validate:
        mock_make.return_value = {
            "type": "signal.v1", "direction": 1, "confidence": 0.65,
            "symbol": "ES", "timeframe": "1m", "timestamp": "...",
            "signal_type": "trend_long", "setup_plugin": "test",
            "entry_price": 5000.0, "stop_loss": 4980.0,
            "targets": [{"price": 5050.0, "label": "t1"}],
            "risk_reward_ratio": 2.5, "regime_context": {},
            "confluence_score": 0.5, "supporting_factors": [],
            "invalidation_conditions": [], "ttl_bars": 10,
        }
        mock_validate.return_value = True
        emit_signal(frame, **_minimal_signal_kwargs())
        mock_validate.assert_called_once()


def test_emit_signal_raises_on_invalid_signal():
    """emit_signal() must raise ValueError when validate_signal returns False."""
    from src.intelligence.trading.plugin_utils import emit_signal
    from unittest.mock import patch

    frame = _make_trade_frame()

    with patch("src.intelligence.trading.plugin_utils.make_signal_from_frame") as mock_make, \
         patch("src.intelligence.trading.plugin_utils.validate_signal", return_value=False):
        mock_make.return_value = {"bad": "signal"}
        with pytest.raises(ValueError, match="emit_signal"):
            emit_signal(frame, **_minimal_signal_kwargs())


def test_emit_signal_skips_snapshot_when_features_empty():
    """features_snapshot must NOT be set when trade_frame.features is empty."""
    from src.intelligence.trading.plugin_utils import emit_signal
    from unittest.mock import patch

    frame = _make_trade_frame(with_features=False)

    with patch("src.intelligence.trading.plugin_utils.make_signal_from_frame") as mock_make, \
         patch("src.intelligence.trading.plugin_utils.validate_signal", return_value=True):
        sig = {
            "type": "signal.v1", "direction": 1, "confidence": 0.65,
            "symbol": "ES", "timeframe": "1m", "timestamp": "...",
            "signal_type": "trend_long", "setup_plugin": "test",
            "entry_price": 5000.0, "stop_loss": 4980.0,
            "targets": [{"price": 5050.0, "label": "t1"}],
            "risk_reward_ratio": 2.5, "regime_context": {},
            "confluence_score": 0.5, "supporting_factors": [],
            "invalidation_conditions": [], "ttl_bars": 10,
        }
        mock_make.return_value = sig
        result = emit_signal(frame, **_minimal_signal_kwargs())
        assert "features_snapshot" not in result


def test_emit_signal_writes_snapshot_when_features_present():
    """features_snapshot must be written when trade_frame.features is non-empty."""
    from src.intelligence.trading.plugin_utils import emit_signal
    from unittest.mock import patch

    frame = _make_trade_frame(with_features=True)

    with patch("src.intelligence.trading.plugin_utils.make_signal_from_frame") as mock_make, \
         patch("src.intelligence.trading.plugin_utils.validate_signal", return_value=True), \
         patch("src.intelligence.trading.plugin_utils.capture_signal_features",
               return_value={"rsi_14": 55.0}) as mock_cap:
        sig = {
            "type": "signal.v1", "direction": 1, "confidence": 0.65,
            "symbol": "ES", "timeframe": "1m", "timestamp": "...",
            "signal_type": "trend_long", "setup_plugin": "test",
            "entry_price": 5000.0, "stop_loss": 4980.0,
            "targets": [{"price": 5050.0, "label": "t1"}],
            "risk_reward_ratio": 2.5, "regime_context": {},
            "confluence_score": 0.5, "supporting_factors": [],
            "invalidation_conditions": [], "ttl_bars": 10,
        }
        mock_make.return_value = sig
        result = emit_signal(frame, **_minimal_signal_kwargs())
        assert result.get("features_snapshot") == {"rsi_14": 55.0}
        mock_cap.assert_called_once_with(frame.features)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_emit_signal_validation.py -v
```
Expected: ImportError — `emit_signal` not found.

- [ ] **Step 3: Add emit_signal() to plugin_utils.py**

At the top of `src/intelligence/trading/plugin_utils.py`, add imports:

```python
from src.intelligence.trading.signal_schema import validate_signal
from src.intelligence.trading.signal_schema import make_signal_from_frame
from src.intelligence.trading.confidence_utils import capture_signal_features
```

Then add the function (after the existing helpers):

```python
def emit_signal(
    trade_frame,
    *,
    confidence: float,
    entry_type: str,
    stop_loss: float,
    target_1: float,
    target_2: float | None = None,
    **signal_fields,
) -> dict:
    """Construct and validate an I7 signal dict.

    Calls validate_signal() at construction — invalid signals never enter the
    pipeline. Writes features_snapshot only when trade_frame.features is non-empty.

    Args:
        trade_frame: TradeFrame with symbol, timeframe, timestamp, entry_price,
                     zone_low, zone_high, features.
        confidence:  Pre-composed via compose_confidence() — caller's responsibility.
        entry_type:  One of: at_close, at_pullback, at_limit, at_reclaim, zone_proximal.
        stop_loss:   Stop loss price.
        target_1:    Primary profit target.
        target_2:    Optional secondary profit target.
        **signal_fields: Plugin-specific additional fields.

    Returns:
        Validated signal dict.

    Raises:
        ValueError: If validate_signal() returns False.
    """
    signal = make_signal_from_frame(
        trade_frame,
        confidence=confidence,
        entry_type=entry_type,
        stop_loss=stop_loss,
        target_1=target_1,
        target_2=target_2,
        **signal_fields,
    )
    if trade_frame.features:
        signal["features_snapshot"] = capture_signal_features(trade_frame.features)
    if not validate_signal(signal):
        raise ValueError(
            f"emit_signal() produced an invalid signal for {getattr(trade_frame, 'symbol', '?')}. "
            f"Keys: {sorted(signal.keys())}"
        )
    return signal
```

- [ ] **Step 4: Verify imports exist**

```bash
python -c "from src.intelligence.trading.signal_schema import make_signal_from_frame; print('ok')"
python -c "from src.intelligence.trading.confidence_utils import capture_signal_features; print('ok')"
```

If `make_signal_from_frame` does not exist in `signal_schema.py`, find the equivalent signal construction function and adjust the import accordingly. Run `grep -n "def make_signal" src/intelligence/trading/signal_schema.py` to locate it.

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/intelligence/test_emit_signal_validation.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/trading/plugin_utils.py \
        tests/unit/intelligence/test_emit_signal_validation.py
git commit -m "feat: add emit_signal() to plugin_utils with validate_signal at construction"
```

---

### Task 7: CI hard-block — test_incremental_mixin_adoption.py

This test fails until all 24 non-mixin incremental plugins are migrated (Tasks 12–17). Commit it as a failing test intentionally — the migrations complete it.

**Files:**
- Create: `tests/unit/intelligence/test_incremental_mixin_adoption.py`

- [ ] **Step 1: Create the test**

```python
"""CI hard block: every supports_incremental plugin must subclass IncrementalMixin.

Any plugin with supports_incremental=True that does NOT inherit IncrementalMixin
is a structural fragility — it manually reimplements state logic and is the
class of plugin that caused Renaissance production bugs.

This test hard-fails at PR time so violations cannot merge.
"""

from __future__ import annotations

import pytest

from src.intelligence.plugins.mixins import IncrementalMixin
from src.intelligence.plugins import registry
from src.intelligence.register_plugins import (
    TIER_I1, TIER_I2, TIER_I3, TIER_I4, TIER_I5, TIER_I6, TIER_I7, TIER_SMC,
    register_all_plugins,
)

_ALL_TIERS = [
    ("I1", TIER_I1), ("I2", TIER_I2), ("I3", TIER_I3), ("I4", TIER_I4),
    ("I5", TIER_I5), ("SMC", TIER_SMC), ("I6", TIER_I6), ("I7", TIER_I7),
]


def _non_mixin_incremental_plugins() -> list[tuple[str, str, object]]:
    register_all_plugins()
    violations: list[tuple[str, str, object]] = []
    for tier_name, tier_list in _ALL_TIERS:
        for plugin_name in tier_list:
            plugin = registry.get_indicator(plugin_name) or registry.get_pattern(plugin_name)
            if plugin is None:
                continue
            if not getattr(plugin, "supports_incremental", False):
                continue
            if not isinstance(plugin, IncrementalMixin):
                violations.append((tier_name, plugin_name, plugin))
    return violations


_VIOLATIONS = _non_mixin_incremental_plugins()


@pytest.mark.parametrize(
    "tier_name,plugin_name,plugin",
    _VIOLATIONS,
    ids=[f"{t}-{n}" for t, n, _ in _VIOLATIONS],
)
def test_incremental_plugin_uses_mixin(tier_name: str, plugin_name: str, plugin: object) -> None:
    assert isinstance(plugin, IncrementalMixin), (
        f"{plugin_name} ({tier_name}) has supports_incremental=True but does NOT inherit "
        f"IncrementalMixin. Fix: change class {type(plugin).__name__}(IncrementalMixin): "
        f"and implement _compute_full_core, _compute_next_core, _seed_state."
    )
```

- [ ] **Step 2: Run test to see current failure count**

```bash
.venv/bin/pytest tests/unit/intelligence/test_incremental_mixin_adoption.py -v 2>&1 | tail -30
```
Expected: FAIL for all non-mixin incremental plugins (approximately 24 failures). Record the exact count.

- [ ] **Step 3: Commit as intentional failing test**

```bash
git add tests/unit/intelligence/test_incremental_mixin_adoption.py
git commit -m "test: add incremental mixin adoption CI gate (intentionally failing — migrations pending)"
```

---

### Task 8: Equivalence test infrastructure and fixture directory

**Files:**
- Create: `tests/fixtures/legacy_plugins/__init__.py`
- Create: `tests/unit/intelligence/mixin_equivalence/__init__.py`

- [ ] **Step 1: Create directories**

```bash
mkdir -p tests/fixtures/legacy_plugins
mkdir -p tests/unit/intelligence/mixin_equivalence
touch tests/fixtures/legacy_plugins/__init__.py
touch tests/unit/intelligence/mixin_equivalence/__init__.py
```

- [ ] **Step 2: Write the shared equivalence test helper**

Create `tests/unit/intelligence/mixin_equivalence/helpers.py`:

```python
"""Shared helpers for mixin equivalence tests.

Pattern for each plugin:
1. Copy the pre-migration plugin class to tests/fixtures/legacy_plugins/legacy_<name>.py
2. Write a test using assert_compute_full_equivalent + assert_incremental_equivalent
3. Migrate the production plugin
4. Verify both assertions pass
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.core.plugin_validator import build_synthetic_frames


def assert_compute_full_equivalent(legacy_plugin, new_plugin, n: int = 500, seed: int = 42):
    """Assert compute_full outputs match within 0.1% relative tolerance."""
    frames = build_synthetic_frames(n=n, seed=seed)
    legacy = legacy_plugin.compute_full(frames)
    new = new_plugin.compute_full(frames)

    for key in legacy:
        if key == "_state":
            continue
        legacy_val = legacy[key]
        new_val = new.get(key)
        assert new_val is not None, f"Key '{key}' missing in migrated implementation"
        if isinstance(legacy_val, float) and math.isfinite(legacy_val) and abs(legacy_val) > 1e-10:
            rel_err = abs(new_val - legacy_val) / abs(legacy_val)
            assert rel_err < 0.001, (
                f"Key '{key}': legacy={legacy_val:.6f}, new={new_val:.6f}, "
                f"relative_error={rel_err:.4%} exceeds 0.1% tolerance"
            )
        elif isinstance(legacy_val, float):
            assert abs(new_val - legacy_val) < 1e-10, (
                f"Key '{key}': legacy={legacy_val}, new={new_val}"
            )


def assert_incremental_equivalent(plugin, n: int = 500, seed: int = 42, warmup: int = 100):
    """Assert compute_next step-by-step matches compute_full on each bar.

    Runs compute_full on first `warmup` bars to seed state, then runs
    compute_next for bars warmup+1..n and compares to compute_full on the
    same window. All output values must match within 0.1%.
    """
    all_frames = build_synthetic_frames(n=n, seed=seed)
    main_df = all_frames["main"]

    # Seed state
    seed_result = plugin.compute_full({"main": main_df.iloc[:warmup]})
    if not seed_result or "_state" not in seed_result:
        return  # Insufficient warmup data — skip incremental test

    state = seed_result["_state"]

    mismatches = []
    for i in range(warmup, n):
        window = {"main": main_df.iloc[: i + 1]}
        full_result = plugin.compute_full(window)
        next_result = plugin.compute_next(window, state=state)
        state = next_result.get("_state", state)

        for key in full_result:
            if key == "_state":
                continue
            full_val = full_result[key]
            next_val = next_result.get(key)
            if next_val is None:
                mismatches.append(f"bar={i} key='{key}' missing in incremental result")
                continue
            if isinstance(full_val, float) and math.isfinite(full_val) and abs(full_val) > 1e-10:
                rel_err = abs(next_val - full_val) / abs(full_val)
                if rel_err >= 0.001:
                    mismatches.append(
                        f"bar={i} key='{key}' full={full_val:.6f} next={next_val:.6f} "
                        f"err={rel_err:.4%}"
                    )

    assert not mismatches, (
        f"Incremental path diverged from full recompute on {len(mismatches)} bars:\n"
        + "\n".join(mismatches[:10])
    )
```

- [ ] **Step 3: Commit infrastructure**

```bash
git add tests/fixtures/legacy_plugins/ tests/unit/intelligence/mixin_equivalence/
git commit -m "test: add equivalence test infrastructure for mixin migration verification"
```

---

### Task 9: Migrate Group 1A — RSI and MACD (reference implementations)

These two show the full migration pattern in detail. All subsequent tasks follow the same steps.

**Files:**
- Modify: `src/intelligence/features/i1_indicators/rsi.py`
- Modify: `src/intelligence/features/i1_indicators/macd.py`
- Create: `tests/fixtures/legacy_plugins/legacy_rsi.py`
- Create: `tests/fixtures/legacy_plugins/legacy_macd.py`
- Create: `tests/unit/intelligence/mixin_equivalence/test_rsi.py`
- Create: `tests/unit/intelligence/mixin_equivalence/test_macd.py`

#### RSI Migration

- [ ] **Step 1: Copy pre-migration RSI to legacy fixture**

```bash
cp src/intelligence/features/i1_indicators/rsi.py \
   tests/fixtures/legacy_plugins/legacy_rsi.py
```

In `tests/fixtures/legacy_plugins/legacy_rsi.py`, rename the class to `LegacyRSIPlugin` so it doesn't conflict with the production import.

- [ ] **Step 2: Write equivalence test for RSI**

```python
# tests/unit/intelligence/mixin_equivalence/test_rsi.py
from tests.unit.intelligence.mixin_equivalence.helpers import (
    assert_compute_full_equivalent,
    assert_incremental_equivalent,
)


def test_rsi_compute_full_equivalent():
    from tests.fixtures.legacy_plugins.legacy_rsi import LegacyRSIPlugin
    from src.intelligence.features.i1_indicators.rsi import RSIPlugin
    assert_compute_full_equivalent(LegacyRSIPlugin(), RSIPlugin())


def test_rsi_incremental_equivalent():
    from src.intelligence.features.i1_indicators.rsi import RSIPlugin
    assert_incremental_equivalent(RSIPlugin())
```

- [ ] **Step 3: Run test — expect it to pass before migration (baseline)**

```bash
.venv/bin/pytest tests/unit/intelligence/mixin_equivalence/test_rsi.py -v
```
Expected: PASS (current code returns the same values as legacy copy of current code).

- [ ] **Step 4: Migrate RSI to IncrementalMixin**

Replace `src/intelligence/features/i1_indicators/rsi.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.intelligence.plugins import InputSpec
from src.intelligence.plugins.mixins import IncrementalMixin, wilders_update


@dataclass
class RSIPlugin(IncrementalMixin):
    name: str = "RSI"
    outputs: frozenset[str] = frozenset({"rsi_14"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=100),)
    periods: list[int] | None = field(default=None)

    def __post_init__(self) -> None:
        if not self.periods:
            self.periods = [14]
        self.outputs = frozenset({f"rsi_{p}" for p in self.periods})

    def _compute_full_core(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < min(self.periods) + 1:
            return {}
        close = df["close"].to_numpy(copy=False)
        out: dict[str, Any] = {}
        for p in self.periods:
            if len(close) >= p + 1:
                rsi = self._rsi_np(close, p)
                out[f"rsi_{p}"] = float(rsi[-1])
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> dict:
        df = frames.get("main")
        if df is None:
            return {}
        close = df["close"].to_numpy(copy=False)
        state_dict: dict = {}
        for p in self.periods:
            if len(close) < p + 1:
                continue
            deltas = np.diff(close)
            seed = deltas[:p]
            up_val = float(seed.clip(min=0).sum() / p)
            down_val = float(-seed.clip(max=0).sum() / p)
            for i in range(p, len(deltas)):
                delta = float(deltas[i])
                up_val = wilders_update(up_val, max(delta, 0), p)
                down_val = wilders_update(down_val, max(-delta, 0), p)
            state_dict[f"rsi_{p}"] = {
                "avg_gain": up_val,
                "avg_loss": down_val,
                "prev_close": float(close[-1]),
            }
        return state_dict

    def _compute_next_core(self, frames: dict[str, Any], state: dict) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < 1:
            return {}
        close = float(df["close"].iloc[-1])
        out: dict[str, Any] = {}
        for p in self.periods:
            key = f"rsi_{p}"
            if key not in state:
                continue
            s = state[key]
            delta = close - s["prev_close"]
            s["avg_gain"] = wilders_update(s["avg_gain"], max(delta, 0.0), p)
            s["avg_loss"] = wilders_update(s["avg_loss"], max(-delta, 0.0), p)
            s["prev_close"] = close
            if s["avg_loss"] == 0:
                out[key] = 100.0
            else:
                out[key] = 100.0 - 100.0 / (1.0 + s["avg_gain"] / s["avg_loss"])
        return out

    @staticmethod
    def _rsi_np(close: np.ndarray, period: int) -> np.ndarray:
        deltas = np.diff(close)
        seed = deltas[:period]
        up = seed.clip(min=0).sum() / period
        down = -seed.clip(max=0).sum() / period
        rs = up / down if down != 0 else np.inf
        rsi = np.zeros_like(close)
        rsi[:period] = 50.0
        rsi[period] = 100.0 - 100.0 / (1.0 + rs)
        up_val, down_val = up, down
        for i in range(period + 1, len(close)):
            delta = deltas[i - 1]
            up_val = (up_val * (period - 1) + max(delta, 0)) / period
            down_val = (down_val * (period - 1) + max(-delta, 0)) / period
            rs = up_val / down_val if down_val != 0 else np.inf
            rsi[i] = 100.0 - 100.0 / (1.0 + rs)
        return rsi


plugin = RSIPlugin()
```

The key changes from the pre-migration version:
- `class RSIPlugin(IncrementalMixin):` — inherits mixin
- `compute_full` renamed to `_compute_full_core` — no `_state` in return
- `compute_next` renamed to `_compute_next_core` — no fallback logic, no `out["_state"] = state`; state is mutated in place, mixin attaches it
- `_seed_state` stays identical

- [ ] **Step 5: Run equivalence tests and adoption gate**

```bash
.venv/bin/pytest tests/unit/intelligence/mixin_equivalence/test_rsi.py \
                 tests/unit/intelligence/test_incremental_mixin_adoption.py \
                 tests/unit/intelligence/test_plugin_state_contract.py -v -k "rsi or RSI"
```
Expected: equivalence tests PASS; adoption gate shows RSI no longer in violations.

#### MACD Migration

- [ ] **Step 6: Copy pre-migration MACD to legacy fixture**

```bash
cp src/intelligence/features/i1_indicators/macd.py \
   tests/fixtures/legacy_plugins/legacy_macd.py
```
Rename class to `LegacyMACDPlugin` in the fixture file.

- [ ] **Step 7: Write MACD equivalence test**

```python
# tests/unit/intelligence/mixin_equivalence/test_macd.py
from tests.unit.intelligence.mixin_equivalence.helpers import (
    assert_compute_full_equivalent,
    assert_incremental_equivalent,
)


def test_macd_compute_full_equivalent():
    from tests.fixtures.legacy_plugins.legacy_macd import LegacyMACDPlugin
    from src.intelligence.features.i1_indicators.macd import MACDPlugin
    assert_compute_full_equivalent(LegacyMACDPlugin(), MACDPlugin())


def test_macd_incremental_equivalent():
    from src.intelligence.features.i1_indicators.macd import MACDPlugin
    assert_incremental_equivalent(MACDPlugin(), warmup=150)
```

- [ ] **Step 8: Migrate MACD to IncrementalMixin**

Read `src/intelligence/features/i1_indicators/macd.py`. Apply the migration pattern:

1. Change `class MACDPlugin:` → `class MACDPlugin(IncrementalMixin):`
2. Add `from src.intelligence.plugins.mixins import IncrementalMixin` to imports
3. Rename `compute_full` body → `_compute_full_core`. Remove the `_seed_state` call and `out["_state"] = state` line. Return `out` directly.
4. MACD's `_seed_state` currently takes `(frames, state)` — it mutates state in place. Change signature to `_seed_state(self, frames) -> dict:`. Extract and return the state dict rather than mutating an input.
5. Rename `compute_next` body → `_compute_next_core`. Remove the `if state is None: return self.compute_full(windows)` fallback — the mixin handles this. Remove `out["_state"] = state`. Mutate `state[key]` in place.

MACD state structure (per config key `f"{fast}_{slow}_{signal}"`):
```python
{
    "12_26_9": {
        "ema_fast": float,
        "ema_slow": float,
        "ema_signal": float,
    }
}
```

- [ ] **Step 9: Run MACD equivalence tests**

```bash
.venv/bin/pytest tests/unit/intelligence/mixin_equivalence/test_macd.py -v
```
Expected: PASS.

- [ ] **Step 10: Run full test suite**

```bash
.venv/bin/pytest tests/unit/ -q
```
Expected: all PASS.

- [ ] **Step 11: Commit**

```bash
git add src/intelligence/features/i1_indicators/rsi.py \
        src/intelligence/features/i1_indicators/macd.py \
        tests/fixtures/legacy_plugins/legacy_rsi.py \
        tests/fixtures/legacy_plugins/legacy_macd.py \
        tests/unit/intelligence/mixin_equivalence/test_rsi.py \
        tests/unit/intelligence/mixin_equivalence/test_macd.py
git commit -m "migrate: RSI + MACD to IncrementalMixin with equivalence tests"
```

---

### Task 10: Migrate Group 1B — CCI, Aroon, Chandelier, CMF

Apply the identical migration process from Task 9 for each of these four plugins. For each plugin:

1. Copy current file to `tests/fixtures/legacy_plugins/legacy_<name>.py`, rename class to `Legacy<Name>Plugin`
2. Write `tests/unit/intelligence/mixin_equivalence/test_<name>.py` using `assert_compute_full_equivalent` and `assert_incremental_equivalent`
3. Run baseline (expect PASS)
4. Apply migration: inherit `IncrementalMixin`, rename `compute_full` → `_compute_full_core`, rename `compute_next` → `_compute_next_core`, fix `_seed_state` signature if needed
5. Run equivalence test (expect PASS)
6. Commit each plugin separately

**CCI** (`src/intelligence/features/i1_indicators/cci.py`):
CCI state: `{"prev_typical": float, "tp_window": list[float]}` — a rolling window of typical prices. `_compute_next_core` appends new `(H+L+C)/3` to the window and trims to period length.

**Aroon** (`src/intelligence/features/i1_indicators/aroon.py`):
Aroon state: `{"high_window": list[float], "low_window": list[float]}` — rolling windows of highs and lows for period+1 bars. `_compute_next_core` appends new bar's high/low and trims.

**Chandelier** (`src/intelligence/features/i1_indicators/chandelier.py`):
Chandelier Exit state: `{"prev_atr": float, "long_stop": float, "short_stop": float, "prev_close": float}`. ATR uses Wilder's smoothing (import `wilders_update`).

**CMF** (`src/intelligence/features/i1_indicators/cmf.py`):
CMF state: `{"mf_vol_window": list[float], "vol_window": list[float]}` — rolling windows of money flow volume and volume for the CMF period.

> **Note:** Read each plugin file before migrating — verify the state structure matches what you implement. The descriptions above are based on the standard algorithm; confirm against the actual code.

- [ ] **Steps for CCI, Aroon, Chandelier, CMF:** follow the 6-step process above for each.

- [ ] **Run adoption gate after all four**

```bash
.venv/bin/pytest tests/unit/intelligence/test_incremental_mixin_adoption.py -v 2>&1 | grep -c "PASSED"
```
Violation count should decrease by 4.

- [ ] **Commit each plugin separately** (4 commits total for this task).

---

### Task 11: Migrate Group 1C — Historical Volatility, ROC/PPO, Parabolic SAR, Stoch RSI, AC Oscillator

Apply the identical migration process from Task 9 for each plugin.

**Historical Volatility** (`src/intelligence/features/i1_indicators/historical_volatility.py`):
HV state: `{"log_return_window": list[float]}` — rolling window of `log(close/prev_close)` for HV period bars. `_compute_next_core` appends new log return, trims, computes std.

**ROC/PPO** (`src/intelligence/features/i1_indicators/roc_ppo.py`):
ROC state: `{"close_window": list[float]}` — rolling window of closes for ROC period. PPO state: `{"ema_fast": float, "ema_slow": float}` — both per config.

**Parabolic SAR** (`src/intelligence/features/i1_indicators/parabolic_sar.py`):
PSAR state is the most complex scalar-state plugin: `{"sar": float, "ep": float, "af": float, "is_long": bool}`. The incremental update is a state machine — read the existing `compute_next` carefully before renaming.

**Stochastic RSI** (`src/intelligence/features/i1_indicators/stochastic_rsi.py`):
StochRSI state: combines RSI Wilder smoothing state (`avg_gain`, `avg_loss`, `prev_close`) with a RSI window for Stochastic: `{"rsi_window": list[float], "avg_gain": float, "avg_loss": float, "prev_close": float}`.

**AC Oscillator** (`src/intelligence/features/i1_indicators/ac_oscillator.py`):
AC state: `{"ao_window": list[float]}` — rolling window of AO values for the SMA used in AC computation.

- [ ] **Steps for each:** follow the 6-step process from Task 9 (copy → test → baseline → migrate → verify → commit).

- [ ] **Run adoption gate after all five**

```bash
.venv/bin/pytest tests/unit/intelligence/test_incremental_mixin_adoption.py -v 2>&1 | grep -c "PASSED"
```

---

### Task 12: Migrate remaining simple incremental plugins

These plugins have `supports_incremental=True` but their incremental logic is straightforward (windowed or EMA-based). Apply the identical migration process.

Plugins in this task:
- `src/intelligence/features/i1_indicators/bollinger.py` (Bollinger Bands — EMA + rolling std state)
- `src/intelligence/features/i1_indicators/donchian.py` (Donchian — rolling high/low window)
- `src/intelligence/features/i1_indicators/moving_averages.py` (SMA/EMA — EMA state per period)
- `src/intelligence/features/i1_indicators/obv.py` (OBV — running cumulative sum)
- `src/intelligence/features/i1_indicators/supertrend.py` (SuperTrend — ATR + trend state)
- `src/intelligence/features/i1_indicators/vwap.py` (VWAP — cumulative price*vol / cumulative vol)
- `src/intelligence/features/i3_structure/session_levels.py` (session high/low/open tracking)
- `src/intelligence/features/i3_structure/market_profile.py` (volume at price histogram)

For each:
1. Copy to `tests/fixtures/legacy_plugins/legacy_<name>.py`
2. Write equivalence test in `tests/unit/intelligence/mixin_equivalence/test_<name>.py`
3. Run baseline (PASS)
4. Migrate: inherit `IncrementalMixin`, rename methods, fix `_seed_state`
5. Run equivalence test (PASS)
6. Commit

> **OBV note:** OBV state is a single float (`{"obv": float, "prev_close": float}`). `_seed_state` extracts the final cumulative OBV and last close from `compute_full`. This is pure scalar state.

> **VWAP note:** VWAP state contains `{"cum_tp_vol": float, "cum_vol": float}` — reset at session start. If the existing plugin resets on session change, verify `_compute_next_core` handles the reset logic correctly.

> **market_profile note:** If market_profile's incremental path is complex (histogram updates), consider whether it belongs in Group 2 (buffer-state). Read the file first. If state is a dict of price→volume counts, treat it as buffer-state (same migration approach, just a dict instead of deque).

- [ ] **Commit each plugin separately** (8 commits total for this task).

---

### Task 13: Migrate Group 2 — Bollinger Squeeze (buffer-state)

**Files:**
- Modify: `src/intelligence/features/i5_patterns/bollinger_squeeze.py`
- Create: `tests/fixtures/legacy_plugins/legacy_bollinger_squeeze.py`
- Create: `tests/unit/intelligence/mixin_equivalence/test_bollinger_squeeze.py`

Buffer-state plugins store deques or lists of recent values. The migration is identical to scalar-state but verify deque alignment — the window length in state must match the plugin's period.

- [ ] **Step 1: Read the current bollinger_squeeze.py**

```bash
cat src/intelligence/features/i5_patterns/bollinger_squeeze.py
```

Identify the state structure. It will contain rolling windows for Bollinger Band calculation and/or Keltner Channel values.

- [ ] **Step 2: Copy to legacy fixture and write equivalence test**

Follow the same 6-step process from Task 9.

- [ ] **Step 3: Migrate**

The critical difference for buffer-state plugins: `_seed_state` must populate the deque/list from the full dataset so that the first `_compute_next_core` call has a properly populated window. Verify that `len(state["window"]) == period` after seeding.

- [ ] **Step 4: Run equivalence tests with 2x normal warmup**

```bash
.venv/bin/pytest tests/unit/intelligence/mixin_equivalence/test_bollinger_squeeze.py -v
```

Use `warmup=200` in `assert_incremental_equivalent` for buffer-state plugins to ensure the window is fully seeded.

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/features/i5_patterns/bollinger_squeeze.py \
        tests/fixtures/legacy_plugins/legacy_bollinger_squeeze.py \
        tests/unit/intelligence/mixin_equivalence/test_bollinger_squeeze.py
git commit -m "migrate: BollingerSqueeze to IncrementalMixin (buffer-state, deque alignment verified)"
```

---

### Task 14: Migrate Group 3 — Model-state plugins (BOCPD, HMM, GARCH, Kalman)

These four plugins have complex model state. Each requires dedicated numerical equivalence tests on 2000 bars (not 500). Sign off on each separately before merging.

**Locations:**
- `src/intelligence/features/smc_context/bocpd_changepoint.py`
- `src/intelligence/features/smc_context/hmm_regime.py`
- `src/intelligence/context/garch_volatility.py`
- `src/intelligence/context/kalman_trend.py`

> **Critical:** GARCH and Kalman are in `src/intelligence/context/` not `src/intelligence/features/`. The adoption gate test covers all tiers from `register_plugins.py`. Verify GARCH and Kalman appear in the relevant TIER_* list; if they're in TIER_I4 or similar, they will appear in `_VIOLATIONS` and must be migrated.

For each model-state plugin:

- [ ] **Step 1: Read the plugin carefully**

```bash
cat src/intelligence/context/garch_volatility.py
```

Understand the state structure. GARCH state typically contains `{"omega": float, "alpha": float, "beta": float, "last_variance": float}`. Kalman state contains the filter's covariance matrix and state vector.

- [ ] **Step 2: Copy to legacy fixture**

```bash
cp src/intelligence/context/garch_volatility.py \
   tests/fixtures/legacy_plugins/legacy_garch_volatility.py
```
Rename class to `LegacyGARCHVolatilityPlugin`.

- [ ] **Step 3: Write 2000-bar equivalence test**

```python
# tests/unit/intelligence/mixin_equivalence/test_garch_volatility.py
from tests.unit.intelligence.mixin_equivalence.helpers import (
    assert_compute_full_equivalent,
    assert_incremental_equivalent,
)


def test_garch_compute_full_equivalent():
    from tests.fixtures.legacy_plugins.legacy_garch_volatility import LegacyGARCHVolatilityPlugin
    from src.intelligence.context.garch_volatility import GARCHVolatilityPlugin
    assert_compute_full_equivalent(LegacyGARCHVolatilityPlugin(), GARCHVolatilityPlugin(), n=2000)


def test_garch_incremental_equivalent():
    from src.intelligence.context.garch_volatility import GARCHVolatilityPlugin
    assert_incremental_equivalent(GARCHVolatilityPlugin(), n=2000, warmup=500)
```

- [ ] **Step 4: Run baseline before migration**

```bash
.venv/bin/pytest tests/unit/intelligence/mixin_equivalence/test_garch_volatility.py -v
```
Expected: PASS (pre-migration snapshot matches current code).

- [ ] **Step 5: Migrate GARCH to IncrementalMixin**

Apply the standard migration pattern. The key invariant for GARCH: `_compute_next_core` must implement the exact GARCH(1,1) recursive update:
```
h_t = omega + alpha * epsilon_{t-1}^2 + beta * h_{t-1}
```
Where `h_{t-1}` is `state["last_variance"]` and `epsilon_{t-1}` is the previous log return. This is the same formula currently in `compute_next` — do NOT change it, only rename and restructure.

- [ ] **Step 6: Run 2000-bar equivalence test after migration**

```bash
.venv/bin/pytest tests/unit/intelligence/mixin_equivalence/test_garch_volatility.py -v
```
Expected: PASS within 0.1% tolerance on all 2000 bars.

- [ ] **Step 7: Repeat Steps 1–6 for HMM, BOCPD, and Kalman**

For HMM: state contains emission parameters and the last Viterbi sequence. `_compute_next_core` runs forward algorithm step. Use 2000 bars.

For BOCPD: state contains the run-length probability distribution. Use 2000 bars.

For Kalman: state contains the filter matrices (P, x, K). `_compute_next_core` implements the predict + update step. Use 2000 bars.

- [ ] **Step 8: Run adoption gate — should show 0 violations**

```bash
.venv/bin/pytest tests/unit/intelligence/test_incremental_mixin_adoption.py -v
```
Expected: 0 FAILED (all plugins now use IncrementalMixin).

- [ ] **Step 9: Run full test suite**

```bash
.venv/bin/pytest tests/unit/ -q
```
Expected: all PASS.

- [ ] **Step 10: Commit each model-state plugin separately**

```bash
# Example for GARCH:
git add src/intelligence/context/garch_volatility.py \
        tests/fixtures/legacy_plugins/legacy_garch_volatility.py \
        tests/unit/intelligence/mixin_equivalence/test_garch_volatility.py
git commit -m "migrate: GARCHVolatility to IncrementalMixin (2000-bar equivalence verified)"
```

---

### Task 15: Output key consistency CI test

**Files:**
- Create: `tests/unit/intelligence/test_plugin_output_key_consistency.py`

This test catches a silent data quality bug: `_compute_next_core` returning a subset of keys that `_compute_full_core` returns, causing downstream features to go missing on incremental bars.

- [ ] **Step 1: Write the test**

```python
"""CI test: compute_next must return same keys as compute_full for IncrementalMixin plugins.

A plugin that returns {"rsi_14": 55.0} on full bars but {} or {"rsi_14": ...}
(missing other keys) on incremental bars creates silent data quality bugs.
"""

from __future__ import annotations

import pytest

from src.core.plugin_validator import build_synthetic_frames
from src.intelligence.plugins import registry
from src.intelligence.plugins.mixins import IncrementalMixin
from src.intelligence.register_plugins import (
    TIER_I1, TIER_I2, TIER_I3, TIER_I4, TIER_I5, TIER_I6, TIER_I7, TIER_SMC,
    register_all_plugins,
)

_ALL_TIERS = [
    ("I1", TIER_I1), ("I2", TIER_I2), ("I3", TIER_I3), ("I4", TIER_I4),
    ("I5", TIER_I5), ("SMC", TIER_SMC), ("I6", TIER_I6), ("I7", TIER_I7),
]


def _mixin_plugins() -> list[tuple[str, str, object]]:
    register_all_plugins()
    result = []
    for tier_name, tier_list in _ALL_TIERS:
        for plugin_name in tier_list:
            plugin = registry.get_indicator(plugin_name) or registry.get_pattern(plugin_name)
            if plugin is not None and isinstance(plugin, IncrementalMixin):
                result.append((tier_name, plugin_name, plugin))
    return result


_MIXIN_PLUGINS = _mixin_plugins()


@pytest.mark.parametrize(
    "tier_name,plugin_name,plugin",
    _MIXIN_PLUGINS,
    ids=[f"{t}-{n}" for t, n, _ in _MIXIN_PLUGINS],
)
def test_compute_next_returns_same_keys_as_compute_full(
    tier_name: str, plugin_name: str, plugin: object
) -> None:
    frames = build_synthetic_frames(n=200, seed=0)
    full_result = plugin.compute_full(frames)
    if not full_result or "_state" not in full_result:
        pytest.skip(f"{plugin_name}: compute_full returned no state (insufficient data)")

    state = full_result.get("_state")
    next_result = plugin.compute_next(frames, state=state)
    if not next_result:
        pytest.skip(f"{plugin_name}: compute_next returned empty dict (no data this bar)")

    full_keys = {k for k in full_result if k != "_state"}
    next_keys = {k for k in next_result if k != "_state"}

    missing = full_keys - next_keys
    assert not missing, (
        f"{plugin_name} ({tier_name}): compute_next is missing keys that compute_full returns: "
        f"{sorted(missing)}. These keys will be absent on incremental bars."
    )
```

- [ ] **Step 2: Run test**

```bash
.venv/bin/pytest tests/unit/intelligence/test_plugin_output_key_consistency.py -v
```
Expected: all PASS (after all migrations complete). If failures exist, fix the specific plugins before proceeding.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/intelligence/test_plugin_output_key_consistency.py
git commit -m "test: add output key consistency CI gate for IncrementalMixin plugins"
```

---

### Task 16: Final verification and legacy fixture cleanup

- [ ] **Step 1: Run complete test suite**

```bash
.venv/bin/pytest tests/unit/ -v 2>&1 | tail -20
```
Expected: all PASS. Zero failures.

- [ ] **Step 2: Verify adoption gate shows zero violations**

```bash
.venv/bin/pytest tests/unit/intelligence/test_incremental_mixin_adoption.py -v
```
Expected: 0 items collected (no violations to parametrize) or all PASSED if parametrize still runs.

- [ ] **Step 3: Verify plugin state contract still green**

```bash
.venv/bin/pytest tests/unit/intelligence/test_plugin_state_contract.py -v
```
Expected: all PASS.

- [ ] **Step 4: Delete legacy fixture copies**

```bash
rm -rf tests/fixtures/legacy_plugins/
git add -A tests/fixtures/legacy_plugins/
git commit -m "cleanup: remove legacy plugin fixtures after mixin equivalence verified"
```

- [ ] **Step 5: Run lint and format**

```bash
.venv/bin/ruff check . --fix && .venv/bin/black .
```

- [ ] **Step 6: Final commit and push**

```bash
git add -A
git commit -m "feat: plugin infrastructure hardening complete — PluginObserver, IncrementalMixin migration, emit_signal, 5 new metrics"
```

---

## Alert Thresholds Reference

These alert rules must be added to Grafana after this phase ships (out of scope for this plan — tracked in ops):

| Metric | Alert Condition |
|--------|----------------|
| `intelligence_pipeline_plugin_warmup_skip_total` | rate > 50% after 30 bars in session |
| `intelligence_pipeline_plugin_output_null_total` | rate > 10× rolling baseline |
| `intelligence_pipeline_plugin_state_validation_errors_total` | any non-zero = CRITICAL |
| `intelligence_pipeline_plugin_signal_emit_total` | zero for any I7 plugin over 4 market hours |
| `intelligence_pipeline_plugin_confidence_histogram` | p50 < 0.15 over 1h |
