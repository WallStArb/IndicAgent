# Feature lifecycle as an evidence ledger and its own DAG node (todo 402)

Author: Claude Opus 5.5, 2026-09-24

Status: design, not yet implemented. Lands inside the post-176 ic_engine bundle (todos 389,
399, 401, 402, 403), because moving the lifecycle hook out of `services/ic_engine.py` moves
`code_content_key` and that bundle already pays for a full recompute.

## Why todo 402's original fix is wrong

Todo 402 proposed keying the hook's idempotency check on the run's evidence identity so every
recompute re-evaluates lifecycle. The hook advances `concept_gate` counters
(`consecutive_active_fails`, `consecutive_shadow_passes`, `observations_since_demotion`) once
per hook run. With `alpha.validation.oos_start` pinning the training window, every recompute
is the same data. Two code recomputes would reach `alpha.decay.demotion_min_consecutive = 2`
with zero new data. Hysteresis exists to demand repeated failure on independent evidence; the
fix would turn it into a count of code edits.

## What was measured (2026-09-24, window 2025-12-24 05:15 UTC)

1. The feature lifecycle has never made a performance decision. `concept_transition_log`
   holds 294 feature rows: 292 `genesis_seed`, 2 `operator_override`, zero promotions or
   demotions. 137 of 294 features were seeded after the last hook run (2026-07-22) and have
   never been evaluated at all.
2. The two failed Phase 176 features would stay `active` even if the hook had run. Demotion
   counts only material failures: a failing cell whose standing ensemble weight times its
   nearest CI bound exceeds `alpha.decay.materiality_threshold` (0.005). Both features carry
   zero weight. Across the window's mid-lookahead POOLED cells, 0 of 385 weighted cells are
   material (approximate query, per-tf mid lookahead assumed 5m=6, else 2). Under the rule as
   written, `active` means "not materially decayed", not "has evidence". The evidence gate is
   per cell, in `ensemble_trainer`: `passes_fdr`, `reliable`, `passes_walkforward` (3 folds
   within the window), and the meta-FDR fraction. The 176 gate verdict's framing that the two
   features are wrongly `active` is incorrect; they are correctly excluded from weight by the
   per-cell gate.
3. The current Step 0 guard is right about independence (one observation per window) and wrong
   about coverage: the first evaluation of a window wins forever, so features added later and
   code changes to the evidence are never evaluated.
4. Governance lives inside the measurement hash. `code_content_key` hashes every first-party
   module ic_engine loads, including the ~500-line hook and `ConceptRegistryService`. Any
   lifecycle edit invalidates every IC cell (a 9.5 hour corpus run as of 176-08; 3.5 days
   before it).
5. `feature_status_at_eval` is a copy of mutable governance state stored on measurement rows.
   It is refreshed to the current status by `_FEATURE_STATUS_REFRESH_SQL` and a
   status-only-stale fingerprint branch, so it is not point-in-time either. It has the upkeep
   cost of a cache and no audit value that `concept_transition_log` does not already give.
6. Unrelated, found along the way: the champion `ensemble_weights` (computed 2026-09-22)
   predate the 176-08 IC recompute (2026-09-24). 143 of the 385 weighted cells now fail the
   per-cell gate. `ensemble_trainer` has not re-run against the new IC.

## Design

### D1. An evaluation ledger replaces the run counters

New UCR table `concept_evaluation`, domain-generic:

| column | meaning |
|---|---|
| `concept_id`, `domain` | the concept evaluated |
| `window_end` | the training window the evidence belongs to |
| `evidence_key` | sha256 of the canonical, sorted input rows the decision read |
| `passed` | the window's verdict (demotion side: `demote_fraction < floor`; promotion side: `pass_fraction >= meta_fdr_min_fraction`) |
| `statistic`, `n_cells`, `n_observations` | what the verdict was computed from |
| `guard_status` | `ok` / `hold_high` / `alert_low` / `insufficient_cells` for the window |
| `evaluated_at`, `run_ref` | provenance |

Append-only, primary key `(concept_id, window_end, evidence_key)`, `ON CONFLICT DO NOTHING`.
Re-running on identical evidence is a no-op; new evidence for a window adds a row and every
earlier evaluation is kept. The derivation (D2) reads only the latest row per window, so one
window counts once however many times it is recomputed, and new evidence for a window is never
ignored. Idempotency comes from the key, so the Step 0 `integrity_monitor` lookup is deleted.

### D2. Status is a pure function of the ledger

`derive_feature_transition(current_status, evaluations, gate) -> Transition | None`, with no
I/O. Streaks are trailing runs over distinct windows ordered by `window_end`. Observations are
summed over distinct windows. The `concept_gate` counter columns stop being sources of truth
for the feature domain. They are dropped once no reader remains (today only ic_engine and two
ops scripts touch them, grep-verified 2026-09-24). Replaying the whole lifecycle history is a
fold over the ledger, testable with synthetic evaluations and no database.

The decision rules themselves (sign-aware material-fail predicate, per-feature demote fraction,
promotion by meta-FDR fraction, stratified regime-shift guard) move unchanged. This design
fixes how evidence is counted, not what counts as failure.

### D3. `feature_lifecycle` becomes its own DAG node

`services/feature_lifecycle.py` (`FeatureLifecycle`, `BaseBatch` oneshot,
`indicagent-feature-lifecycle.service`), registered in `_DAG_ORDER`:

```
ic_engine -> feature_ic_scores -> feature_lifecycle -> concept_evaluation, concept_registry -> ensemble_trainer
```

- Reads only persisted rows, so any window can be replayed without an IC recompute. This is
  what todo 402 wanted from "re-run only the hook".
- Materiality reads the champion `ensemble_weights` version pinned in APR. That is an input
  artifact from an earlier run, not this run's output, so each run's DAG stays acyclic; the
  feedback is a time-lagged recurrence, declared as such.
- Async, on the `BaseBatch` asyncpg pool. `ConceptRegistryService` keeps one async transition
  path; the `*_sync` counter and transition twins that only ic_engine used are deleted. The
  operator override CLI calls the async path via `asyncio.run`.
- ic_engine loses the hook, `_apply_feature_transitions`, `_lifecycle_guard_cells` and the
  staleness gauge wiring (the gauge moves with the node). Lifecycle edits stop invalidating IC
  cells.

### D4. Measurement rows stop carrying governance state

`ensemble_trainer` joins `concept_registry` for status at train time instead of reading
`feature_ic_scores.feature_status_at_eval`. ic_engine stops reading and writing the column:
`_FEATURE_STATUS_REFRESH_SQL` and the status-only-stale fingerprint branch are deleted.
Point-in-time status for historical analysis comes from `concept_transition_log`. The column
is dropped in a later migration that follows
`docs/foundation/timescaledb-compressed-column-migration.md`. The four ops/analysis scripts
that read it (`ops_canary_integrity_assert.py`, `ops_ensemble_ablation.py`,
`ops_ic_fingerprint_equivalence.py`, `regime_boundary_churn_check.py`) are repointed in the
same change.

### D5. No special genesis rule

An earlier draft let a never-evaluated genesis concept be decided by its first evaluation,
without hysteresis. Finding 2 makes that unnecessary: a zero-weight feature is correctly
`active` under the materiality rule and correctly excluded from weight by the per-cell gate.
Hysteresis applies uniformly.

## Pre-registered prediction for the first replay

After landing, replay `feature_lifecycle` for window 2025-12-24 05:15 UTC. From finding 2:
zero demotions and zero promotions (0 shadow_only concepts exist to promote). 294 ledger rows,
one per feature concept with POOLED cells at the mid lookahead. Any transition is a surprise
to investigate before accepting, not a result.

## Net complexity

Deleted: Step 0 guard; the three counter columns as state; the counter CAS SQL and its sync
methods; the sync transition twin; the status refresh SQL and fingerprint branch; ~500 lines
from ic_engine. Added: one table, one pure function, one thin `BaseBatch` node. Fewer moving
parts, and governance and measurement can change independently.

## Out of scope

- Migrating `domain='ensemble_strategy'` (`record_comparison_outcome`, `promotion_consecutive`)
  onto `concept_evaluation`. The table is domain-generic so it can follow; separate todo.
- Whether the materiality threshold (0.005) is right. APR calibration backlog.

## First replay (2026-09-24, after landing)

`services/feature_lifecycle.py --training-window-end 2025-12-24T05:15:00+00:00`, dry run first,
then real, then a rerun, all against the 176-08 IC.

- Transitions: 0, as predicted. Material cells: 0 of 90,220.
- Ledger rows: 295, not the predicted 294. The prediction counted `concept_transition_log`
  rows (294); 295 feature concepts are `active` (one has no genesis log row), and all 295 were
  evaluated. A counting slip in the prediction, not a code surprise.
- Rerun on identical evidence: still 295 rows (upsert refreshed `evaluated_at`/`run_ref` only).
- Surprise: the window reads `hold_high`. Eight cross-asset strata (commodity/fx/rates at
  15m/1h/1d) fail at 99.6-100%, above the seeded 0.995 rail, with no calibration history (the
  groups postdate the guard's 2026-07 calibration). Under the unchanged guard rule a held window
  is not evidence, so nothing would count until those strata accrue `guard_min_history`
  windows. Filed as todo 407; it would have held the retired hook the same way.
