---
**Created:** 2026-06-28
**Superseded:** 2026-07-04 (concept doc archived 2026-07-02; scope absorbed into `docs/ideas/intel-14-integrity-monitor.md`)
**Area:** intelligence
**Type:** new_feature
**Priority:** N/A — superseded
**Effort:** 2-3 days
**Benefit:** Prevents silent ensemble dilution from decayed features; enables automatic feature exclusion
**Risk:** medium (affects ensemble composition)
**Gate:** N/A — superseded
---

# 015 — Feature Vector Lifecycle (Demotion + Observability)

## SUPERSEDED — ABSORBED INTO INTEL-14 (2026-07-04)

This todo's concept doc (`docs/ideas/feature-vector-lifecycle.md`) was archived 2026-07-02: its
cooldown-based recovery policy was superseded by `docs/ideas/intel-14-integrity-monitor.md`'s
evidence-based approach (2 consecutive passing corpus runs AND ≥
`alpha.ic.decay_recovery_min_observations` new independent observations, not a calendar cooldown).
This todo itself was never updated to point at the successor and kept showing `Status: Pending`
against a design that was no longer the plan — exactly the "notebook nobody reads" failure mode.
Not implementing this todo as originally scoped; intel-14 is the live design for wiring feature
decay detection when that work is picked up. The scope/schema notes below are kept for their
original problem statement and Scope breakdown, not as a build plan — build against intel-14
instead.

**Status:** Superseded, not implemented as written
**Concept doc (archived):** `docs/ideas/archive/feature-vector-lifecycle.md`
**Successor design:** `docs/ideas/intel-14-integrity-monitor.md`

## What

Wire the demotion side of the feature lifecycle. The IC gate handles promotion (already correct). Nothing handles demotion — `is_decaying`, `decay_detected_at`, `recovery_eligible_at` are schema-only dead columns. A feature that passes IC once stays in the ensemble forever.

## Why

With 54 features the risk is low. With 100+ atomics + compound primitives from the Interaction Factory the ensemble could accumulate features whose edge has disappeared. Silent wrong answer — weights for non-predictive features dilute the ensemble without any signal of the problem.

## Scope

1. **ic_engine.py** — detect active→decaying transition on each run; write `is_decaying=true`, `decay_detected_at`, `recovery_eligible_at`; detect recovery (cooldown elapsed + gate re-passes); publish `topic_feature_lifecycle_transition` event
2. **ensemble_trainer.py** — add `AND is_decaying = false` and `AND feature_name NOT IN (SELECT feature_name FROM feature_deprecations)` to feature query
3. **Migration** — `feature_deprecations` table; `topic_feature_lifecycle_transition` key in `stream_keys.py`
4. **APR keys** — `alpha.ic.decay_ic_sharpe_threshold` (default 0.0), `alpha.ic.decay_cooldown_days` (default 30)
5. **Metrics** — `feature_active_count`, `feature_decaying_count` labeled by (tf, regime)

## Key Design Decisions (pre-resolved in concept doc)

- Binary exclude (not weight dampening) — a feature either has demonstrated edge or it hasn't
- No live shadow period — IC walkforward gate is the validation; a live shadow period would be redundant
- `feature_deprecations` table for manual operator removals (definition changes, collinearity audit results)
- Recovery requires cooldown elapsed + IC gate re-pass — prevents oscillation on marginal features
- `is_decaying IS NULL` guard in ensemble query ensures backward compatibility with legacy rows
