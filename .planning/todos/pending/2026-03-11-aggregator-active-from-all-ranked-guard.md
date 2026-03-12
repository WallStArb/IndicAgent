# Aggregator: Guard `active` Must Derive from `all_ranked`

**Created:** 2026-03-11
**Priority:** Medium (regression risk)
**Effort:** Small (30 min)
**Source:** CONCERNS.md audit

## Problem

`src/intelligence/trading/aggregator.py` correctly derives `active` from `all_ranked`, but this is a non-obvious invariant with no documentation or test assertion. If someone modifies winner selection logic and uses raw `signals` instead of `all_ranked`, the performance weighting (`perf_multiplier`) silently stops working — signals still fire, just with wrong priority.

Root cause: `_build_all_ranked()` copies signal dicts and adds `adjusted_rank`. Raw `signals` never get `adjusted_rank` set, so `perf_weights` have zero effect on winner selection.

## Fix

### 1. Add comment at the `active` derivation line in `aggregator.py`
```python
# CRITICAL: Always derive active from all_ranked, NOT raw signals.
# _build_all_ranked() applies perf_multiplier weighting and sets adjusted_rank.
# Raw signals list is never modified — using it here would silently zero-out perf weighting.
active = [s for s in all_ranked if s.get("regime_eligible", True)]
```

### 2. Add assertion in aggregator tests
In `tests/unit/test_aggregator.py` (or equivalent), verify that active signals have `adjusted_rank`:
```python
result = aggregator.select(signals, perf_data, regime)
for sig in result["active"]:
    assert "adjusted_rank" in sig, "active signals must derive from all_ranked, not raw signals"
```

## Files

- `src/intelligence/trading/aggregator.py`
- `tests/unit/test_aggregator.py`
