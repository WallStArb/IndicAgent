---
phase: 126-signal-universe-hardening
reviewed: 2026-06-15T00:00:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - production/scripts/signal_quality_audit.py
  - src/intelligence/pipeline/signal_processor.py
  - src/intelligence/plugins/base.py
  - src/intelligence/register_plugins.py
  - src/intelligence/schemas.py
  - src/intelligence/trading/choch_reversal.py
  - src/intelligence/trading/confidence_utils.py
  - src/intelligence/trading/fvg_fill.py
  - src/intelligence/trading/liquidity_sweep_reclaim.py
  - src/intelligence/trading/mean_reversion.py
  - src/intelligence/trading/signal_schema.py
  - src/intelligence/trading/supply_demand_setup.py
  - src/intelligence/trading/trade_framer.py
  - src/intelligence/trading/trend_following.py
  - tests/unit/intelligence/test_pipeline_annotation.py
  - tests/unit/intelligence/test_zone_width_gate.py
findings:
  critical: 2
  warning: 5
  info: 3
  total: 10
status: issues_found
---

# Phase 126: Code Review Report

**Reviewed:** 2026-06-15
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Phase 126 delivers five interlocking changes: (1) zone width gate (D-01) in `frame_trade()` rejecting sub-ATR zones; (2) extrinsic annotation moved from per-plugin `capture_signal_features()` to pipeline-layer `_annotate_signal()`; (3) `shadow_only=True` applied to five statistically anti-predictive plugins; (4) APR seeds for zone engine thresholds and signal audit thresholds; (5) a two-layer IC audit script.

The core logic is sound. Two blockers require attention: a stale-reference bug where all signals in a bar share a single mutable `context_features` dict object, and a wrong table name in the audit script that queries a deprecated schema. Five warnings cover correctness gaps in verdict logic, empty string fields in one plugin, a comment/header mismatch in a migration, a duplicate docstring param in `confidence_utils.py`, and missing `valid_asset_classes` attributes on all reviewed plugins.

---

## Critical Issues

### CR-01: All signals in a bar share one mutable `context_features` dict (aliasing bug)

**File:** `src/intelligence/pipeline/signal_processor.py:93`

**Issue:** `_annotate_signal()` assigns `sig["context_features"] = flat_features` — a direct reference, not a copy. When multiple signals fire on the same bar, every call to `_annotate_signal` overwrites `sig["context_features"]` on all previously annotated signals with the same dict object. Any downstream code that adds a per-signal key to `context_features` (e.g., a future annotator or the Kafka serializer) will mutate that single shared object and corrupt all signals simultaneously. The test `test_annotate_sets_context_features_to_full_snapshot` asserts `sig["context_features"] is ff` — this validates the aliasing is intentional but does not test the multi-signal mutation path.

This is currently latent because nothing modifies `context_features` after annotation. The moment any future annotator or middleware adds a per-signal key (likely in Phase 127/128 when signal_events adds per-signal context fields), all signals on the same bar will silently carry corrupted context.

**Fix:** Use a shallow copy:
```python
def _annotate_signal(sig: dict, flat_features: dict) -> None:
    sig["context_features"] = dict(flat_features)  # shallow copy — prevents aliasing across signals
    ...
```
Update `test_annotate_sets_context_features_to_full_snapshot` to assert equality (`==`) not identity (`is`).

---

### CR-02: Audit script queries `signal_ledger`+`signal_outcomes` — wrong schema for Phase 126

**File:** `production/scripts/signal_quality_audit.py:252-265`

**Issue:** Layer 1 SQL joins `signal_ledger` to `signal_outcomes` (a two-table pre-Phase-128 schema). Per CLAUDE.md, Phase 128+ uses the 3-table architecture: `signal_events` / `trade_frames` / `trade_executions`, with backward-compat view `signal_ledger_v2`. The audit script's SQL `FROM signal_ledger sl LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id` will either fail at runtime (if `signal_outcomes` has already been replaced by Phase 128 migration) or silently return rows from a deprecated table.

The same applies to the Layer 2 sample query at line 400 which joins `signal_ledger sl JOIN intelligence_features f`. If `signal_ledger` was dropped in Phase 129 (per the CLAUDE.md note: "`signal_ledger` — legacy monolith (read-only during v2.10 migration; dropped in Phase 129)"), this script will throw at runtime.

The script header comment at line 239 says "uses signal_ledger + signal_outcomes join via signal_ledger_full view" but the SQL itself does not use the view — it directly queries the tables.

**Fix:** Replace direct table queries with the backward-compat view:
```sql
-- Layer 1: use signal_ledger_v2 for Phase 128+ compatibility
FROM signal_ledger_v2 sl
-- pnl_r lives on trade_frames in 3-table schema
WHERE sl.counterfactual_pnl_r IS NOT NULL
```
Or gate the query on which schema exists, matching the 3-table field names (`counterfactual_pnl_r` on `trade_frames`, `raw_confidence` on `signal_events`).

---

## Warnings

### WR-01: Layer 1 verdict logic has inverted threshold variable name for ANTI-SIGNAL CI check

**File:** `production/scripts/signal_quality_audit.py:301-304`

**Issue:** The verdict logic at line 301-303:
```python
if ic is not None and ic < ic_anti_signal_ceil:
    verdict = "ANTI-SIGNAL"
elif ci_upper < hit_rate_anti_ceil:
    verdict = "ANTI-SIGNAL"
```
`ic_anti_signal_ceil` is loaded from APR key `threshold.signal_audit.ic_anti_signal_ceiling` with default `-0.02`. The variable name uses `_ceil` but stores the ceiling for ANTI-SIGNAL classification (the lower bound, a negative number). `hit_rate_anti_ceil` is loaded from `threshold.signal_audit.hit_rate_anti_signal_ceiling` with default `0.45`. These names are semantically inverted from their use:
- `ic_anti_signal_ceil = -0.02` is a ceiling but is used as `ic < -0.02` — so it is actually a floor (anything below -0.02).
- The D-13 design doc calls the hit_rate threshold the "CI upper bound below 0.45" check, but the variable is named `hit_rate_anti_ceil` and used as `ci_upper < 0.45`.

The variable naming makes the ANTI-SIGNAL condition for `ci_upper` appear to use the same threshold as VALIDATED (`hit_rate_valid_floor = 0.45`). Both `hit_rate_valid_floor` and `hit_rate_anti_ceil` default to `0.45`, making any plugin with `ci_upper < 0.45` simultaneously qualify as ANTI-SIGNAL — before even reaching the VALIDATED check. This means no plugin can be VALIDATED if `ci_upper < hit_rate_valid_floor` (same 0.45), because the ANTI-SIGNAL branch fires first.

Per D-13 in the audit results doc: `ANTI-SIGNAL: hit_rate CI upper < 0.45`. The logic is functionally correct (ANTI-SIGNAL fires first when `ci_upper < 0.45`), but the variable naming and ordering make it easy to misread the intent. More critically, if an operator lowers `hit_rate_anti_signal_ceiling` below `hit_rate_validated_floor`, the ANTI-SIGNAL CI check would become more lenient than the VALIDATED check — silently producing NOISE CANDIDATE verdicts for genuinely anti-predictive plugins.

**Fix:** Rename to clarify intent, and add a startup assertion:
```python
hit_rate_anti_signal_ci_upper_max = await cfg.get("threshold.signal_audit.hit_rate_anti_signal_ceiling", 0.45)
# Assert thresholds are consistent: anti ceiling must equal or exceed validated floor
assert hit_rate_anti_signal_ci_upper_max <= hit_rate_valid_floor, (
    "hit_rate_anti_signal_ceiling must be <= hit_rate_validated_floor"
)
```

---

### WR-02: `supply_demand_setup.py` passes empty string `symbol`, `timeframe`, and `timestamp` to `make_signal_from_frame()`

**File:** `src/intelligence/trading/supply_demand_setup.py:206-218`

**Issue:** The call to `make_signal_from_frame()` at line 206 passes `symbol=""`, `timeframe=""`, `timestamp=""`, and `regime_context=""`:
```python
return make_signal_from_frame(
    tf,
    symbol="",
    timeframe="",
    timestamp="",
    ...
    regime_context="",
    ...
)
```
Every other I7 plugin correctly reads these from `frames.get("symbol", "")` and `features.get("timeframe", "")`. The empty strings will propagate into the Kafka signal payload with blank symbol/timeframe/timestamp fields. `make_signal_id()` includes `symbol` in its SHA-256 input — blank symbol means all SupplyDemandSetup signals across all instruments share the same ID space, risking collisions.

Downstream, `REQUIRED_SIGNAL_FIELDS` includes `"symbol"`, `"timeframe"`, `"timestamp"` — `validate_signal()` will pass because the fields are present (just empty), but consumers (signal_ledger writer, lifecycle tracker) will receive malformed rows.

**Fix:**
```python
return make_signal_from_frame(
    tf,
    symbol=frames.get("symbol", ""),
    timeframe=features.get("timeframe", ""),
    timestamp=features.get("timestamp", ""),
    signal_type=sig_type,
    setup_plugin=self.name,
    direction=direction,
    confidence=confidence,
    regime_context="demand" if direction == 1 else "supply",
    supporting_factors=supporting,
    factor_scores=factor_scores,
)
```

---

### WR-03: `signal_quality_audit.py` references `market_context` column — stale name post migration 127

**File:** `production/scripts/signal_quality_audit.py:399, 436`

**Issue:** The Layer 2 sample query at line 388-409 selects `f.market_context` and the feature merge loop at line 436 iterates over `"market_context"`. Per `TIER_DB_COLUMNS` in `schemas.py`, the column for I4 is now `"confluence_scores"` (reverted from `i4` in migration 126 after the Phase 125 rename). The `market_context` name is the pre-124 name (when I2+I4 shared the column). After migration 124, `market_context` retains only cross_asset context data. Querying it for I4 features like `trend_confidence` or `trend_regime` will find no data.

The `_FIELD_TO_COLUMN` mapping correctly maps `"trend_confidence"` to `"technical_indicators"` (line 115) so those specific fields will work. But the SQL selects `f.market_context` as an extra column and merges it as `"market_context"` — if the column no longer holds the I4 fields that some audit plugins expect (e.g., for future VALIDATED plugins), the audit will silently under-report coverage.

The script should use `TIER_DB_COLUMNS` from `schemas.py` to ensure the column list stays in sync with schema evolution.

**Fix:**
```python
from src.intelligence.schemas import TIER_DB_COLUMNS

# In sample_sql, select columns from TIER_DB_COLUMNS values + technical_indicators + smc
# Replace hard-coded column list with dynamic construction from TIER_DB_COLUMNS
```

---

### WR-04: `confidence_utils.py` has duplicate `tol:` param in `_validate_weights_sum` docstring

**File:** `src/intelligence/trading/confidence_utils.py:70-71`

**Issue:** The docstring for `_validate_weights_sum` has the `tol` parameter documented twice:
```python
    tol:     Floating-point tolerance. Default 1e-6 handles float repr of 0.40+0.35+0.25.
    tol:     Floating-point tolerance (default 1e-6 handles 0.40+0.35+0.25).
```
Lines 70-71 are duplicate lines for the same parameter. This is a minor quality defect but confuses documentation readers and indicates a copy-paste artifact left in the code.

**Fix:** Remove the duplicate line (line 71).

---

### WR-05: `CHoCHReversalPlugin.compute_full()` accesses `hmm_regime` but never uses it to gate signals

**File:** `src/intelligence/trading/choch_reversal.py:81`

**Issue:** `hmm_regime` is read at line 81 (`hmm_regime = float(features.get("hmm_regime", 0.0))`) and used only to assign `regime_ctx` string labels (lines 98-107). It is not used in any confidence computation or as a gate. More importantly, `raw_conf` is computed as `0.5 + 0.3 * abs(direction)` which is always `0.5 + 0.3 = 0.8` since `abs(direction)` is always `1` (direction is `+1` or `-1` per the check at line 78). This means `raw_conf` is a hardcoded constant `0.8` — the `hmm_regime` float load is dead weight that adds misleading code signal.

The confidence also uses no factor audit trail sensitive to actual market conditions — `factor_scores = {"choch_strength": round(min(1.0, raw_conf), 4)}` is always `{"choch_strength": 0.8}`. This is the likely source of the IC=-0.014 finding: a constant-confidence plugin cannot be predictive.

**Fix:** Either remove `hmm_regime` extraction (since it's not used in the confidence calc), or use it in a genuine confidence adjustment. At minimum, document that `raw_conf=0.8` is intentionally fixed while the plugin is parked shadow_only:
```python
# Plugin parked shadow_only=True; confidence is intentionally constant (0.8) pending redesign.
# hmm_regime is captured for context annotation only, not used in gate or confidence.
```

---

## Info

### IN-01: Migration 134 header comment says "Migration 132" — stale copy

**File:** `production/migrations/134_phase126_apr_seeds.sql:1`

**Issue:** The file is `134_phase126_apr_seeds.sql` but line 1 reads `-- Migration 132: Seed Phase 126 zone width gate...`. This is a copy-paste artifact from the original migration 132 that was reused when creating 134. The comment references the wrong migration number, which will confuse anyone auditing the migration history.

**Fix:** Change line 1 to `-- Migration 134: Seed Phase 126 zone width gate and stop distance floor parameters into APR.`

---

### IN-02: `_bootstrap_hit_rate_ci()` runs a pure-Python loop for 10,000 resamples — slow for large N

**File:** `production/scripts/signal_quality_audit.py:191`

**Issue:** The bootstrap CI function uses a Python `for` loop over 10,000 iterations. For the largest plugins (N=149,873 for `trad_DivergenceStack`), this generates 10,000 arrays of ~150k elements. The current implementation is correct but can be replaced with a vectorized NumPy call that is 50-100x faster and cleaner:

```python
# Replace the for loop with:
indices = rng.integers(0, n, size=(n_resamples, n))
sample_means = hits[indices].mean(axis=1)
```
This is a quality improvement for an audit script that may be run regularly post-Phase-127.

---

### IN-03: `test_annotate_sets_context_features_to_full_snapshot` asserts identity (`is`) not equality

**File:** `tests/unit/intelligence/test_pipeline_annotation.py:68`

**Issue:** The test asserts `sig["context_features"] is ff` — same object identity. This test will break if CR-01 is fixed (shallow copy). More importantly, asserting identity as a correctness invariant bakes in the aliasing behavior as a contract, making the CR-01 fix a "breaking change" in the test suite. The intent of the test is to verify that all keys from `flat_features` appear in `context_features`, not that they share the same reference.

**Fix:** Change to equality assertion:
```python
assert sig["context_features"] == ff, (
    "context_features must contain all keys from flat_features"
)
```
Add a separate test that modifying `sig["context_features"]` after annotation does not affect `flat_features` (verifying isolation).

---

_Reviewed: 2026-06-15_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
