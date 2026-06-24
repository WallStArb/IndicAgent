---
phase: 139-ensemble-alpha-emission
reviewed: 2026-06-24T00:00:00Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - docs/analysis/ic-discovery-report.json
  - docs/analysis/ic-discovery-report.md
  - production/migrations/168_ensemble_tables.sql
  - production/systemd/indicagent-alpha-emitter.service
  - production/systemd/indicagent-ensemble-builder.service
  - services/alpha_emitter.py
  - services/ensemble_builder.py
  - services/generate_ic_discovery_report.py
  - services/service_auditor.py
  - src/core/stream_keys.py
  - src/intelligence/ensemble/alpha_score.py
  - src/intelligence/ensemble/covariance.py
  - src/intelligence/ensemble/feature_selector.py
  - src/intelligence/ensemble/__init__.py
  - src/intelligence/ensemble/weights.py
  - src/observability/metrics.py
  - tests/unit/test_alpha_emitter.py
  - tests/unit/test_ensemble_builder.py
  - tests/unit/test_ensemble_math.py
findings:
  critical: 4
  warning: 5
  info: 3
  total: 12
status: issues_found
---

# Phase 139: Code Review Report

**Reviewed:** 2026-06-24
**Depth:** standard
**Files Reviewed:** 19
**Status:** issues_found

## Summary

Phase 139 delivers the ensemble weight derivation pipeline (EnsembleBuilder) and alpha emission service (AlphaEmitter) for the v3.0 AlphaEngine. The math library (`src/intelligence/ensemble/`) is clean, correctly structured as pure functions, and well-tested. The migration, service units, and stream key are all correct.

Four blockers were found:

1. `alpha_emitter.py` passes `json.dumps(top_features)` to asyncpg for a JSONB column — the project rule is to pass a plain dict; `json.dumps()` causes asyncpg to insert a JSON-encoded string into JSONB rather than a native JSONB value, which may cause downstream type errors.
2. `alpha_emitter.py` applies the CI gate **before** the threshold gate, but emits a `threshold_miss` rejection reason for zero-score rows that were actually rejected at a completely different logical step. More critically, a row with `alpha_score == 0` is classified as `threshold_miss`, masking zero-score anomalies and making observability data incorrect.
3. `ensemble_builder.py` counter variables `total_weights_written` and `total_alpha_written` are incremented by 1 per stratum regardless of the actual rows written, and are never referenced in the completion log — they are dead tracking variables that obscure how many rows were actually persisted.
4. `alpha_emitter.py` acquires a second pool connection (`async with pool.acquire() as conn:`) inside the Kafka `try/finally` block for the per-row emission loop, but the outer `async with pool.acquire()` block (for the startup queries) already released its connection before the Kafka producer starts. This is fine for correctness but the second connection is held for the entire emission loop of potentially millions of rows, which is a resource correctness risk (connection held for up to 3600s per the systemd `TimeoutStartSec`).

---

## Critical Issues

### CR-01: asyncpg JSONB violation — `json.dumps()` on `top_features` JSONB column

**File:** `services/alpha_emitter.py:332`

**Issue:** The project CLAUDE.md rule states: "asyncpg: JSONB → dict (no json.loads()/json.dumps())". At line 332, `top_features` is passed as `json.dumps(top_features)` to asyncpg for the `alpha_events.top_features` JSONB column. asyncpg handles JSONB natively; passing a JSON string makes asyncpg insert it as a text string, not a native JSONB value. This causes downstream consumers reading `alpha_events.top_features` to receive a string literal instead of a JSONB object, breaking any JSON operators or JSONB indexing on that column.

The comment at line 332 claims `"asyncpg requires json-encoded string for JSONB"` — this directly contradicts the project rule and is incorrect. asyncpg accepts Python dicts directly for JSONB columns.

**Fix:**
```python
# Before (WRONG):
json.dumps(top_features),  # asyncpg requires json-encoded string for JSONB

# After (correct):
top_features,  # asyncpg passes dict → JSONB natively; no json.dumps() needed
```

Also remove the `import json` at line 29 if it is no longer used elsewhere in the file (it is not).

---

### CR-02: Gate order inversion causes incorrect rejection metrics and masks zero-score rows

**File:** `services/alpha_emitter.py:231-260`

**Issue:** The gate order is: zero-weight guard → alpha_score==0 check (labeled `threshold_miss`) → direction determination → CI gate → threshold gate. The problem is twofold:

1. A row with `alpha_score == 0` (line 231) is given rejection reason `threshold_miss` even though it has not been checked against the threshold. Zero alpha score is a distinct condition — a NaN-propagation artifact or upstream scoring bug — and silently counting it as a threshold miss hides data quality issues.

2. The CI gate (line 242-257) runs **before** the threshold gate (line 259-266). For a row with `alpha_ci_lower > 0` (CI pass) but `abs(alpha_score) <= threshold`, the emission loop correctly continues to the threshold gate and rejects. But the ordering makes the threshold gate functionally dead for any row that fails CI, producing confusing metrics where `ci_not_directional` is charged for rows that would also have been `threshold_miss`. The directional character of the signal is the primary gate; threshold magnitude should be checked first to avoid emitting CI calculations for clearly weak signals.

**Fix:** Reorder gates and fix the zero-score reason:
```python
# 1. Zero-score guard (data quality, not threshold miss)
if alpha_score == 0:
    ALPHA_EMITTER_REJECTIONS_TOTAL.add(
        1, {"symbol": symbol, "tf": tf, "rejection_reason": "zero_alpha_score"}
    )
    reject_count += 1
    continue

is_long = alpha_score > 0

# 2. Threshold gate first (cheap, no CI math needed)
threshold = self._threshold_for_tf(tf, cfg)
if abs(alpha_score) <= threshold:
    ALPHA_EMITTER_REJECTIONS_TOTAL.add(
        1, {"symbol": symbol, "tf": tf, "rejection_reason": "threshold_miss"}
    )
    reject_count += 1
    continue

# 3. Direction-aware CI gate (only for rows above threshold)
if is_long:
    ci_pass = alpha_ci_lower > 0
else:
    ci_pass = alpha_ci_upper < 0
...
```

Note: `threshold = self._threshold_for_tf(tf, cfg)` is currently called unconditionally at line 207 (before the zero-weight guard). After the reorder, move it to after the zero-weight and zero-score guards.

---

### CR-03: Dead tracking variables in EnsembleBuilder — written count is always wrong

**File:** `services/ensemble_builder.py:231-232`

**Issue:** `total_weights_written` and `total_alpha_written` are incremented by `+= 1` per stratum regardless of whether any rows were actually written (strata can be skipped by multiple early-return guards at lines 269, 276, 293, 303). The variables are then never referenced in the completion log at line 235, which logs `strata_processed=len(strata_rows)` instead. This means the written-row counts are permanently misleading and provide no diagnostic value if a silent skip cascade occurs.

**Fix:** Either remove the dead variables, or correctly count rows written by capturing the return value of `_process_stratum` (which would need to return `(n_weights, n_alpha)` — currently returns `None`). The simpler fix is to delete the dead variables and add logging inside `_process_stratum` at the actual write sites (which is already done at lines 431 and 481):

```python
# In execute(), remove these two lines:
# total_weights_written += 1   # DEAD — always wrong count
# total_alpha_written += 1     # DEAD — always wrong count

# And update the completion log to reflect strata attempted vs completed:
self.logger.info(
    "ensemble_builder.complete",
    strata_found=len(strata_rows),
    # Per-stratum write counts already logged by _process_stratum
)
```

---

### CR-04: `alpha_emitter.py` passes the pool connection incorrectly across a yield boundary

**File:** `services/alpha_emitter.py:179-369`

**Issue:** The pool connection used for the startup queries (loading APR, weight cache, and alpha rows) is acquired and released in the first `async with pool.acquire() as conn:` block (lines 118-177). That block exits before the Kafka producer is started. Then a second `async with pool.acquire() as conn:` block (lines 195-334) is used for the per-row `INSERT INTO alpha_events`. This second connection is held open while iterating over potentially millions of `alpha_rows` and making a Kafka publish call **inside the loop** (`await self._producer.publish()`).

The `publish()` call is awaited inside the connection-held context. If the Kafka broker is slow or stalls, this holds the asyncpg connection (which is a pool resource) for the full duration. For the 4-symbol validation corpus the discovery report shows 2.8M events, meaning this connection is held while making 2.8M Kafka calls with no batch or flush boundary. The `TimeoutStartSec=3600` in the systemd unit acknowledges this may run for an hour, making the resource hold a correctness risk for pool exhaustion if any other process needs a connection from the same pool.

**Fix:** Batch the DB inserts separately from Kafka publishes, or at minimum use `executemany` for the inserts in batches and publish to Kafka after the DB transaction commits:

```python
# Collect all qualifying events first, then batch-insert, then publish
qualifying = []
for row in alpha_rows:
    # ... gate logic ...
    qualifying.append((event_id, ..., top_features))  # no json.dumps

# Batch insert
async with pool.acquire() as conn:
    await conn.executemany("INSERT INTO alpha_events ...", qualifying)

# Publish to Kafka after DB commit (Kafka is transport, not state)
for event in qualifying:
    await self._producer.publish(topic, msg=event["payload"])
```

---

## Warnings

### WR-01: `ensemble_builder.py` column order mismatch in `ensemble_weights` INSERT

**File:** `services/ensemble_builder.py:421-429`

**Issue:** The INSERT at line 421 specifies columns in this order:
`symbol, tf, regime, weight_version, feature_name, raw_weight, weight, ic_sharpe, lookahead_bars, effective_n, computed_at`

The `weight_rows` tuple at lines 403-417 is built as:
`(symbol, tf, regime, weight_version, ordered_names[i], float(raw_weights[i]), float(weights[i]), float(ic_sharpes[i]), lookahead_bars[i], eff_n)`

Then `[(*row, now) for row in weight_rows]` appends `now` as the 11th element.

This matches. However, the migration DDL at line 45 has column order:
`symbol, tf, regime, weight_version, feature_name, ic_sharpe, raw_weight, weight, lookahead_bars, effective_n, computed_at`

Note that in the DDL `ic_sharpe` comes before `raw_weight`, but in the INSERT statement the column list explicitly names them — so this is positional-to-named and is correct. However, this is fragile: if the column order is inferred from the values rather than the explicit list, it would silently swap `ic_sharpe` and `raw_weight`. Add a comment citing that the INSERT column list is authoritative.

**Fix:** The code is currently correct (named columns in INSERT). Add a comment noting the DDL column order differs from INSERT order to avoid future confusion:

```python
# NOTE: INSERT column order differs from DDL definition order — this is intentional.
# The INSERT explicitly names columns so positional order in the tuple does not matter.
await conn.executemany(
    """
    INSERT INTO ensemble_weights
        (symbol, tf, regime, weight_version, feature_name,
         raw_weight, weight, ic_sharpe, lookahead_bars, effective_n, computed_at)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
    ...
    """,
```

---

### WR-02: `alpha_emitter.py` missing connection pool context for second `conn.execute` — connection shared across Kafka yield

**File:** `services/alpha_emitter.py:194-369`

**Issue:** The `conn.execute` at line 303 (inside the per-row loop) executes each alpha event INSERT as an individual statement with no explicit transaction. For 2.8M rows this means 2.8M individual auto-committed INSERTs, which will be orders of magnitude slower than a batched `executemany`. The EnsembleBuilder correctly uses `executemany` for its bulk inserts; the AlphaEmitter should do the same.

Beyond performance, individually auto-committed INSERTs means a failure mid-run leaves a partial state in `alpha_events` with no way to distinguish "run failed at row N" from "run completed normally". The `ON CONFLICT DO NOTHING` makes re-runs safe, but a partial run wastes compute on the next run as it must re-evaluate all previously emitted events.

**Fix:** Collect qualifying rows and emit using `executemany` in a single transaction:
```python
# Collect all qualifying inserts first (keeps Kafka publish separate from DB)
insert_rows = []
for row in alpha_rows:
    # ... gate logic, top_features build ...
    insert_rows.append((event_id, symbol, tf, bar_ts, ..., top_features, now))

async with pool.acquire() as conn:
    await conn.executemany("INSERT INTO alpha_events (...) VALUES (...)", insert_rows)
```

---

### WR-03: CI independence assumption sentinel not enforced at runtime

**File:** `services/alpha_emitter.py:119-131`

**Issue:** The migration seeds `alpha.ensemble.ci_independence_assumption = 'acknowledged'` and the APR description says "The value 'acknowledged' must be present for the alpha emitter to proceed." But `alpha_emitter.py` never checks this key. The APR is loaded (line 120) but the sentinel is not read or validated. A misconfigured environment where the key is absent (e.g., after a migration rollback) would silently proceed with CI gates and emit events whose CI bounds are undefined.

**Fix:**
```python
ci_assumption = _cfg_str(cfg, "alpha.ensemble.ci_independence_assumption", "")
if ci_assumption != "acknowledged":
    raise RuntimeError(
        "AlphaEmitter: alpha.ensemble.ci_independence_assumption must be 'acknowledged' "
        f"before emitting CI-gated alpha events. Got: {ci_assumption!r}. "
        "Set this APR key to confirm that independent IC estimation error assumption is accepted."
    )
```

---

### WR-04: `generate_ic_discovery_report.py` calls `setup_service_logging()` at module level

**File:** `services/generate_ic_discovery_report.py:40`

**Issue:** `setup_service_logging("logs/generate_ic_discovery_report.log")` is called at module import time (line 40), outside any function. This means importing the module (e.g., from a test) creates/opens the log file as a side effect. This is an anti-pattern in the codebase — other services call `setup_service_logging` inside `main()` or `__init__`. The impact is low for a read-only report generator but inconsistent.

**Fix:** Move the call inside `main()`:
```python
async def main() -> None:
    setup_service_logging("logs/generate_ic_discovery_report.log")
    _logger.info("generate_ic_discovery_report.start")
    ...
```

---

### WR-05: `ensemble_builder.py` does not guard against NaN/Inf in feature matrix before matmul

**File:** `services/ensemble_builder.py:337-340`

**Issue:** At line 337-340, `None` values in feature_vectors rows are replaced with `0.0` but no NaN or Inf check is performed on the float values themselves. If the database contains `NaN` or `Inf` in a numeric column (possible from upstream feature computation bugs or overflow), `X @ signed_weights` at line 440 will produce `NaN` alpha scores silently. These NaN scores would then be compared against the CI lower/upper bounds in the AlphaEmitter, where `float(row["alpha_ci_lower"])` would be NaN, causing all CI comparisons to evaluate to False (NaN comparisons always False in Python), and the row would be silently rejected at the CI gate with no diagnostic log about why.

**Fix:** Add a NaN/Inf clamp after building `X_raw`:
```python
X_raw = np.array(
    [[float(r[c]) if r[c] is not None else 0.0 for c in col_subset] for r in fv_rows],
    dtype=float,
)
# Guard against NaN/Inf from upstream feature computation bugs
if not np.all(np.isfinite(X_raw)):
    n_nonfinite = int(np.sum(~np.isfinite(X_raw)))
    log.warning(
        "ensemble_builder.nonfinite_feature_values",
        n_nonfinite=n_nonfinite,
        symbol=symbol, tf=tf, regime=regime,
    )
    X_raw = np.where(np.isfinite(X_raw), X_raw, 0.0)
```

The pure function `compute_alpha_score` in `alpha_score.py` already does this guard for its input, but `ensemble_builder.py` uses the raw matmul `X @ signed_weights` at line 440, bypassing that protection.

---

## Info

### IN-01: `ALPHA_EMITTER_EMISSIONS_TOTAL` uses `up_down_counter` instead of `counter`

**File:** `src/observability/metrics.py:1179-1199`

**Issue:** `ALPHA_EMITTER_EMISSIONS_TOTAL`, `ALPHA_EMITTER_BARS_SCORED_TOTAL`, and `ALPHA_EMITTER_REJECTIONS_TOTAL` are declared as `_meter.create_up_down_counter(...)`. Emission and rejection counts are monotonically increasing (oneshot batch run totals) — they should be `Counter` instruments, not `UpDownCounter`. An `UpDownCounter` signals to OTel collectors that the value can decrease, which disables rate/delta alerting in Prometheus/Grafana. The correct instrument for "cumulative count per batch run" is `Counter` (`.add(1, attrs)` with no negative values).

**Fix:**
```python
ALPHA_EMITTER_EMISSIONS_TOTAL = _meter.create_counter(
    "alpha_emitter_emissions_total",
    description="...",
)
ALPHA_EMITTER_BARS_SCORED_TOTAL = _meter.create_counter(
    "alpha_emitter_bars_scored_total",
    description="...",
)
ALPHA_EMITTER_REJECTIONS_TOTAL = _meter.create_counter(
    "alpha_emitter_rejections_total",
    description="...",
)
```

---

### IN-02: Test coverage gap — `EnsembleBuilder._process_stratum` not tested

**File:** `tests/unit/test_ensemble_builder.py`

**Issue:** `test_ensemble_builder.py` only tests the class contract and import structure. The core logic in `_process_stratum` — feature ordering, matmul, CI margin computation, and the early-return guards (insufficient columns, min_passing_features, zero weight vector) — has no unit test coverage. The math library tests in `test_ensemble_math.py` cover the pure functions, but the integration of those functions inside `_process_stratum` (particularly the column reordering at lines 310-316 and ordered index mapping at lines 343-344) is not tested.

**Fix:** Add at minimum one integration-level test that calls `_process_stratum` with a mocked asyncpg connection returning synthetic IC scores and feature vectors, and asserts that `conn.executemany` was called with the correct number of weight rows and alpha rows.

---

### IN-03: `cluster_deflate_weights` test documents confusing "no-op on whole-ensemble cluster" behavior without asserting the meaningful invariant

**File:** `tests/unit/test_ensemble_math.py:299-333`

**Issue:** The test `test_deflates_highly_correlated_cluster` correctly notes that when the entire weight vector is one cluster, deflation + renorm produces the same weights as input (the relative ratio is preserved). The test asserts the ratio is preserved but does not assert that a 3-feature ensemble where only 2 features form a cluster correctly shows the cluster total being reduced. This is already covered by `test_deflates_cluster_leaves_non_cluster_features_intact`, but the first test's comment block is misleading — it states "deflation constrains the cluster's absolute share" while the output is identical to the input. The comment may lead future maintainers to believe a two-feature cluster is always reduced in isolation.

**Fix:** Add a comment clarifying the semantics, and optionally add a test asserting that a cluster that is a strict subset of a larger ensemble has its share genuinely reduced (which `test_deflates_cluster_leaves_non_cluster_features_intact` already covers — this is low priority).

---

_Reviewed: 2026-06-24_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
