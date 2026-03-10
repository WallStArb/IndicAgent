# Enable CIS Scoring in Historical Backfill

**Created:** 2026-03-08
**Priority:** HIGH
**Status:** Pending
**Related:** Renaissance Gap Analysis (T0-A — Tier 0 bug fix), docs/ideas/renaissance-gap-analysis.md

## Problem

`historical_backfill.py` does not run CIS scoring when generating signals. The `aggregate()` function is called without the `features=` kwarg, so `cis_scorer` never computes bucket scores. Backfilled signals have `cis_score=NULL`, `bucket_scores=NULL`, `weights_version=NULL` in `signal_ledger`.

This prevents:
- Backtesting CIS gating effectiveness
- Comparing CIS-selected vs baseline signals historically
- Validating CIS thresholds (`abs(score) > 0.35`, `buckets_agreeing >= 3`)

## Root Cause

In `production/scripts/historical_backfill.py:502`:
```python
agg_result = aggregate(raw_signals, trend_regime=trend_regime)
# Missing: features=all_features
```

Compare to live `services/signal_generator_service.py:574`:
```python
result = aggregate(
    raw_signals,
    trend_regime=trend_regime,
    features=features,  # ← CIS scoring runs ONLY when this is provided
    regime_data=regime_data,
    perf_weights=self._perf_weights,
)
```

And `src/intelligence/trading/aggregator.py:150`:
```python
if features is not None:  # ← CIS only runs when True
    scorer = CISScorer()
    cis_result = scorer.score(features, plugin_outputs)
```

## Solution

### 1. Pass `features=all_features` to `aggregate()`

In `run_i7_and_persist()` at line ~502, add the kwarg:

```python
# Before:
agg_result = aggregate(raw_signals, trend_regime=trend_regime)

# After:
agg_result = aggregate(raw_signals, trend_regime=trend_regime, features=all_features)
```

### 2. Populate CIS fields in `_build_ledger_entries()`

In `historical_backfill.py:372-427`, the `LedgerEntry` dataclass construction currently sets CIS fields to `None` (lines 446-449):

```python
entries.append(LedgerEntry(
    # ... existing fields ...
    None,           # cis_score — NULL for backfill
    None,           # bucket_scores — NULL for backfill
    None,           # weights_version — NULL for backfill
    None,           # signal_quality — NULL for backfill
))
```

Should populate from `agg_result`:

```python
entries.append(LedgerEntry(
    # ... existing fields ...
    cis_score=result.cis_score,
    bucket_scores=result.bucket_scores,
    weights_version=result.weights_version,
    signal_quality=None,  # Still NULL; filled by lifecycle service
))
```

### 3. Add `features=` to `aggregate()` call for regime_data

The `regime_data` (slow-clock HMM regime from higher-TF) should also be passed:

```python
regime_data = intelligence_cache.get(symbol, {}).get(authority_tf)
# authority_tf lookup already exists in signal_generator_service logic
# Should also be passed to aggregate() for regime gating
```

## Verification

After fix, verify by:

```sql
-- Should return non-NULL CIS scores for backfilled signals
SELECT
    COUNT(*),
    COUNT(cis_score),
    AVG(cis_score)
FROM signal_ledger
WHERE source = 'backfill'  OR  created_at < '2026-03-08';
```

Expected: `cis_score` should be populated (not NULL) for recent signals.

## Test Plan

1. Modify `run_i7_and_persist()` to pass `features=all_features` and `regime_data`
2. Update `_build_ledger_entries()` to populate CIS fields from `AggregatedResult`
3. Add authority TF lookup for `regime_data` (mirror signal_generator_service)
4. Run `--replay-only --clean` on a single symbol (e.g., ESH6)
5. Query `signal_ledger` to verify CIS fields populated
6. Run `--replay-only` again without `--clean` — verify idempotence
7. Full `--replay-only --clean` on all symbols for production

## Dependencies

- None — changes are isolated to backfill script
- Ensure `aggregator.py` interface is stable (it is)
- Ensure `cis_scorer.py` interface accepts `features` dict (it does)

## Acceptance Criteria

- [ ] Backfilled signals have `cis_score` populated (not NULL)
- [ ] `bucket_scores` JSONB contains per-bucket values
- [ ] `weights_version = 0` (bootstrap) for backfill entries
- [ ] Existing tests pass
- [ ] No change to live `signal_generator_service` behavior

## Related

- [docs/ideas/renaissance-gap-analysis.md](../../../docs/ideas/renaissance-gap-analysis.md) — T0-A (Tier 0 bug fix)
- [docs/concepts/cis-scoring.md](../../../docs/concepts/cis-scoring.md) — CIS reference
- [src/intelligence/trading/aggregator.py](../../../src/intelligence/trading/aggregator.py) — `aggregate()` function
- [src/intelligence/trading/cis_scorer.py](../../../src/intelligence/trading/cis_scorer.py) — CISScorer
