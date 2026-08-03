# Todo Priorities

**Scope of this index:** `pending/` only — small, single-session, run-it-now items. Phases
(ROADMAP.md, `/gsd-discuss-phase` workflow) are a separate execution track and do not appear
here; anything that's actually phase-scoped (a new feature family, a batched corpus-rerun item,
or hard-gated on a phase/dataset that doesn't exist yet) lives in `deferred/` with a status line
explaining what unblocks it.

**This file is the single source of truth for todo-level prioritization.** Do not automate
ranking itself (the P0-P3 tiers) — that's a judgment call reserved for the project owner. A
"Gate:" line written once at filing time rots — anything sitting in `deferred/` for more than
~2 weeks should have its gate re-checked against live state before being cited as still-blocked.

**Tiers:** P0 = fix soon, real gap/bug surfaced. P1 = high value, quick, fully unblocked. P2 =
real value, not urgent. P3 = hygiene/docs/process, opportunistic.

**Prioritization lens (this project's design north star, CLAUDE.md):** apply Musk's 5-step
mandate in order — question the requirement, delete, simplify, accelerate, automate — before
scoring or filing any todo; don't accelerate work steps 1-3 haven't justified, and don't automate
what isn't proven. A todo that's really a requirement to question or delete belongs in that
state, not P2 "someday."

Weight tier placement against Renaissance Technologies / Jim Simons principles (full doc:
`docs/foundation/principles.md`): instrument everything · shadow mode first · data quality over
model complexity · never drop data that could contain signal · earn promotion through proof
(p<0.05, sufficient N) · segment by regime · automate manual tasks · empirical over theoretical ·
resist overfitting. A todo that would earn its way to P0/P1 under these tests (a live-path
integrity gap, an unproven claim masquerading as settled) outranks one that's merely convenient.

**Phase-level status and in-flight run state:** see `.planning/STATE.md`'s "Current saga"
section (authoritative, live) and
`docs/research/intelligence-lifecycle-backlog-matrix.md`'s Operational Context -- never
duplicated here; a run-status snapshot pasted into this file goes stale within hours and this
file's job is prioritization, not a live dashboard. One open item with no phase home yet: todo
218 (`BIL` implausible per-symbol IC on thin cells, filed 2026-07-31, check `passes_fdr` once
the in-flight run completes).

**Regime-stratification cluster consolidated 2026-08-01** -- read
`docs/research/stratification-dimension-unification.md`'s "Reconciliation pass (2026-08-01)"
section before re-deriving candidate stratification dimensions from scratch; it already
cross-links todos 135/167/224/225/111 (Phase 145).

**Dual intelligence-path plan (stated 2026-08-01, `project_dual_intelligence_path_plan.md` in
memory):** v2.x I1-I7 will eventually run again as a second path alongside v3.0's AlphaEngine,
not retired permanently -- governs todo 223's archive-not-delete call and todo 056's
decommission-in-fact framing (re-read that plan before executing either).

**Corpus pass completed 2026-08-02 (step_timings.jsonl confirms steps 5-8 finished 21:19:49
UTC) -- sequencing chain gated on it re-checked 2026-08-03:** todo 210's live verification
against a repopulated `ensemble_alpha` is now CONFIRMED (1h/1d OOS rows present, see todo 173's
closure). Todo 065 (EM-CAL calibration) is now unblocked -- its gate was this pass completing.
Todo 167 (equity vs symbol-HMM falsifier) status is NOT yet re-confirmed -- unclear whether
`regime_writer` (step 2) itself reran with fresh dual-write data in this pass or whether the
relaunch-from-step-3 skipped it; check before assuming unblocked. Once 065/167 are actioned:
todo 214 (deferred ic_engine/ensemble_ic_engine compute-core refactor), and scoping
Phase 167/T3's cost-hurdle-adjusted spread construction
(`docs/research/trade-construction-layer.md`) as a new phase via `/gsd-discuss-phase` --
proceeding on the latter is the user's call.

**Backlog-quality pass, 2026-08-03:** closed 7 pending todos on inspection -- 217/233 (both
fully shipped and live-confirmed, just never closed), 173 (the specific data gap it reported no
longer exists post the 2026-08-02 run), 189 (remaining scope had zero actionable payoff left),
111 (superseded/double-tracked by ROADMAP Phase 145), and 022+024 (Superset BI + dependent
dashboard, rejected as not Renaissance-quality -- pure convenience tooling with no proof-of-alpha
value for a single-operator system, see each file's closure note). All in `completed/`.

---

## P0 — Fix soon (integrity/correctness gaps already surfaced)

**Live P0 as of 2026-07-29:** [203](pending/203-canary-rng-seed-not-per-symbol-cross-sectional-pseudo-replication.md)
— **seeding fix + broadcast-feature audit DONE 2026-07-29** (see plan
`docs/superpowers/plans/2026-07-29-canary-seed-and-broadcast-feature-audit.md`);
`symbol` now included in `_canary_sub_seed`'s hash, `ops_broadcast_feature_audit.py`
confirms `vix_z`/`yield_slope_z`/`flight_quality` + all session/calendar features
share the same pseudo-replication exposure the canaries had. Building an actual
broadcast-aware significance test remains open (real design question, not filed as
its own todo yet).

**[204](../completed/204-canary-acausal-placebo-pooled-not-detected.md) CLOSED 2026-08-02** —
the 2026-08-02 corpus pass (`ic_engine` run_complete 19:19:25 UTC) confirmed Hypothesis 1
(stale vintage): `canary_acausal_placebo`/POOLED now clears its significance gate in 231/239
cells (96.7%, was 0/239), with real non-degenerate CIs. No further diagnosis needed.

**[230](../completed/230-canary-negative-controls-pooled-false-clears.md) CLOSED 2026-08-02** —
not a corpus artifact: `15m/high_neutral`/`1h/high_bull` carry genuine regime-conditional
signal, so BH-FDR's budgeted false discoveries mathematically cluster there and 3 canaries rode
along under the 5% noise budget. Gate's POOLED zero-tolerance rule replaced with a stricter
Binomial tail bound (`pooled_tail_alpha=0.001`), documented as an E7 addendum.

| Todo | Gap |
|---|---|
| [099](pending/099-bootstrap-ci-staged-validation-gate-not-cleared-5m-residual.md) | P2 — the bootstrap CI staged-validation gate's 6 SUSPECT cells trace to 5 diagnostic-only (`is_pooled=false`) breaches + 1 capital-relevant cell that independently clears its own bound — no longer blocks Plan 07. Underlying statistical question (why 5m autocorrelation/momentum features resist both Fisher-z and block-bootstrap) remains open as non-blocking follow-up. |

**[219](../completed/219-feature-vector-pipeline-crash-loop-and-missing-checked-in-unit.md)
CLOSED 2026-07-31** — crash-loop fixed same day (missing `_THRESHOLD_KEYS` entry, missing
checked-in systemd unit).

## P1 — High value, quick, fully unblocked

**[221](../completed/221-live-vix-z-flight-quality-yield-slope-z-permanently-zero.md) CLOSED
2026-07-31** — `vix_z`/`flight_quality`/`yield_slope_z` were permanently 0.0 in live serving
(wrong `CacheManager` method collision); fixed via shared per-tf broadcast state, 3 regression
tests added. Not verified against live Kafka (ingestion intentionally stopped) — re-confirm
once it resumes.

| Todo | Why now |
|---|---|
| [229](pending/229-regime-writer-hmm-retry-logic-structurally-unreachable.md) | New 2026-08-02, found reviewing todo 226's branch: hmmlearn 0.3.3's `monitor_.converged` is unconditionally `True` after any completed fit (proven both by source and empirical test), making `regime_writer.py`'s same-seed convergence retry (todo 108) dead code since it shipped. **Design decision settled and proven** (`monitor_.iter < monitor_.n_iter` is the exact fix) — implementation deliberately deferred, sequenced behind the next full corpus run's `iters_used` log data (todo 226's instrumentation) to measure blast radius before paying for the fix + mandatory re-run. P1 because "silent wrong answers are worse than loud crashes," not because it's urgent to implement immediately. |
| [065](pending/065-emission-layer-calibration-proposals.md) | EM-CAL threshold calibration — both prerequisite gates (rebuild, EIC-04) cleared 2026-07-09. **Caution added 2026-07-30**: that clearance predates todo 146/208's grid rework (per-tf lookahead grid; 208's session-gate premise is now fixed, but the grid's actual values are still open, see 208's row above). **Unblocked 2026-08-03**: the corpus pass this was waiting on completed 2026-08-02 21:19 UTC (see 210's confirmation). Ready to calibrate against the corrected corpus now — real design/execution work, not mechanical. |
| [079](pending/079-anytime-valid-e-values-corpus-reruns.md) | Anytime-valid inference pilot (one tf) — new statistical primitive, deliberately staged small |
| [080](pending/080-ensemble-combination-e-candidates-queue.md) | Posterior-blended weighting (L5-1) — testable now via existing A/B judge, zero new data |
| [054](pending/054-shadow-alpha-events-monitoring.md) | Shadow alpha_events monitoring — prevents delayed detection of feature decay/threshold bugs |
| [169](pending/169-no-regime-coverage-completeness-check.md) | **Built and tested 2026-07-24, not yet deployed.** `services/regime_coverage_auditor.py` ships with unit tests (`tests/unit/services/test_regime_coverage_auditor.py`) and matching systemd unit files (`production/systemd/indicagent-regime-coverage-auditor.{service,timer}`, daily 06:00 UTC, same pattern as every other auditor). It already earned its keep once — immediately found 14 symbols, not the 7 known at filing time (closed as [168](../completed/168-seven-symbols-zero-per-symbol-hmm-regime-labels.md)). Remaining: actually enable the timer on the live host (`systemctl enable/start`) — a real persistent infra change, deliberately not done without explicit go-ahead. |
| [167](pending/167-equity-cross-sectional-vs-symbol-hmm-never-falsifier-tested.md) | **Plan changed 2026-07-29 — no longer a standalone equity-scoped relaunch,** folded into 176's queued sequence (market-data-gap catchup → 176's `--refresh` → one full-corpus `ic_engine` pass). **176's `--refresh` step confirmed run 2026-07-30** (see 176's updated entry above), but the sequence's final step (a full-corpus equity+rates `ic_engine` pass) has not yet run — that pass is what would actually close this todo. Currently blocked behind todo 202's in-flight regime_writer→forward_return_writer→cross_sectional_regime_model→ic_engine relaunch (single-writer discipline: do not run a second `ic_engine` pass concurrently). |
**[210](../completed/210-ensemble-ic-worker-scales.md) CLOSED 2026-07-30** — fixed (commit
`75c2eb3a`); live-data verification against a repopulated `ensemble_alpha` still pending the
in-flight `ic_engine` run.

**[179](../completed/179-gate166-concurrent-exposure-diagnostic.md) CLOSED 2026-07-31** —
concluded, not actionable: every method tried found zero replicating positive expectancy in
the per-symbol directional construction; the strategic fork it raised is resolved independently
via Phase 167/T3's decisive pass (T3 cross-sectional long-short passed decisively — see
`docs/research/data-edge-source-thesis.md`), making `docs/research/trade-construction-layer.md`
the concrete near-term next step ahead of Phase 164/165.

**[146](../completed/146-lookahead-grid-per-tf-recalibration.md) CLOSED 2026-07-31** — grid-value
question resolved, no re-migration needed. The one new question it surfaced (decay-walk method
validity for `hold_max_bars`) is absorbed by [208](pending/208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md).

**[124](../completed/124-market-ohlcv-tradeable-view-tier2-audit.md) CLOSED 2026-07-31** — all
10 remaining Tier-2 files resolved (9 migrated to `market_data_ohlcv_tradeable`, 1 reclassified
PERMANENT). Boundary test allow-list's PENDING entries: 0.

## P2 — Real value, not urgent

| Todo | What |
|---|---|
| [218](pending/218-bil-thin-cell-per-symbol-ic-instability.md) | New 2026-07-31, found spot-checking the in-flight `ic_engine` recompute in parallel while it runs: `BIL` (near-zero-vol T-bill ETF) shows implausible per-symbol IC (0.5-0.73, incl. a calendar feature) on thin regime cells (n_independent 116-160) — isolated to BIL only, no other symbol shows the pattern. Not diagnosed; check `passes_fdr` once the run completes before assuming a live-path bug. |
| [208](pending/208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md) | **Updated 2026-07-31 — characterization run is COMPLETE, not still pending.** Steps 1/2 DONE (`forward_return_writer.py`'s same-ET-session gate removed for 5m/15m/1h, `forward_returns` rebuilt clean). The run confirmed migration 269's grid values hold under corrected semantics — **no re-migration needed, [146](completed/146-lookahead-grid-per-tf-recalibration.md) closed on that basis 2026-07-31.** This todo's remaining scope is now the deeper method question 146 surfaced and handed off: does decay-walk-on-pooled-median-IC even make sense for `hold_max_bars` selection, given IC rises alongside CI width rather than decaying within any tested horizon. Real design pass needed (3 candidate approaches in the file), not mechanical. Not blocking anything, including the in-flight `ic_engine` run. |
| [213](pending/213-rolling-vp-suppressed-for-1d-never-independently-reviewed.md) | New 2026-07-30, found while closing 176: `poc_rolling_dist_atr`/`poc_session_rolling_divergence_atr` (D-18's rolling-track VP additions, tf-agnostic by construction) are suppressed for `tf='1d'` via the same code branch as session VP (which correctly doesn't apply to 1d) -- but the rolling case was never independently reviewed for tf-applicability across any of Phase 163's three design-review passes. Likely dropping real signal (a 1d bar's dislocation from a ~2-year value anchor is a coherent auction-market-theory concept per D-18's own argument), not a considered exclusion. Needs an incremental-IC check before promoting, same discipline as any other structural column. Renumbered from 209 -- collided with a same-day, independently-filed todo from the per-tf-active-scale-set final review. |
| [186](pending/186-ic-math-cross-sectional-block-bootstrap-gap.md) | New 2026-07-26, same review as 185: `ic_math.py` has a per-symbol circular block bootstrap but no cross-sectional (pooled-panel) variant, so T5's within-bar_ts rigor check approximated it ad hoc. Lower urgency than 185 — the approximation is conservative and the script says so; do this once a real (non-exploratory) T3/T5 candidate needs it. |
| [214](pending/214-ic-engine-ensemble-ic-engine-shared-compute-refactor.md) | New 2026-07-30, user question mid-session: `ic_engine.py` (5,239 lines) and `ensemble_ic_engine.py` (1,523 lines) independently duplicate the same per-scale compute pattern instead of sharing one implementation — exactly the duplication that let todo 210's bug (one engine masks on `complete_{scale}`, the other silently didn't) exist undetected. **One narrow slice landed 2026-07-30** (commit `955e6fbe`) — the `{scale: {tf: lookahead_bars}}` dict-construction duplicated across `ic_engine.py`/`ensemble_ic_engine.py`/`ops_ensemble_ablation.py` was consolidated into `lookahead_by_scale_from_apr()` (`services/_batch_utils.py`). The actual compute-core consolidation (fetch → mask → rank-IC → walk-forward folds) this todo describes is still open — real refactor, deliberately deferred until the current IC measurement chain (208/210/209/211's fixes, a fresh corpus rebuild) is stable again. |
**[188](../completed/188-t5-replication-15m-deferred-memory-contention.md) CLOSED 2026-08-03** —
15m replication complete via todo 234's fix: cross-sectional-neutral `point_ic`=0.2506, much
closer to 1h's 0.1822 than 1d's 0.0127 -- T5 is substantial at the tf Phase 167's live
construction actually trades, small specifically at 1d.
| [177](pending/177-bar-history-maxlen-caps-windows-beyond-200.md) | **Step 1 (enumeration) done 2026-07-31** — 22 `FeatureFactoryConfig` fields confirmed >200 bars; 19 genuinely `BarHistory`-capped, 2 (`vix_zscore_window`/`yield_curve_zscore_window`) turned out to be a worse, unrelated dead-code-path bug, split out to [221](../completed/221-live-vix-z-flight-quality-yield-slope-z-permanently-zero.md) (since closed). Steps 2-3 (fix-shape decision + IC verification) still correctly deferred pending corpus rebuild. |
| [101](pending/101-migration-duplicate-number-sweep.md) | **Stale row corrected 2026-08-03**: the original 14-group finding was resolved in commit `18551320` (2026-07-18). Current remaining scope is narrower — one brand-new collision at `240` (two concurrent worktree sessions), caught by the guard test (`tests/unit/test_migration_number_uniqueness.py`) and allow-listed there pending a dedicated renumbering session. **Confirmed 2026-08-03: do not casually rename either 240 file** — both are already applied to the live DB; the guard test's own docstring explicitly scopes renumbering as its own higher-risk session, not a quick fix. |
| [108](pending/108-hmm-multi-seed-restart-best-likelihood.md) | `regime_writer.py`'s HMM fit uses a single seed with a same-seed convergence retry, not multi-seed-restart-and-keep-best-log-likelihood. Robustness gap, not a proven bug. **Update 2026-08-02:** todo 229 found the `n_restarts > 1` convergence-vs-likelihood tiebreak this todo relies on has been silently degraded to pure-likelihood ranking by the same `monitor_.converged` bug — 229's fix revives the intended tiebreak behavior as a side effect. Re-read 229 before scoping any further work here. |
| [005](pending/005-ic-regime-transition-purge.md) | Purge regime-transition label noise from IC measurement. **Measurement-first design doc written 2026-08-02** — `docs/plans/2026-08-02-regime-label-transition-quality-measurement-design.md` specs a read-only diagnostic (combined-label smoothing + split purge_back/purge_fwd, paired ΔIC bootstrap, per-tf promotion gate) to test whether either mechanism actually improves IC before any production change. Rejects the original 10-20% ic_sharpe claim as unverified. Design went through an Opus review + rewrite; every number independently re-verified against live DB. Sequenced behind the in-flight `ic_engine` corpus pass completing. Next step is an implementation plan for the diagnostic script itself, not the production fix. |
| [038](pending/038-cross-sectional-collinearity-diagnostic.md) | Cross-sectional feature collinearity diagnostic vs IC |
| [039](pending/039-tag-stratified-ic-population-check.md) | Population-count check before tag-stratified cross-sectional IC |
| [081](pending/081-emission-meta-labeling-and-conviction-cross-ref.md) | Emission meta-labeling gate — check overlap with 065/EM-HYST before building |
| [089](pending/089-ensemble-ic-engine-recurring-cadence.md) | No recurring `ensemble_ic_engine` schedule exists — IC-decay trigger input can go stale |
| [009](pending/009-service-utils-ic-engine-cleanup.md) | Phase B infra cleanup batch — APR compliance sweep, `BaseBatch` promotion, naming vocab, shared-utility DRY fixes. Parts A and D closed 2026-07-31 (commit `bd3c5ced`, done in parallel with the in-flight `ic_engine` corpus run — pure code/infra, no corpus dependency). Part E closed 2026-07-23 via Phase 162-01. Parts B/C (promote 4 scripts to `BaseBatch`+systemd, naming-vocab doc update) remain open — real scoped work, not mechanical. |
| [191](pending/191-feature-scoring-beyond-ic.md) | Feature scoring beyond IC (near-term derived metrics) |
| [052](pending/052-adversarial-data-error-hunt.md) | Adversarial data-error hunt batch job |
| [042](pending/042-15m-chunk-size-retest.md) | Re-test 15m backfill chunk size (likely too conservative) — gate reconfirmed clear 2026-07-19, live probe not yet run (see file) |
| [125](pending/125-tag-calibrator-discovery-oos-gate-not-enforced.md) | TagCalibrator's `discovery_oos_days` OOS-confirmation gate computed but never enforced — new discoveries go live immediately. Zero current blast radius (no live consumer reads the affected tags yet, see 126). |
| [126](pending/126-instrument-tags-valid-to-no-consumer-contract.md) | No `instrument_tags` reader filters on `valid_to` — expiry has no observable effect yet, no contract established for future consumers. Resolve before/alongside 125. |
| [135](pending/135-cross-sectional-regime-grid-shape-never-validated.md) | Cross-sectional regime grid shape (9 equity cells, 6 rates cells) has never been validated as a model-selection question — unlike HMM's K=5, which went through a real BIC study. Distinct from todo 092 (cut-point values within the existing shape). |
| [078](pending/078-frame-outcome-labels-second-outcome-definition.md) | Register frame-outcome (barrier-hit sign) as a second outcome definition alongside forward-return IC, now that `alpha_frames` has real data. Gate cleared 2026-07-12 (todo 093 backfill ran); moved back to pending/ 2026-07-18. Diagnostic value, not a reason to touch 142B's frozen design. |
| [082](pending/082-simulation-validation-lenses-post-142b.md) | Additional read-only simulation/validation lenses over `alpha_frames` (standing permutation nulls, etc.) — same gate-cleared status as 078. No new judgment surface, mechanical. |
| [118](pending/118-migrate-feature-domain-into-concept-registry.md) | Migrate `feature_registry` (`domain='feature'`) into the Concept Registry MVP (shipped 2026-07-13 with only `domain='ensemble_strategy'` seeded). Sequencing blocker resolved (Phase 143 already shipped against `feature_registry` directly, so this is now a plain fold-in, not a race). Touches the live feature lifecycle path — do after 117 proves the actuator pattern. |
| [175](pending/175-structural-candidate-part2-smc-swing-fib-anchored-vwap.md) | Filed 2026-07-23 closing Phase 166: Part 2 of the structural stop/target candidate (SMC/swing/fib/anchored-VWAP, i.e. Phase 164/165's primitives) once those phases land — VP/SR (Part 1, Phase 163) is the only part Phase 166 actually scored. Gated on Phase 164 (not planned) and Phase 165 (researched, not planned). **Same deprioritization as todo 176 applies, per [179](../completed/179-gate166-concurrent-exposure-diagnostic.md)'s now-closed findings** — read that file before resuming. |
| [155](pending/155-price-sanity-status-historical-backfill.md) | New 2026-07-20, filed closing [149](../completed/149-bar-ingestion-price-sanity-guard.md): live pilot measured ~4.1 years to clear the 215M-row historical backlog at `BarAuditor`'s default batch size/cadence. Raising the batch size risks the daemon's 60s systemd watchdog and conflates one-time historical debt with the ongoing live-stream audit. Needs a dedicated one-time backfill tool, decoupled from `BarAuditor`'s cycle, reusing 149's classification primitives and Task 1's TimescaleDB compressed-chunk lessons. Also: oldest-first ordering means the guard protects nothing live until this lands. **Batch its effects into the same next full corpus rebuild as [146](completed/146-lookahead-grid-per-tf-recalibration.md)'s grid fix, not a standalone rebuild.** |
| [156](pending/156-otel-span-coverage-gap-v3-pipeline.md) | **Steps 1+2 done 2026-07-31** — `ensemble_trainer.py`/`alpha_publisher.py` execute() spans (step 1, 2026-07-29); step 2 resolved `BaseBatch.run()` now auto-wraps `execute()` for all 8 subclasses (`_span_attrs()` hook), `BaseWriter` found to already auto-wrap (undercounted before), `BaseDaemon` confirmed can't (no per-unit boundary). Tests green. Remaining: step 3 (broader remaining-services audit: `bar_auditor.py`, `ml_*` batch services) — real scoping question, not mechanical. |
| [157](pending/157-no-mechanical-base-class-compliance-check.md) | Items 1-2 CLOSED 2026-07-31 (base-class + prometheus_client compliance tests). Item 3 (span requirement) unblocked 2026-07-31 by 156's step 2 — concrete scope now: assert `BaseBatch`/`BaseWriter` span-wrapping still exists, document `BaseDaemon` as convention-only. Test not yet written. |
| [166](pending/166-1d-ensemble-eligibility-small-sample-treatment.md) | New 2026-07-21, split out of todo 164: `1d`'s median effective-N (1,222, min 143) is ~32x fewer than `15m`'s, CI width 3x wider — a genuine small-sample power problem (Type II error risk), not a miscalibrated threshold like `1h`'s. Needs a real small-sample statistical treatment (Bayesian shrinkage IC or a calibrated day-clustered bootstrap), scoped as its own plan. |
| [171](pending/171-rates-dual-write-symbol-hmm-reversion-check.md) | New 2026-07-22, a "don't forget" item recorded when closing Phase 144: `rates.dual_write_symbol_hmm=true` was deliberately temporary shadow-mode measurement; F1's non-trigger answered the question but only on a scoped 12-symbol run. Batch into the next full corpus rebuild (same cluster as [146](completed/146-lookahead-grid-per-tf-recalibration.md)/[155](pending/155-price-sanity-status-historical-backfill.md)) — confirm F1 holds at full scale before reverting the flag, don't revert on a partial sample, don't forget to ever revisit it either. |
| [172](pending/172-path-dependent-frame-statistics-order-sensitivity-sweep.md) | New 2026-07-22, found during Phase 148-05's Gate 2 execution: `_max_drawdown` over `alpha_frames` silently produced a non-reproducible number because same-`bar_ts` frames (genuinely simultaneous cross-sectional positions) were treated as sequential in a cumulative-sum walk — fixed for Gate 2 (aggregate per `bar_ts` before the walk), but a related order-sensitivity symptom also surfaced in `frame_gate_passes`'/`evaluate_frame_gate`'s cluster-mean array construction (dict insertion order feeds a fixed-seed bootstrap), unfixed. Two threads: (1) sweep for other path-dependent statistics over frame-level data elsewhere in the codebase, (2) make `frame_gate_passes`'s cluster-mean array order-deterministic. Did not affect Phase 148's actual gate verdicts. |
| [223](pending/223-src-intelligence-i1-i7-dead-code-153-files-30k-lines.md) | New 2026-08-01, found during a "clean up docs tests scripts dead code" survey pass: `src/intelligence/`'s I1-I7 orchestration/plugin tree (~153 files, ~30k lines) has no live production entry point (`services/intelligence_pipeline.py` is physically deleted) — reachable only via `shadow_validator.py`'s weekly job, which queries a table (`shadow_registry`) already confirmed dead. One clean orphaned duplicate (`features/i5_patterns/`, 17 files) already deleted same day. The rest needs an explicit delete-vs-archive decision plus a matching call on 18 Group-A dead-pipeline tests and 26+ Group-B SLA/I7-plugin tests (Group B depends on whether the paused IBKR ingestion chain resumes through the v2.x signal path or not). |
| [224](pending/224-commodity-fx-regime-group-reenablement-decision-todo-041.md) | New 2026-08-01, refreshed/filed as its own todo (previously only referenced inline as "todo 041"), **revised same day** into two independent tracks now that the problem is fully understood: (1) near-term, unblocked — **step 1 DONE 2026-08-01 (migration 280): `fx` enabled**, zero effect on the in-flight `ic_engine` run (config loaded once at startup), takes effect next corpus rebuild; still open — unify `commodity_energy`/`commodity_metals`/`commodity_agri` into one `commodity` group (fixes each sub-group's individual thinness, esp. agri's N=1), and fix `DBC`'s `commodity_broad` tag never being wired into any `tag_filter`; (2) blocked on [225](pending/225-multi-vector-systematic-regime-join-hybrid-sensitivity-symbols.md) — the `AMLP`/`GDX`/`OIH`/`XLE`/`XOP` equity-tag collision, unaffected by unification, still needs 225's gradient approach (or an explicit interim exception) before those 5 symbols' commodity membership can actually be enabled. |
| [226](pending/226-regime-writer-n-iter-convergence-headroom-check.md) | New 2026-08-02. **Step 1 DONE 2026-08-02**: log `model.monitor_.iter` per (symbol, tf) cell (commit 5c86ffeb + fix 7a0d7de1). Next step: analyze distribution to decide if n_iter=200 cap is oversized. |
| [227](pending/227-ic-engine-adaptive-bootstrap-resample-early-stop.md) | New 2026-08-02. Contingent on a design decision: does `_blocked_bootstrap_ci` need bit-identical reproducibility (load-bearing like HMM) or is a documented tolerance acceptable? That choice gates whether adaptive/early-stopping resample is feasible or requires a full redesign. |
| [228](pending/228-corpus-pipeline-unmeasured-steps-io-vs-cpu-triage.md) | New 2026-08-02. **[217](../completed/217-corpus-pipeline-step-timing-instrumentation.md) is now CLOSED** (step_timings.jsonl confirmed live) but only captured steps 5-8 so far — steps 1-4 predate the instrumentation landing mid-run. Needs one more full pipeline run from step 1 to get timing data for all 8 steps. Then: classify steps 1/6/7/8 as I/O- vs CPU-bound before applying thread-tuning lessons from todos 215/216. |
| [235](pending/235-t3-5m-construction-never-tested-15m-is-a-default-not-a-finding.md) | New 2026-08-03, user question mid-session. Phase 167's live tracker trades T3 at 15m only -- checked, that's an inherited default from the original falsification script, not a comparative finding. The one existing 5m cost-hurdle result (todo 030) tested standalone directional IC, not T3's netted dollar-neutral spread, which the research doc itself says has different cost dynamics. Run T3's actual methodology at 5m before assuming 15m is the right choice. |

**[231](../completed/231-t5-1h-lightgbm-check-oom-corpus-outgrew-script.md) CLOSED 2026-08-02** —
fixed a chunked-fetch OOM (shared fix across all 3 T5 scripts) and used it to re-verify the 1h
finding under corrected `forward_returns`: holds, magnitude down ~30-40%.

**[234](../completed/234-t5-15m-lightgbm-oom-survives-both-prior-fixes.md) CLOSED 2026-08-03** —
15m hit two further OOMs on top of 231's fix; root-caused via `superpowers:systematic-debugging`
(background Opus 5 agent) instead of another patch — the wide-DataFrame fetch pattern itself was
the defect (measured ~18.5GB before any processing started), not any single operation on it.
Fixed by building the training matrix directly from asyncpg rows, matching
`ensemble_trainer.py`'s existing production pattern. 15m completed clean, peak 14.65GB (was
~21.8GB at kill). Also closed [232](../completed/232-chunked-fetch-oom-pattern-untouched-in-6-other-files.md)
as moot — its named helper functions no longer exist post-rewrite.

## P3 — Hygiene, docs, process (opportunistic)

**[222](../completed/222-cross-asset-state-reuses-full-featurecache.md) CLOSED 2026-07-31** —
extracted `CrossAssetState` (`src/intelligence/feature_cache.py`) + shared
`_compute_cross_asset()` free function; `feature_vector_pipeline.py`'s broadcast state no
longer pays for `FeatureCache`'s other ~87 fields. `FeatureCache.update_cross_asset()` now
delegates to the same function (one implementation, not two). `backfill_feature_factory.py`
deliberately left untouched — its incremental algorithm genuinely differs from the live
per-tick recompute, unifying them would be a behavior change to the corpus-computation path.
97/97 directly-affected tests green, full suite green.

**[236](../completed/236-hmm-duration-and-weekly-atr-dist-implausible-extreme-values.md) CLOSED
2026-08-03** — root-caused via `superpowers:systematic-debugging`: `hmm_duration`'s implausible
values (also silently affecting `hmm_regime_prob`/`hmm_entropy`) traced to a since-deleted K3
`FeatureCache` counter (todo 207) that never reset for symbols where its own low-quality forward
model rarely changed label — airtight, 100% of extreme values on `regime IS NULL` rows, zero on
`regime IS NOT NULL`. `ops_stale_k3_hmm_fields_cleanup.py --apply` nulled 10,062,758 stale rows
across 77 (symbol, tf) pairs; verified live, audited via `integrity_monitor`. Split off the
ATR-floor half (much bigger shared-helper question, not root-caused to the same certainty) as
[237](pending/237-atr-distance-features-no-floor-guard-shared-helper.md).

| Todo | What |
|---|---|
| [237](pending/237-atr-distance-features-no-floor-guard-shared-helper.md) | New 2026-08-03, split from 236. `feature_factory.py`'s shared `_above`/`_below` helper (15+ ATR-normalized distance columns) guards `atr_val > 0` but not "numerically tiny" — confirmed real via BIL/5m/2012 (a near-zero-ATR blowup), but only 3-6 rows out of 25.4M cross any visible threshold. Needs a real APR-governed floor design, not a rushed two-column patch. |
| [056](pending/056-phase146-147-v2x-retirement-stale.md) | ROADMAP Phase 147/148 text rewritten 2026-07-19 (operator call resolved: archive not delete, decouple from proof gates). Remaining scope: the actual decommission-in-fact execution (git mv v2.x code to archive/, disable dead systemd units, rename-not-drop the frozen v2.x tables) — real multi-file operation, do with a clean git state. |
| [225](pending/225-multi-vector-systematic-regime-join-hybrid-sensitivity-symbols.md) | Downgraded P2→P3 2026-08-01 per its own pilot finding (was left un-actioned in this file until this cleanup pass): read-only pilot on 5 hybrid symbols (`OIH`/`XLE`/`XOP`/`AMLP`/`GDX`) came back negative — the one BH-FDR survivor (`GDX momentum_z_fast`) failed cross-timeframe replication, flat null. Real information, not wasted effort; don't build the Fix steps until a better-motivated candidate surfaces or the universe scales. Full methodology in the todo file's "Pilot result" section. |
| [115](pending/115-days-to-month-end-exact-redundancy.md) | `days_to_month_end` is an exact affine complement of `month_position` (Pearson correlation -1) — perfectly collinear, remove one. |

**[233](../completed/233-timescaledb-compression-policy-scheduler-silent-noop.md) CLOSED
2026-08-03** — permanent fix (`services/compression_auditor.py`) confirmed deployed and active
via `systemctl is-active`; file was fully documenting its own resolution already, just never
moved to `completed/`.

**[232](../completed/232-chunked-fetch-oom-pattern-untouched-in-6-other-files.md) CLOSED
2026-08-02** — already in `completed/` (fixed drift here 2026-08-03; this file previously
linked `pending/232`, which no longer exists). Closed as moot alongside todo 234: its named
helper functions no longer exist post-rewrite.

---

**Not in this list:** anything in `deferred/` (phase-gated or corpus-rerun-batched) or
`completed/` (done). Check those folders directly for that work.
