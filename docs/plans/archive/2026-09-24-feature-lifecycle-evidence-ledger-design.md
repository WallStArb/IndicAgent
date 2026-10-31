# Feature lifecycle as an evidence ledger and its own DAG node (todo 402)

Author: Claude Opus 5.5, 2026-09-24
Status: superseded for decision rules by unified design 11 (data-quality status, phase 186-09);
current rules live in `docs/foundation/unified-concept-registry.md`. Superseded again
2026-10-31 at the program level by `docs/plans/2026-10-31-data-fill-and-corpus-rerun-plan.md`
(operative). The `concept_evaluation` ledger mechanics below still describe the table.
Archived 2026-10-31 (todo 568); the pre-condense full text stands at commit `bfed851f9`.
Original status: design, not yet implemented; landed inside the
post-176 ic_engine bundle
(todos 389, 399, 401, 402, 403), because moving the lifecycle hook out of
`services/ic_engine.py` moves `code_content_key` and that bundle already pays for a full
recompute.

## What was wrong with todo 402's original fix

Keying the hook's idempotency check on the run's evidence identity would have made every
recompute re-evaluate lifecycle. The hook advanced `concept_gate` counters once per run; with
`alpha.validation.oos_start` pinning the training window, every recompute is the same data, so
two code recomputes could reach the demotion threshold with zero new data. Hysteresis demands
repeated failure on independent evidence; the fix would have made it a count of code edits.

## The decision

An append-only UCR table `concept_evaluation` replaces the run counters. Domain-generic:
`concept_id`, `domain`, `window_end` (the training window the evidence belongs to),
`evidence_key` (sha256 of the canonical, sorted input rows the decision read), `passed`
(demotion side: `demote_fraction < floor`; promotion side: `pass_fraction >= meta_fdr_min_fraction`),
`statistic`, `n_cells`, `n_observations`, `guard_status` (`ok` / `hold_high` / `alert_low` /
`insufficient_cells`), `evaluated_at`, `run_ref`.

Append-only, primary key `(concept_id, window_end, evidence_key)`, `ON CONFLICT DO NOTHING`.
Re-running on identical evidence is a no-op; new evidence for a window adds a row and every
earlier evaluation is kept. The derivation reads only the latest row per window, so one window
counts once however many times it is recomputed, and new evidence for a window is never ignored.
Idempotency comes from the key, so the Step 0 `integrity_monitor` lookup is deleted.

Supporting decisions: status is a pure function of the ledger
(`derive_feature_transition`, streaks over distinct windows; `concept_gate` counter columns stop
being sources of truth); `feature_lifecycle` becomes its own DAG node
(`ic_engine -> feature_ic_scores -> feature_lifecycle -> concept_evaluation, concept_registry ->
ensemble_trainer`) so lifecycle edits stop invalidating IC cells; measurement rows stop carrying
governance state (`feature_status_at_eval` dropped, point-in-time status from
`concept_transition_log`); no special genesis rule (hysteresis applies uniformly).

## Record (2026-09-24, window 2025-12-24 05:15 UTC)

- The pre-redesign lifecycle had never made a performance decision: `concept_transition_log`
  held 294 feature rows (292 `genesis_seed`, 2 `operator_override`), zero promotions or
  demotions. Demotion counted only material failures (standing weight times nearest CI bound
  above `alpha.decay.materiality_threshold` 0.005); 0 of 385 weighted cells were material, so
  `active` meant "not materially decayed", not "has evidence".
- First replay after landing: 0 transitions, 0 material cells of 90,220, 295 ledger rows
  (295 active feature concepts evaluated; the predicted 294 came from the log row count and
  missed one concept with no genesis row). Rerun on identical evidence added no rows.
- Surprise: the window read `hold_high` - eight cross-asset strata (commodity/fx/rates at
  15m/1h/1d) failed at 99.6-100% against the seeded 0.995 rail with no calibration history
  (the groups postdate the guard's 2026-07 calibration). Filed as todo 407.
