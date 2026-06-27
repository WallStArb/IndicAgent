# 010 — Feature Vector Lifecycle (Demotion + Observability)

**Status:** Pending
**Priority:** Medium — can run in parallel with primitives expansion; should land before ensemble has 100+ features where undetected decay becomes a real risk
**Concept doc:** `docs/ideas/feature-vector-lifecycle.md`

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
