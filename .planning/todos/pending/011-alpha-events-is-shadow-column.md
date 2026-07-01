---
**Created:** 2026-06-28
**Revised:** 2026-06-30
**Area:** alphaengine
**Type:** new_feature
**Priority:** P1
**Effort:** 0.5 days
**Benefit:** Enables scientific shadow validation — all alpha_events are shadow until explicitly promoted; promotion gate cannot be retroactively softened
**Risk:** low
**Gate:** Phase 142A complete (alpha_ensemble_ic table exists)
---

# 011 — Add `is_shadow` to alpha_events

## Problem

`alpha_events` has no `is_shadow` column. Every emission is treated as live. There is no
mechanism to enforce the Phase 142B → Phase 144 promotion gate in the data itself. A
Renaissance shadow deployment requires the shadow/live distinction to be a first-class
DB column, not an implicit assumption.

## Deliverables

### 1. Migration

Add to `alpha_events`:

```sql
ALTER TABLE alpha_events ADD COLUMN is_shadow BOOLEAN NOT NULL DEFAULT TRUE;
```

All existing rows default to `TRUE` — correct, since no live promotion has occurred.

### 2. APR key

```sql
INSERT INTO config_state (key, value, changed_by, reason)
VALUES ('alpha.publisher.is_shadow', 'true', 'migration', '[initial_value] flip to false at Phase 144 live promotion');
```

### 3. alpha_publisher.py

Load `is_shadow` from APR at init. Add to INSERT columns and `$N` binding.
All batch/corpus runs emit `is_shadow=True` until the operator flips the APR key.

### 4. Downstream query discipline

Any query that should only touch live emissions must filter `WHERE is_shadow = FALSE`.
Any query measuring shadow performance must filter `WHERE is_shadow = TRUE`.
No query should omit the filter — mixing live and shadow is a silent wrong answer.

## Promotion Gate (defined here, not negotiated later)

At Phase 144, the operator sets `alpha.publisher.is_shadow = false` only after all of
the following pass on the shadow record:

- ≥ 60 trading days of shadow alpha_events
- mean(counterfactual_pnl_r) > 0 at 95% CI (bootstrap, one-tailed) on trade_frames WHERE is_shadow = TRUE
- Sharpe of counterfactual_pnl_r > 0.5 annualized
- max drawdown of cumulative counterfactual_pnl_r < 25%
- IC Sharpe stable across shadow window (no cliff in final 20 days)

These criteria are fixed. Post-hoc negotiation is not allowed.
