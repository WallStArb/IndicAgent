# Plugin Infrastructure Hardening — Design Spec
**Date:** 2026-05-22
**Status:** Approved, pending implementation plan

---

## Problem Statement

The plugin system processes 132 plugins per bar across tiers I1-I7. Three structural
problems identified through audit:

1. **Structural fragility:** 25 of 33 incremental plugins manually reimplement state
   logic instead of using IncrementalMixin. These are the exact plugins that generated
   the Renaissance bugs (circuit breakers firing, state corruption, silent bad bars).
   The _state contract is enforced by tests after the fact, not by design.

2. **Observability blindness:** The pipeline has no per-plugin output quality signal.
   A plugin can emit nulls, pin confidence at the floor, or never fire — all silently.
   `PLUGIN_FALLBACK_TOTAL` exists in metrics.py but is never recorded. No signal
   emission frequency, no confidence distribution, no state validation errors.

3. **Boilerplate tax:** 104 repeated df-guard patterns across all tiers, 36 I7 plugins
   each manually calling the same 3-line signal construction sequence. Every schema
   evolution touches N files instead of 1.

---

## Design Principles (Renaissance / Jim Simons Standard)

- **Silent failure is catastrophe.** If a system can fail without detection, it will.
- **Structural enforcement over tribal knowledge.** The mixin makes the _state contract
  impossible to violate. Tests catch what design can't prevent.
- **One door into each concern.** Observability flows through PluginObserver. Signal
  construction flows through emit_signal(). No scattered recording.
- **Every metric must be actionable.** If there is no alert to write against it, the
  metric is noise. Each metric below has an explicit alerting threshold.
- **Plugins express analytical logic only.** Frame validation, state attachment, metric
  recording, signal construction — these are infrastructure concerns, not plugin concerns.

---

## Architecture: The Layer Model

```
┌─────────────────────────────────────────────────────────┐
│  EXECUTOR                                                │
│  - Frame pre-validation (replaces 104 in-plugin guards) │
│  - Dispatch, circuit breakers, timing                   │
│  - Zero metric recording code — delegates to observer   │
├─────────────────────────────────────────────────────────┤
│  PLUGIN OBSERVER  (src/observability/plugin_observer.py)│
│  - Single recording surface for ALL plugin metrics      │
│  - Imports instruments from metrics.py                  │
│  - Injected into executor at construction               │
│  - No-op stub for unit tests                            │
├─────────────────────────────────────────────────────────┤
│  INCREMENTAL MIXIN                                      │
│  - State lifecycle: _state attachment, fallback, nulls  │
│  - Sets _used_incremental in result dict                │
│  - Plugin implements 3 focused methods, nothing else    │
├─────────────────────────────────────────────────────────┤
│  PLUGIN UTILS                                           │
│  - emit_signal(): I7 signal construction + validation   │
│  - Calls validate_signal() at construction, not later   │
├─────────────────────────────────────────────────────────┤
│  PLUGINS                                                │
│  - Pure analytical logic only                           │
│  - _compute_full_core / _compute_next_core / _seed_state│
│  - Zero frame validation, state attachment, or metrics  │
└─────────────────────────────────────────────────────────┘
```

Information flows down. Plugins know nothing about the layers above them.

---

## Section 1: Executor Changes

### Frame Pre-Validation

Added before every plugin dispatch, replaces 104 in-plugin df guards:

```python
df = frames.get("main")
if df is None or len(df) < plugin.min_lookback:
    self._observer.record_warmup_skip(plugin_name, tier_key)
    continue
```

Plugins never receive invalid frames. After migration the guard in each plugin
body is dead code and is removed.

### PluginCallResult Dataclass

Replaces the (result, duration_ms) tuple returned by _timed_plugin_call:

```python
@dataclass(slots=True)
class PluginCallResult:
    outputs: dict
    duration_ms: float
    used_incremental: bool   # True = incremental path, False = fallback/full
    null_count: int          # count of None/NaN in outputs, computed in mixin
    state: dict | None       # extracted _state, popped from outputs
```

Structured, typed, self-documenting. Future fields added here propagate
automatically to the observer and quality recorder.

### Executor Metric Recording — Removed

All `.add()` / `.record()` calls currently inline in `_collect_plugin_results`
and `run_i7_plugins` are removed from the executor and replaced with:

```python
self._observer.record_result(result, plugin_name, tier)     # timing, quality, fallback
self._observer.record_error(plugin_name, tier, str(exc))    # errors
self._observer.record_circuit_breaker_change(plugin_name, state)
self._observer.record_warmup_skip(plugin_name, tier)
# For I7 signals with direction != 0:
self._observer.record_i7_signal(signal, plugin_name)
```

### plugin_validator.py Inline Metrics — Cleaned Up

The 3 inline `_pv_meter.create_*` calls in plugin_validator.py are moved to
metrics.py as standard module-level constants, then imported. No more direct
`get_meter()` calls outside of metrics.py.

---

## Section 2: IncrementalMixin Migration

### The Contract

Every `supports_incremental=True` plugin must be an `IncrementalMixin` subclass.
Non-mixin incremental plugins are a hard CI failure after this phase.

### Plugin Shape After Migration

```python
@dataclass
class RSIPlugin(IncrementalMixin):
    # attributes unchanged

    def _compute_full_core(self, frames: dict) -> dict:
        # pure RSI calculation — returns outputs only, no _state
        return {"rsi_14": float(rsi[-1])}

    def _seed_state(self, frames: dict) -> dict:
        # extract initial Wilder smoothing values
        return {"avg_gain": ..., "avg_loss": ...}

    def _compute_next_core(self, frames: dict, state: dict) -> dict:
        # one-bar incremental update — returns outputs only, no _state
        return {"rsi_14": float(new_rsi)}
```

The mixin owns: _state attachment, fallback logic, null counting,
_used_incremental flag. Plugin author expresses analytical logic only.

### _used_incremental Propagation

The mixin sets `result["_used_incremental"]` before returning:
- `True` on the incremental path
- `False` on fallback to compute_full

Extracted by executor alongside `_state`, placed in `PluginCallResult`.
No callback injection, no mutable singletons — telemetry propagates through
data, not side channels.

### Migration Order (by state complexity, not tier)

**Group 1 — Scalar-state (14 plugins, mechanical):**
RSI, MACD, CCI, Williams R, Stochastic, MFI, CMF, Historical Volatility,
ROC/PPO, Aroon, Chandelier, Parabolic SAR, Stoch RSI, AC Oscillator

**Group 2 — Buffer-state (2 plugins, verify deque alignment):**
Bollinger Squeeze, Volume Zscore

**Group 3 — Model-state (2 plugins, dedicated equivalence tests):**
GARCH Volatility, Kalman Trend
- Must pass numerical equivalence against 2000 bars before merge
- Incremental update must implement exact model recursion
- Signed off separately

### Numerical Equivalence Requirement

Every migrated plugin ships with a numerical equivalence test:
- Old implementation vs mixin implementation on 500 synthetic bars
- All output fields must match within 0.1% relative tolerance
- Legacy classes kept in `tests/fixtures/legacy_plugins/` until verified, then deleted
- Tests live in `tests/unit/intelligence/mixin_equivalence/`

### Output Key Consistency

CI test asserts `_compute_next_core` returns the same keys as `_compute_full_core`
for each plugin. A plugin missing a key on incremental bars (while returning it
on full bars) is a silent data quality bug — caught at PR time.

---

## Section 3: I7 Signal Construction Template

### emit_signal() in plugin_utils.py

```python
def emit_signal(
    trade_frame: TradeFrame,
    *,
    confidence: float,       # pre-composed via compose_confidence() — plugin's job
    entry_type: str,
    stop_loss: float,
    target_1: float,
    target_2: float | None = None,
    **signal_fields,
) -> dict:
    signal = make_signal_from_frame(
        trade_frame,
        confidence=confidence,
        entry_type=entry_type,
        stop_loss=stop_loss,
        target_1=target_1,
        target_2=target_2,
        **signal_fields,
    )
    # Only write snapshot when there is something to write
    if trade_frame.features:
        signal["features_snapshot"] = capture_signal_features(trade_frame.features)
    # Validate at construction — invalid signals never enter the pipeline
    validate_signal(signal)
    return signal
```

### What This Enforces

- `validate_signal()` called exactly once, at construction, in one place
- Empty `features_snapshot` never written to database
- Schema evolution (new required fields, quality tier annotation) touches
  one function, not 36 plugins
- `**signal_fields` retained for plugin-specific fields

### Future Extension Point (tracked TODO)

When `PluginCallResult.used_incremental` propagates into `IntelligenceEvent`
(future phase), `emit_signal()` gains one line — attach `signal_quality_tier`
derived from pipeline context. 36 plugins get it automatically. This is the
payoff of having the abstraction: adding a field once, everywhere.

---

## Section 4: Observability — PluginObserver

### Location

`src/observability/plugin_observer.py`

All plugin metric recording lives here. Executor has zero `.add()` / `.record()`
calls after this phase. The existing OTel → Prometheus → Grafana pipeline
handles export automatically — no new infrastructure.

### New Metric Instruments (added to metrics.py)

All 5 follow the existing pattern (module-level constants, OTel SDK):

| Instrument | Type | Labels | Alert Threshold |
|------------|------|--------|-----------------|
| `intelligence_pipeline_plugin_warmup_skip_total` | counter | plugin_name, tier | rate > 50% after 30 bars in session |
| `intelligence_pipeline_plugin_output_null_total` | counter | plugin_name, tier | rate > 10x rolling baseline |
| `intelligence_pipeline_plugin_state_validation_errors_total` | counter | plugin_name | any non-zero = CRITICAL |
| `intelligence_pipeline_plugin_signal_emit_total` | counter | plugin_name, direction | zero for I7 plugin over 4 market hours |
| `intelligence_pipeline_plugin_confidence_histogram` | histogram | plugin_name | p50 < 0.15 over 1h |

Buckets for confidence histogram: [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95]

Existing `PLUGIN_FALLBACK_TOTAL` (exists as `plugin_fallbacks_total` — rename to `intelligence_pipeline_plugin_fallback_total` in this phase)
is wired in this phase.

**Cardinality budget:** ~2,000 new time series. Well within Prometheus capacity.
No per-field null tracking (avoids 132 x 20 = 2,640 label combinations).

### PluginObserver Interface

```python
class PluginObserver:
    def record_result(self, result: PluginCallResult, plugin_name: str, tier: str) -> None
    def record_error(self, plugin_name: str, tier: str, error: str) -> None
    def record_circuit_breaker_change(self, plugin_name: str, state: CircuitState) -> None
    def record_warmup_skip(self, plugin_name: str, tier: str) -> None
    def record_state_error(self, plugin_name: str) -> None
    def record_i7_signal(self, signal: dict, plugin_name: str) -> None
```

Injected into executor at construction. Unit tests inject a no-op stub.
Add a new metric: add one method here and one instrument to metrics.py.

### Consolidation of plugin_validator.py Inline Metrics

The 3 inline `_pv_meter.create_*` calls in plugin_validator.py are non-standard.
Moved to metrics.py in this phase. Plugin validator imports from metrics.py
like every other module.

---

## Section 5: Testing Strategy

One test owns each invariant. No invariant is covered by two tests.

### New Tests

| Test | Invariant Owned | Gate |
|------|----------------|------|
| `test_incremental_mixin_adoption.py` | Every supports_incremental plugin uses IncrementalMixin | CI hard block |
| `tests/unit/intelligence/mixin_equivalence/test_<plugin>.py` | Migrated plugin numerically identical to legacy (500 bars, 0.1%) | CI per migration |
| `test_executor_pre_validation.py` | Executor skips invalid frames, records warmup_skip | CI |
| `test_emit_signal_validation.py` | emit_signal() raises on invalid, skips empty snapshots | CI |
| `test_plugin_observer.py` | Observer records correct metrics with correct labels | CI |

### Existing Tests (unchanged, remain authoritative)

| Test | Invariant Owned |
|------|----------------|
| `test_plugin_state_contract.py` | _state in compute_next() result |
| `test_plugin_incremental.py` | Numerical equivalence for existing incremental plugins |
| `test_plugin_validator.py` | PluginValidator.validate_all() catches contract violations |

---

## Future Extension Points (out of scope this phase)

1. **Signal quality tier propagation:** `PluginCallResult.used_incremental` → `IntelligenceEvent`
   → I6 confluence weighting. When this ships, `emit_signal()` gains `signal_quality_tier`
   automatically. Design hook is in place.

2. **Per-plugin span tracing:** `observed_span()` inside `PluginObserver.record_result()`
   using existing `ATTR_PLUGIN_NAME` / `ATTR_TIER` constants from spans.py. No new
   infrastructure — just call sites. Low effort follow-on.

3. **PluginObserver pattern replicated upstream:** `SignalObserver`, `FeatureObserver`
   following the same pattern. `src/observability/` becomes the authoritative domain
   for all pipeline observability.
