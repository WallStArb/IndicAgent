---
status: pending
priority: P3
filed: 2026-07-11
source: methodology-change-ledger.md E10, Phase 143.1-07 resumption
---

# Staged-validation gates should bound `is_pooled=true` and `is_pooled=false` cells separately

## Finding

E6's bootstrap CI staged-validation gate used a single total bound (`<=2` SUSPECT cells
out of 66-72 evaluated, `<=1` per `(tf, is_pooled)` stratum) across both `is_pooled=true`
(POOLED, cross-sectional — the actual ensemble eligibility source per
`ensemble_trainer.py`/`ic_engine.py`'s lifecycle hook) and `is_pooled=false` (per-symbol,
diagnostic-only — excluded from every capital-allocation consumer by construction).

When the gate measured 6/29 SUSPECT, 5 of those 6 were `is_pooled=false` and mechanically
incapable of affecting a weight or lifecycle decision, yet they alone were enough to
breach the total bound and block Plan 07's corpus-wide re-run. The per-stratum bound
correctly isolated the one cell that mattered (`price_vol_corr_slow`/POOLED/1d/mid_bull,
which independently satisfied its own `<=1` stratum bound) — but the total bound did not
distinguish "5 diagnostic-only breaches + 1 capital-relevant breach" from "6
capital-relevant breaches," and a naive reading of the gate's FAIL verdict would have
blocked the re-run indefinitely for a risk profile that was, on inspection, almost
entirely inert.

See `docs/plans/methodology-change-ledger.md` E10 for the full disaggregation and the
resulting risk-acceptance decision.

## Proposal

Any future staged-validation gate that evaluates cells split by `is_pooled` (or any
other dimension that maps directly onto "does this data reach a capital-allocation
consumer") should pre-commit two separate total bounds — one for the capital-relevant
strata, one for diagnostic-only strata — rather than one pooled total. The
capital-relevant bound should stay strict (arguably 0-tolerance, since it gates live
trading capital); the diagnostic-only bound can be looser, since a SUSPECT flag there is
informational, not risk-bearing.

This is a design fix to the gate-authoring pattern (`ops_ic_null_calibration.py` and any
future scripts of its shape), not an urgent fix — no gate is currently blocked by this
gap (E10 already resolved the one live incident). Low priority, applies the next time a
staged-validation gate of this shape is authored.

## Not in scope

Retroactively re-splitting E6's already-measured/already-resolved result — E10 already
did the disaggregation manually for that one incident. This todo is about the gate
*design* pattern for next time, not re-litigating E6.
