---
status: closed
priority: P2
filed: 2026-09-24
closed: 2026-09-24
source: Phase 176-08 gate verdict, Query 3
---

# ic_engine lifecycle hook never re-runs at a pinned training window

## What

`services/ic_engine.py`'s post-run lifecycle hook (Step 0, ~line 6398) short-circuits when
`integrity_monitor` already holds an `ic_lifecycle` `guard_fail_fraction` /
`decay_cells_flagged` fact for the run's `training_window_end`. `alpha.validation.oos_start`
pins that window at 2025-12-24 05:15 UTC, and the fact for it was written 2026-07-22. Every
corpus recompute since then (new features, code changes, new cell fingerprints) has logged
`ic_engine.lifecycle_hook_already_ran` and written no `concept_transition_log` rows; the last
feature transitions are dated 2026-08-05.

Concrete effect: Phase 176's `earnings_season_flag` and `days_since_quarter_end` fail the
FDR/walk-forward gate in every cell (176-GATE-VERDICT.md) but remain at their migration-350
genesis status `active` with no evidence event.

## Fix direction

Key the idempotency check on the run's evidence identity, not the window alone: e.g. include a
hash of the run's cell fingerprints (code_content_key / apr_snapshot_key / upstream watermark)
or the run_ts, so a recompute that changed the evidence re-evaluates lifecycle while a plain
resume of the same run still no-ops. Then re-run only the hook for the current window (no IC
recompute needed; it reads persisted `feature_ic_scores`). Never hand-edit
`concept_registry.status` (UCR Invariant 1).

## Superseded fix direction (2026-09-24)

The "Fix direction" above is wrong: it would count code recomputes of one pinned window as
independent observations and break the demotion/promotion hysteresis. The measured state also
shows the two Phase 176 features are correctly `active` under the materiality rule (zero
weight means they can never be a material failure) and already excluded from weight by the
per-cell gate, so this is not P1. Replacement design, with the measurements:
`docs/plans/2026-09-24-feature-lifecycle-evidence-ledger-design.md` (append-only
`concept_evaluation` ledger, status as a pure function of it, lifecycle extracted into its
own `feature_lifecycle` DAG node, governance state removed from `feature_ic_scores`).

## Closure (2026-09-24)

Landed db48829c8 (+ 0205f0cb3 guard, 7448a8e55 season filter); first post-recompute run 2026-09-24 19:31: 295 evaluated, guard uncalibrated, 0 transitions (correct with one window, see 415).
