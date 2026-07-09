# 068 — Canary (negative-control) predictors

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §11 (G-1), executive
summary item 2.
**Priority:** high — cheapest integrity purchase available, zero new services.
**Gate:** none. Buildable immediately, independent of the v3.15 batch.

## Proposal

Register 5-10 permanent control features, run through the full corpus pipeline every rerun:

- **Pure noise:** seeded RNG columns (seed in APR, same precedent as `HMM_RANDOM_STATE`).
- **Acausal placebos:** an existing feature deliberately shifted forward (e.g. `ret_lag_1` from
  T+2) — must show spectacular IC; a live calibration of what look-ahead contamination looks
  like in this exact pipeline. Any *causal* feature approaching placebo-level IC deserves
  immediate suspicion.
- **Dead features:** a constant and a near-constant column, verifying degenerate-input handling.

**Gate:** any noise canary passing `ic_ci_lower > 0 AND passes_fdr` in any stratum fails the
corpus run loudly (manifest error, not a warning) — converts "found by audit months later" into
"found by the next corpus run."

## Mechanics

A handful of `feature_registry` rows flagged `is_control=true` (excluded from ensemble
eligibility by the existing status filter) + one orchestrator assertion in `ic_engine.py` or the
corpus pipeline script. No new tables, no new service.

## Filter check (from source doc)

Falsifiable (self-verdicting by construction); reduces overfitting risk rather than adding any;
weak-signal diversification n/a (this is integrity tooling, not a predictor); cheap (a handful of
rows + one assertion).
