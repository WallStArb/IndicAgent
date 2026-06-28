# 029 — Executable Returns Implementation (Invariant 1)

## Problem

Current `forward_returns` table uses theoretical returns:
```python
return[T, N] = close[T+N] / close[T] - 1
```

This violates Renaissance Invariant 1. The IC measured on theoretical returns is overstated because close[T] is the observation price, not the executable entry price. Overnight gaps and opening moves are captured in theoretical returns but cannot be traded.

**Impact:** IC values, especially for short-horizon predictors (1m, 5m momentum), are numerically overstated. This affects every downstream weight and ensemble decision.

## Renaissance Mandate

From `docs/ideas/signal-08-intelligence-refactor.md` Invariant 1:

> **Rule:** Forward returns MUST use executable entry/exit prices.
> ```
> R(T, N) = ln(open[T+N+1] / open[T+1])  -- CORRECT
> R(T, N) = ln(close[T+N] / close[T])    -- WRONG
> ```

From `docs/plans/2026-06-20-alphaengine-ic-spec.md` §V.1:

> The IC engine measures whether a feature score at bar T predicts price movement after T.
> The relevant price movement is what a trader can actually capture — not the theoretical
> return from T's close to T+N's close, but the return from the first executable entry
> (open of bar T+1) to the exit (open of bar T+N+1).

## Fix

### 1. Update `forward_returns` Schema

Add `return_type` column to distinguish theoretical vs executable:

```sql
ALTER TABLE forward_returns ADD COLUMN return_type text NOT NULL DEFAULT 'theoretical';
CHECK (return_type IN ('executable_open_to_open', 'theoretical'));

-- Existing rows marked as theoretical
UPDATE forward_returns SET return_type = 'theoretical' WHERE return_type IS NULL;
```

### 2. Update Outcome Labeler Computation

Change from close-based to open-based returns:

```sql
-- Current (WRONG):
LN(close[T+N] / close[T])

-- Correct (Renaissance spec):
LN(open[T+N+1] / open[T+1])
```

### 3. Re-compute `forward_returns`

Run the Outcome Labeler with executable returns:
- Backfill all (symbol, TF) pairs
- Write rows with `return_type = 'executable_open_to_open'`
- Keep old rows for comparison (archive as `*_v0_theoretical_returns`)

### 4. Re-run IC Engine

Run `ic_engine.py` on corrected `forward_returns`:
- All IC values will be re-measured
- Compare new IC (executable) vs old IC (theoretical)
- Document delta in IC discovery report

### 5. Update Ensemble Weights

After IC re-measurement:
- Run `ensemble_trainer.py` on new `feature_ic_scores`
- New `ensemble_weights` with corrected IC-based weights
- Archive old weights as `weight_version_v0_theoretical`

## Scope

- `docs/plans/2026-06-20-alphaengine-ic-spec.md` — update §V.1 SQL query
- `services/forward_return_labeler.py` — update to use open-based returns
- `migrations/` — schema migration for `return_type` column
- `services/ic_engine.py` — ensure it filters `WHERE return_type = 'executable_open_to_open'`
- `services/ensemble_trainer.py` — re-run after IC re-measurement
- `docs/analysis/` — IC comparison report (theoretical vs executable)

## Verification

After fix, verify:
1. `forward_returns.return_type = 'executable_open_to_open'` on all new rows
2. IC engine filters by `return_type` (logs confirm)
3. IC values are lower than theoretical (expected — fewer gaps captured)
4. Ensemble weights updated and committed

## Reference

- `docs/ideas/signal-08-intelligence-refactor.md` — Invariant 1
- `docs/plans/2026-06-20-alphaengine-ic-spec.md` §V.1 — Executable Return Specification
- Renaissance Invariants Summary Table — status: ⚠️ NOT IMPLEMENTED
