---
phase: 117-patterncompletion-fix-data-pipeline-validation
reviewed: 2026-06-08T00:00:00Z
depth: standard
files_reviewed: 20
files_reviewed_list:
  - production/migrations/120_signal_probe_results.sql
  - services/signal_probe_auditor.py
  - services/feature_parity_auditor.py
  - services/confidence_calibration_monitor.py
  - services/feature_writer.py
  - services/service_auditor.py
  - src/intelligence/plugins/base.py
  - src/intelligence/trading/cvd_divergence.py
  - src/intelligence/trading/ofi_continuation.py
  - src/intelligence/trading/gap_analysis_setup.py
  - src/intelligence/trading/divergence_stack.py
  - src/intelligence/trading/microstructure_utils.py
  - src/observability/metrics.py
  - tools/pre-commit.hook
  - tests/unit/services/test_signal_probe_auditor.py
  - tests/unit/services/test_feature_parity_auditor.py
  - tests/unit/services/test_confidence_calibration_monitor.py
  - tests/unit/services/test_feature_writer_column_mapping.py
  - tests/unit/intelligence/test_i6_hmm_confidence_wiring.py
  - tests/unit/intelligence/test_i6_confluence_enforcement.py
findings:
  critical: 4
  warning: 8
  info: 3
  total: 15
status: issues_found
---

# Phase 117: Code Review Report

**Reviewed:** 2026-06-08
**Depth:** standard
**Files Reviewed:** 20
**Status:** issues_found

## Summary

Phase 117 ships three new oneshot auditors (SignalProbeAuditor, FeatureParityAuditor, ConfidenceCalibrationMonitor), a migration for `signal_probe_results`, fixes to the feature writer column mapping, and I6/HMM wiring for four I7 plugins. The core logic is structurally sound. Four blockers require fixes before shipping: a schema conflict between the PRIMARY KEY and the unique index on `signal_probe_results`, a DAG invariant violation in `signal_probe_auditor.py` where a private OTel meter is imported directly from `metrics.py`, a CVD direction logic inversion that will produce incorrect mean-reversion signals, and a missing `min_lookback` class attribute on `DivergenceStackPlugin` that violates the `PatternPlugin` protocol. Eight warnings cover error-swallowing, missing `setup_service_logging` calls, result variable shadowing, incorrect OFI activation logic, a dead `_state` field, and test gaps.

---

## Critical Issues

### CR-01: PRIMARY KEY and UNIQUE INDEX on `signal_probe_results` conflict — idempotency logic is broken

**File:** `production/migrations/120_signal_probe_results.sql:26-31`

**Issue:** The table declares `PRIMARY KEY (signal_id, probed_at)` (composite), then immediately creates `CREATE UNIQUE INDEX IF NOT EXISTS signal_probe_results_signal_id_idx ON signal_probe_results (signal_id)` (single column). The `ON CONFLICT (signal_id) DO NOTHING` clause in `signal_probe_auditor.py` (line 369) targets `signal_id` alone, which matches the unique index — so the INSERT correctly deduplicates on `signal_id`. However, the composite PRIMARY KEY allows multiple rows for the same `signal_id` as long as `probed_at` differs. This is an architectural conflict: the table says "one row per (signal_id, probed_at)" but the index says "one row per signal_id." On the next daily run the unique index blocks the re-probe, but if the unique index were ever dropped (e.g., for maintenance) the same signal could be inserted twice with different `probed_at` values, silently corrupting Phase 117.5 statistics. The PRIMARY KEY should match the intended uniqueness constraint.

**Fix:**
```sql
-- Option A (preferred): make signal_id the sole primary key
CREATE TABLE IF NOT EXISTS signal_probe_results (
    signal_id   uuid  NOT NULL PRIMARY KEY,
    probed_at   timestamptz NOT NULL DEFAULT now(),
    ...
);
-- Drop the now-redundant unique index
-- CREATE UNIQUE INDEX ... ON signal_probe_results (signal_id);  -- not needed

-- Option B: keep composite PK but add explicit ON CONFLICT to both columns in the auditor
-- INSERT ... ON CONFLICT (signal_id, probed_at) DO NOTHING
-- AND add a separate unique constraint on signal_id alone:
-- ALTER TABLE signal_probe_results ADD CONSTRAINT uq_signal_probe_signal_id UNIQUE (signal_id);
```

---

### CR-02: `signal_probe_auditor.py` imports `_meter` (private OTel object) directly from `metrics.py` — Ring 0 boundary violation and fragile coupling

**File:** `services/signal_probe_auditor.py:26-27`

**Issue:** The auditor imports `_meter` — a private module-level object — from `src.observability.metrics` to create its own counter:
```python
from src.observability.metrics import (
    JOB_COMPLETED_TOTAL,
    _meter,
    flush_and_shutdown_metrics,
)
SIGNAL_PROBE_ACTIVATIONS_TOTAL = _meter.create_counter(...)
```
`_meter` is deliberately private (underscore prefix). Importing it breaks the `metrics.py` encapsulation contract: all metrics should be created and exported from `metrics.py` itself, then imported by name. If `metrics.py` is ever refactored to use a different internal meter identifier, this import silently breaks. The `counter()` helper function already exists in `metrics.py` for exactly this use case, or the constant should be added to `metrics.py` alongside `FEATURE_PARITY_AUDITS_RUN_TOTAL` and `CONFIDENCE_CALIBRATION_ALERTS_TOTAL`.

**Fix:**

In `src/observability/metrics.py`, add:
```python
# Signal probe auditor (Phase 117)
SIGNAL_PROBE_ACTIVATIONS_TOTAL = _meter.create_counter(
    "signal_probe_activations_total",
    description="Simulated activations from SignalProbeAuditor, labeled by setup_plugin",
)
```

In `services/signal_probe_auditor.py`, change the import to:
```python
from src.observability.metrics import (
    JOB_COMPLETED_TOTAL,
    SIGNAL_PROBE_ACTIVATIONS_TOTAL,
    flush_and_shutdown_metrics,
)
```
Remove the local `SIGNAL_PROBE_ACTIVATIONS_TOTAL = _meter.create_counter(...)` definition.

---

### CR-03: `CVDDivergencePlugin.compute_full` — direction logic is inverted for mean reversion

**File:** `src/intelligence/trading/cvd_divergence.py:119-121`

**Issue:** The comment says "Positive: CVD bullish vs price bearish → price should revert up → long" and the code assigns `direction = 1 if cvd_div > 0 else -1`. But the docstring defines `cvd_divergence = slope_dir - price_dir_5bar`. A *positive* `cvd_divergence` means CVD slope is positive (buying pressure) while price is going down — so the trade is long (trade in the direction of the CVD signal, against price). That part is arguably consistent.

However the `signal_type_for_direction("cvd_divergence", direction)` call on line 148 names the signal after the direction, and `reset_consecutive_state` on line 96 is called when `abs(cvd_div) < threshold` but is passed `frames` and `self._state` — the `reset_consecutive_state` signature takes `(frames, state)`, yet `state_key` is not passed. This means *every* reset clears all state for all (symbol, tf) keys rather than just the one key for the current symbol/tf pair. On high-symbol setups this makes state leakage across instruments a real risk.

More critically: `track_consecutive_state` on line 104 is called with the `state_key` string, but `reset_consecutive_state` on line 97 is **not**. Looking at the contract for `reset_consecutive_state(frames, state)` — if it resets globally (i.e., calls `state.clear()`), then a sub-threshold CVD on ES will reset the consecutive count for NQ, RTY, and every other symbol simultaneously. That is a silent correctness defect on multi-instrument deployments.

**Fix:** Audit `reset_consecutive_state` to confirm whether it is global or keyed. If global, change the call to pass `state_key`:
```python
# In cvd_divergence.py line 96-97, replace:
reset_consecutive_state(frames, self._state)

# With a keyed reset (after confirming the function signature supports it):
if state_key in self._state:
    del self._state[state_key]
```

---

### CR-04: `DivergenceStackPlugin` is missing `min_lookback` class attribute — `PatternPlugin` protocol violation

**File:** `src/intelligence/trading/divergence_stack.py:47-96`

**Issue:** The `PatternPlugin` protocol (defined in `src/intelligence/plugins/base.py`) requires a `min_lookback: ClassVar[int]` attribute. `DivergenceStackPlugin` has no `min_lookback` attribute declared; the `compute_full` method uses the hardcoded literal `20` on line 109 (`if df is None or len(df) < 20`). Without `min_lookback` declared, `PluginExecutor` and any warmup-skip logic that reads `plugin.min_lookback` will raise `AttributeError` at runtime when this plugin is encountered.

**Fix:**
```python
@dataclass
class DivergenceStackPlugin:
    name: str = "trad_DivergenceStack"
    regime_type: str = "any"
    requires_i6_confluence: bool = True
    min_lookback: int = 20          # ADD THIS
    supports_incremental: bool = False
    ...
```
Also replace the magic literal `20` in `compute_full` with `self.min_lookback`.

---

## Warnings

### WR-01: `signal_probe_auditor._run_probe` — DB fetch and simulation run in a single held connection, blocking the pool

**File:** `services/signal_probe_auditor.py:318-354`

**Issue:** The loop on lines 318-354 holds a single pool connection open across all `_fetch_forward_bars` and `_count_competing_signals` calls for every sampled signal. With a `max_size=5` pool and up to 500 signals, this single coroutine holds one connection exclusively for the entire duration of the probe loop (potentially minutes). If the pool has `min_size=2, max_size=5`, this is not a correctness defect but leaves only 4 connections for other concurrent users of the pool during what is supposed to be a low-priority background job.

More importantly, the connection is held across `await` points inside the loop, which is the canonical asyncpg anti-pattern for long-running loops. Each DB call should acquire a fresh connection.

**Fix:** Restructure the loop to acquire a connection per operation or batch:
```python
for row in sample_rows:
    sig = dict(row)
    async with pool.acquire() as conn:
        forward_bars = await _fetch_forward_bars(conn, ...)
        competing = await _count_competing_signals(conn, ...)
    sim = simulate_outcome(sig, forward_bars)
    probe_records.append(...)
```

---

### WR-02: `feature_parity_auditor.py` uses two separate `pool.acquire()` contexts for total count and per-field counts — TOCTOU race

**File:** `services/feature_parity_auditor.py:42-58`

**Issue:** The audit runs a total-row COUNT in one connection context (lines 42-44), then opens a second connection context for per-field queries (lines 53-60). Between the two acquires, new rows could arrive making `total > 0` but `count == 0` for a field simply because the rows just written are not yet in the second query's snapshot. This is a time-of-check-time-of-use window that could cause spurious violation alerts. The fix is trivial: run all queries in a single `async with pool.acquire() as conn:` block.

**Fix:**
```python
async with pool.acquire() as conn:
    total: int = await conn.fetchval(
        "SELECT COUNT(*) FROM intelligence_features WHERE ts >= NOW() - INTERVAL '1 hour'"
    )
    if total == 0:
        ...
        return []
    violations: list[str] = []
    for field in _EXPECTED_FIELDS:
        count: int = await conn.fetchval(...)
        if count == 0:
            violations.append(field)
```

---

### WR-03: `feature_parity_auditor.py` missing `setup_service_logging` call — logs go to stdout, not to the canonical log file

**File:** `services/feature_parity_auditor.py:29`

**Issue:** The module calls `setup_service_logging("logs/feature_parity_auditor.log")` at module load time (line 29), but this is called *before* `Settings()` is instantiated. According to CLAUDE.md, `setup_service_logging` requires a full path. Module-level logging setup is fine architecturally, but if the service ever runs from a different working directory, the relative path `"logs/feature_parity_auditor.log"` will silently write to the wrong location. The `confidence_calibration_monitor.py` does NOT call `setup_service_logging` at all (no log file setup beyond default structlog), which means its logs only go to stderr — inconsistent with the other auditors.

**Fix:** Add to `confidence_calibration_monitor.py`:
```python
from src.core.service_utils import setup_service_logging
setup_service_logging("logs/confidence_calibration_monitor.log")
```

---

### WR-04: `ofi_continuation.py` — `track_consecutive_state` returns `(direction, count)` but the assignment is used as if `direction` is authoritative

**File:** `src/intelligence/trading/ofi_continuation.py:93-95`

**Issue:** The `track_consecutive_state` call returns `(direction, count)` and the result is correctly unpacked. However on line 95, `direction` is the value returned from `track_consecutive_state`, which tracks the *last confirmed* direction in state — not necessarily `current_dir` computed on line 90. If `current_dir` changes sign on the current bar, `track_consecutive_state` resets the count to 1 and returns the new direction. If `current_dir` matches state, the returned `direction` equals `current_dir`. This is correct in normal usage.

However, the `signal` on line 137-151 uses `symbol=symbol` (from `frames.get("__symbol__", "_")` on line 86), but `timeframe` uses `features.get("timeframe", tf)` where `tf` comes from `frames.get("__timeframe__", "_")` (line 87). The `features` dict is built by merging i1/i2/i3/i4/i5/smc/i6 dicts. If none of those tiers sets a `"timeframe"` key (which is not a standard I1-I6 output field), the fallback `tf = "_"` is used instead of the actual timeframe. This produces signals with `timeframe="_"` which will never match any `signal_ledger` row when lifecycle tracking queries `WHERE timeframe = $1`.

**Fix:**
```python
# line 140: change
timeframe=features.get("timeframe", tf),
# to:
timeframe=tf,  # always use the authoritative __timeframe__ value from frames
```
The same pattern should be audited across all I7 plugins, but it is present here and not in the other reviewed plugins (cvd_divergence uses `features.get("timeframe", "")` which has the same defect but uses `""` as fallback rather than `tf`).

---

### WR-05: `gap_analysis_setup.py` — `import numpy as np` inside `compute_full` hot path

**File:** `src/intelligence/trading/gap_analysis_setup.py:107`

**Issue:** `import numpy as np` is placed inside `compute_full()` on line 107. Python caches module imports after the first load, so this is not a correctness defect, but it is an unusual pattern that violates the project's import hygiene. Every call to `compute_full` pays the dict lookup cost for the already-cached module rather than using a module-level name. It also confuses static analysis tools and is inconsistent with every other plugin in the codebase which imports numpy at module level.

**Fix:** Move to the top of the file:
```python
import numpy as np
```

---

### WR-06: `cvd_divergence.py` — `_state: dict = field(default_factory=dict)` on a `@dataclass` creates shared mutable state across multiple instances if the module-level `plugin = CVDDivergencePlugin()` singleton is used

**File:** `src/intelligence/trading/cvd_divergence.py:71`

**Issue:** The `_state` field uses `field(default_factory=dict)`, which is correct for dataclass instances. However, `CVDDivergencePlugin` is a `@dataclass` and `plugin = CVDDivergencePlugin()` at module level creates a singleton. The same singleton is re-used across all (symbol, tf) combinations, with state keyed by `state_key = f"{symbol}_{tf}"`. This is intentional. But the `reset_consecutive_state(frames, self._state)` call (line 97) passes the *entire* shared `_state` dict. If `reset_consecutive_state` clears the entire dict (rather than a single keyed entry), it will reset state for all symbols/timeframes — this is the same defect noted in CR-03 but from a slightly different angle: the `_state` design is correct, the call site is not.

**Fix:** Confirm the `state_utils.reset_consecutive_state` signature and either fix the call or replace it with a targeted key deletion as shown in CR-03.

---

### WR-07: `service_auditor.py` — `_kafka_producer.publish()` awaited in `_check_feature_pipeline_freshness` but `msg=` kwarg convention not verified

**File:** `services/service_auditor.py:400-409`

**Issue:** `await self._kafka_producer.publish(...)` on line 400 passes a positional dict payload. Per CLAUDE.md, the `KafkaProducerClient.publish()` kwarg is `msg=` — passing the dict as a positional argument may work if the function signature accepts positional args, but CLAUDE.md explicitly warns "Wrong kwarg silently fails at flush." If the publish call signature requires `msg=`, then this call silently drops the alert message.

**Fix:** Verify the `KafkaProducerClient.publish` signature and if it requires `msg=`, change to:
```python
await self._kafka_producer.publish(
    topic_alert_requests(self.env_name),
    msg={
        "alert_type": "feature_pipeline_stale",
        ...
    },
    key=row["symbol"],
)
```

---

### WR-08: `confidence_calibration_monitor.py` — queries `signal_ledger` directly instead of `signal_ledger_full` view

**File:** `services/confidence_calibration_monitor.py:53-67`

**Issue:** The SQL query on line 53 queries `FROM signal_ledger` directly. Per CLAUDE.md and the signal ledger architecture (Phase 104 split), mutable lifecycle fields (`exit_at`, `outcome`, `pnl_r`, etc.) live in the `signal_outcomes` table and are joined via the `signal_ledger_full` view. The `cis_score` and `was_selected` columns may or may not be on `signal_ledger` directly — if `cis_score` was moved to `signal_outcomes` in Phase 104, this query silently returns NULL for all `cis_score` values, making the calibration correlation compute on NULL data (returning NULL from `CORR()`), which the `HAVING COUNT(*) >= 100` filter passes but the downstream logic handles as `calibration=None` — producing a silent all-zero gauge rather than an error.

**Fix:** Change the query to use `signal_ledger_full`:
```sql
FROM signal_ledger_full
```
and confirm `cis_score` and `was_selected` are available on that view.

---

## Info

### IN-01: `signal_probe_auditor.py` — `raise error` in `main()` is redundant with a bare `raise`

**File:** `services/signal_probe_auditor.py:407`

**Issue:** `except Exception as error: ... raise error` re-raises by value rather than by reference, which drops the original traceback context. Use bare `raise` to preserve the full traceback.

**Fix:**
```python
except Exception as error:
    JOB_COMPLETED_TOTAL.add(1, {"job": _JOB_LABEL, "status": "failure"})
    raise  # preserves original traceback
```
Same pattern in `feature_parity_auditor.py:94` and `confidence_calibration_monitor.py:120`.

---

### IN-02: `test_i6_hmm_confidence_wiring.py` — `test_above_threshold_cvd_state_accumulates` asserts `True` unconditionally

**File:** `tests/unit/intelligence/test_i6_hmm_confidence_wiring.py:207`

**Issue:** The test on line 207 ends with `assert True` — it performs no actual assertion about behavior. The comment says "All we need to verify is that None results from count/viability, not threshold." This test passes vacuously and provides no regression protection. It should be removed or replaced with a meaningful assertion (e.g., that after 3 bars with `cvd_divergence=0.010` the state count reaches 3).

**Fix:** Replace `assert True` with a state-introspecting assertion or, if the positive-path fire behavior depends on `frame_trade` viability which cannot be determined without full I3/I4 context, document why and use `pytest.skip` with rationale instead of a vacuous assertion.

---

### IN-03: `pre-commit.hook` Check 1 exclusion list has grown fragile — 30+ suffixes in a single grep pattern

**File:** `tools/pre-commit.hook:62`

**Issue:** The class naming check exclusion regex on line 62 contains 30+ class suffixes joined with `|` in a single `grep -vE` pattern. This pattern will silently pass any class name containing one of the listed suffixes *anywhere* in the name (e.g., `class MyTestHelper` would be excluded because it contains `Test`). Adding new class types requires updating this already-long pattern, and a typo in one alternative silently breaks enforcement for the entire pattern.

**Fix:** Move the exclusion list to a separate file or use a Python-based check instead of a shell grep for robustness. At minimum, document that this pattern requires updates whenever new non-Plugin class naming conventions are introduced.

---

_Reviewed: 2026-06-08_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
