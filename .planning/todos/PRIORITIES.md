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

**Current probable path (updated 2026-07-30 evening -- phase-level, see `.planning/STATE.md` for
full detail, not duplicated here):** Phase 164/165/167 all COMPLETE; user has redirected priority
away from Phase 156-159 (execution) toward validating the features/regimes/IC/ensemble stack
first. The per-tf-active-scale-set branch merged 2026-07-30 (`ic_engine.py`'s hardcoded scales
-> per-tf `active_scales_for(tf)`), whose own final review found and same-day fixed todo 208
(the same-ET-session forward-return completeness gate was silently zeroing 1h's completeness
for a reason that doesn't hold up) -- `forward_returns` truncated and rebuilt clean under the
corrected definition. The three follow-on `_SCALES`-hardcoding cleanups (209/210/211) scoped in
`docs/plans/2026-07-30-ic-scale-cleanup-plan.md` are all now DONE (211 closed 2026-07-30).
Canary RNG seeding fixed (todo 203) but a sibling POOLED-gate anomaly (todo 204) is still
undiagnosed.

**2026-08-01: regime-stratification todo cluster consolidated.** `docs/research/stratification-dimension-unification.md`
(the canonical doc for "what other ways could we stratify/condition IC by regime" — already
covered dispersion/correlation/term-structure/factor-regime/liquidity as named candidates, plus
a full governance model, months before today's conversation reinvented several of them) was a
full milestone-stage stale (last touched 2026-07-06; Phase 144 completed 2026-07-22 since then,
D-05's verdict landed, Phase 145 unblocked-but-never-started). Reconciled and cross-linked to
todos 135 (grid-shape never validated — literally "was the equity 9-cell grid BIC-selected the
way HMM K=5 was" — no), 167 (equity-vs-symbol-HMM substitution test, near an answer, blocked
only on the in-flight `ic_engine` run), 224 (fx/commodity enablement), 225 (gradient-conditional
IC, explicitly a different mechanism from this doc's contract, kept distinct), and 111/Phase 145
(the actual planned vehicle to formalize the contract and scope new candidates — unblocked since
2026-07-22, not started). **Read the doc's "Reconciliation pass (2026-08-01)" section first**
before re-deriving any of this from scratch in a future session.

**2026-08-01: todo 220 closed** (docs/agents/platform/architecture DAG registry resync + CLAUDE.md
OTel label fix). Surfaced new project-level context worth flagging here: the user stated the
v2.x I1-I7 path will eventually be revived as a second, conventional intelligence path alongside
v3.0's AlphaEngine, not retired permanently (`project_dual_intelligence_path_plan.md` in
memory). This softens todo 223's delete-vs-archive call (lean archive, Group B explicitly kept)
and is in mild tension with todo 056's "decommission-in-fact" framing (archive-not-delete is
still compatible, but the systemd-unit-disable / table-rename steps there should be re-read
against this plan before executing, not assumed still fully correct as scoped).

**Live checkpoint 2026-07-31 ~20:35 UTC (re-verify before trusting -- `grep symbol_computed
logs/ic_engine.log`, `ps aux | grep ic_engine`, `SELECT count(*) FROM feature_ic_scores`):**
`ic_engine` at 49/80 symbols, `feature_ic_scores` at 1,637,175 rows, workers healthy (8
forkserver processes, high CPU, no errors in log tail). ~27h elapsed since the 13:19 EDT
2026-07-30 restart -> ETA **~2026-08-01 midday/early afternoon**, consistent with the prior
checkpoint below. Two todos closed in parallel while this run is in flight (pure code, no corpus
dependency): **todo 124** (`market_data_ohlcv` Tier-2 boundary migration, commit `82861b0b`) and
**todo 009 Parts A/D** (APR sweep + pure-function cleanup, commit `bd3c5ced`). New **todo 218**
filed 2026-07-31 spot-checking the live recompute: `BIL` showing implausible per-symbol IC on
thin regime cells -- not diagnosed, check `passes_fdr` once the run completes.

**Prior checkpoint, 2026-07-30 22:35 UTC-ish (superseded by the above, kept for continuity):**
`ic_engine` (step 5/8) was killed and restarted same day to test todo 215's thread-count APR
bump; the restart also picked up todo 215's own just-landed code change, which invalidated every
fingerprint and forced a full 80-symbol recompute (wall-clock cost only, no data lost -- see
STATE.md for the full incident and the banked lesson `feedback_restart_batch_job_check_code_diff_first`).
**Todo 215 CLOSED** -- real measured speedup confirmed across two symbols of different
weight (BTAL 1.28x, CWB 1.35x, ~1.3x average), well below the 2.4x isolated benchmark as
expected from contention, but real and consistent. Decision made: threads=2 kept as the
standing value (near the safe ceiling given 12 physical cores / 8 workers already busy);
not worth testing higher without a dedicated idle-box benchmark.

**Todo 146/208's characterization diagnostic (`ops_lookahead_horizon_response.py`) COMPLETE,
decision resolved: no re-migration, no third rebuild.** Results (see
`completed/146-lookahead-grid-per-tf-recalibration.md` for full writeup) confirm today's
session-gate fix was correct (baseline 1h collapses to 0 completeness at 6 bars;
production-matching overnight mode holds ~1.0 completeness to 70+ bars) AND confirm migration
269's provisional grid is not shown wrong -- every current per-tf value sits inside the
completeness~1.0, FDR-significant zone under corrected semantics. **Todo 146 closed 2026-07-31
on this basis.** The deeper question (does `_select_hold_bars_from_decay`'s premise even hold,
given median IC rises with CI width rather than decaying within any tested horizon) is now
explicitly owned by todo 208 (updated same day), not an action item on its own. **The in-flight
`ic_engine` pass is confirmed trustworthy -- nothing blocks trusting its output once it
completes.**

**Sequencing plan, next few days:** (1) let `ic_engine` finish; (2) once complete, run
everything gated on it -- todo 203's final `ops_canary_integrity_assert.py` confirmation, todo
210's live verification against a repopulated `ensemble_alpha`, todo 065 (EM-CAL calibration),
todo 167 (equity vs symbol-HMM falsifier test), todo 204; (3) only once that chain is stable,
start todo 214 (deferred refactor) (todo 211 corrected -- both parts already CLOSED as of 14:54
EDT today, commit `02506239`, not open work); (4) separately, not blocked on any of the above --
**todo 216 CLOSED 2026-08-02** -- root cause found without needing a live profile (BLAS thread
oversubscription, fixed system-wide across all 5 ProcessPoolExecutor batch services, migration
281), real-world wall-clock delta self-confirms on the next `regime_writer` run's own logs, no
follow-up action needed; scope Phase 167/T3's
cost-hurdle-adjusted spread construction (`docs/research/trade-construction-layer.md`) as a new
phase via `/gsd-discuss-phase`; this is the actual highest-value next step, proceeding is the
user's call. Full detail and live-verification commands: `.planning/STATE.md`'s "Current saga"
section.

---

## P0 — Fix soon (integrity/correctness gaps already surfaced)

**Live P0 as of 2026-07-29:** [203](pending/203-canary-rng-seed-not-per-symbol-cross-sectional-pseudo-replication.md)
— **seeding fix + broadcast-feature audit DONE 2026-07-29** (see plan
`docs/superpowers/plans/2026-07-29-canary-seed-and-broadcast-feature-audit.md`);
`symbol` now included in `_canary_sub_seed`'s hash, `ops_broadcast_feature_audit.py`
confirms `vix_z`/`yield_slope_z`/`flight_quality` + all session/calendar features
share the same pseudo-replication exposure the canaries had. Building an actual
broadcast-aware significance test remains open (real design question, not filed as
its own todo yet). Full end-to-end confirmation (a green
`ops_canary_integrity_assert.py` run) still waits on the in-flight `ic_engine` pass
(`.planning/STATE.md`'s Tier -1).
Sibling finding [204](pending/204-canary-acausal-placebo-pooled-not-detected.md) —
`canary_acausal_placebo` not clearing its POOLED gate for an unrelated, undiagnosed
reason.

| Todo | Gap |
|---|---|
| [099](pending/099-bootstrap-ci-staged-validation-gate-not-cleared-5m-residual.md) | P2 — the bootstrap CI staged-validation gate's 6 SUSPECT cells trace to 5 diagnostic-only (`is_pooled=false`) breaches + 1 capital-relevant cell that independently clears its own bound — no longer blocks Plan 07. Underlying statistical question (why 5m autocorrelation/momentum features resist both Fisher-z and block-bootstrap) remains open as non-blocking follow-up. |

**[219](../completed/219-feature-vector-pipeline-crash-loop-and-missing-checked-in-unit.md) CLOSED 2026-07-31** —
`indicagent-feature-vector-pipeline` had been crash-looping/`start-limit-hit` since 2026-07-29
07:36 EDT (~2 days), surfaced by todo 200's registry-integrity test. Fixed same day: missing
`_THRESHOLD_KEYS` entry added, daemon restarted and confirmed stable; missing checked-in
`production/systemd/` unit file also added (repo/deploy drift).

## P1 — High value, quick, fully unblocked

**[221](../completed/221-live-vix-z-flight-quality-yield-slope-z-permanently-zero.md) CLOSED
2026-07-31** — live pipeline was calling `CacheManager.update_cross_asset()` (a same-named but
unrelated method that just stores a raw spread-feature payload) instead of `FeatureCache`'s
real implementation; `vix_z`/`flight_quality`/`yield_slope_z` were permanently 0.0 in live
serving. Fixed via a new shared per-tf broadcast state (avoids corrupting the trailing z-score
deque by refreshing only on genuine SPY/TLT/SHY bars, then copying onto every symbol's own
cache), `CacheManager`'s method renamed to `store_cross_asset_payload` to remove the collision.
3 regression tests added. Corpus/backfill path was already unaffected and untouched by this
fix. Not verified against live Kafka (ingestion intentionally stopped) — re-confirm once it
resumes.

| Todo | Why now |
|---|---|
| [229](pending/229-regime-writer-hmm-retry-logic-structurally-unreachable.md) | New 2026-08-02, found reviewing todo 226's branch: hmmlearn 0.3.3's `monitor_.converged` is unconditionally `True` after any completed fit (proven both by source and empirical test), making `regime_writer.py`'s same-seed convergence retry (todo 108) dead code since it shipped. **Design decision settled and proven** (`monitor_.iter < monitor_.n_iter` is the exact fix) — implementation deliberately deferred, sequenced behind the next full corpus run's `iters_used` log data (todo 226's instrumentation) to measure blast radius before paying for the fix + mandatory re-run. P1 because "silent wrong answers are worse than loud crashes," not because it's urgent to implement immediately. |
| [217](pending/217-corpus-pipeline-step-timing-instrumentation.md) | **Implemented 2026-07-30** (commit `e87cefa6`) — `run_step()` now appends to `logs/corpus_pipeline/step_timings.jsonl`. Not yet verified live (no step has completed via `run_step` since the commit landed mid-run — the in-flight `ic_engine` run was already past step 4 when it merged); will self-confirm the moment the current `ic_engine` step finishes or fails. Close once that first line appears. |
| [065](pending/065-emission-layer-calibration-proposals.md) | EM-CAL threshold calibration — both prerequisite gates (rebuild, EIC-04) cleared 2026-07-09. **Caution added 2026-07-30**: that clearance predates todo 146/208's grid rework (per-tf lookahead grid; 208's session-gate premise is now fixed, but the grid's actual values are still open, see 208's row above). Calibrating against pre-rebuild data now risks redoing this once the corpus/grid settle — same mistake this todo's own history already flagged once. Wait for the in-flight `ic_engine` pass to finish (`.planning/STATE.md`'s Tier -1) before starting. |
| [079](pending/079-anytime-valid-e-values-corpus-reruns.md) | Anytime-valid inference pilot (one tf) — new statistical primitive, deliberately staged small |
| [080](pending/080-ensemble-combination-e-candidates-queue.md) | Posterior-blended weighting (L5-1) — testable now via existing A/B judge, zero new data |
| [054](pending/054-shadow-alpha-events-monitoring.md) | Shadow alpha_events monitoring — prevents delayed detection of feature decay/threshold bugs |
| [169](pending/169-no-regime-coverage-completeness-check.md) | **Built and tested 2026-07-24, not yet deployed.** `services/regime_coverage_auditor.py` ships with unit tests (`tests/unit/services/test_regime_coverage_auditor.py`) and matching systemd unit files (`production/systemd/indicagent-regime-coverage-auditor.{service,timer}`, daily 06:00 UTC, same pattern as every other auditor). It already earned its keep once — immediately found 14 symbols, not the 7 known at filing time (closed as [168](../completed/168-seven-symbols-zero-per-symbol-hmm-regime-labels.md)). Remaining: actually enable the timer on the live host (`systemctl enable/start`) — a real persistent infra change, deliberately not done without explicit go-ahead. |
| [167](pending/167-equity-cross-sectional-vs-symbol-hmm-never-falsifier-tested.md) | **Plan changed 2026-07-29 — no longer a standalone equity-scoped relaunch,** folded into 176's queued sequence (market-data-gap catchup → 176's `--refresh` → one full-corpus `ic_engine` pass). **176's `--refresh` step confirmed run 2026-07-30** (see 176's updated entry above), but the sequence's final step (a full-corpus equity+rates `ic_engine` pass) has not yet run — that pass is what would actually close this todo. Currently blocked behind todo 202's in-flight regime_writer→forward_return_writer→cross_sectional_regime_model→ic_engine relaunch (single-writer discipline: do not run a second `ic_engine` pass concurrently). |
**[210](../completed/210-ensemble-ic-worker-scales.md) CLOSED 2026-07-30** — fixed (commit
`75c2eb3a`); live-data verification against a repopulated `ensemble_alpha` still pending the
in-flight `ic_engine` run.

**[179](../completed/179-gate166-concurrent-exposure-diagnostic.md) CLOSED 2026-07-31** —
investigation reads as concluded, not actionable (every method tried found zero replicating
positive expectancy in the per-symbol directional construction); the strategic fork it raised
is resolved independently via Phase 167/T3's decisive pass. See the completed file's closing
note for detail.

**[146](../completed/146-lookahead-grid-per-tf-recalibration.md) CLOSED 2026-07-31** — all
three Fix steps done, and the 2026-07-30 characterization run resolved the reopened grid-value
question (no re-migration needed). The one genuinely new question it surfaced (decay-walk
method validity for `hold_max_bars`) is explicitly absorbed by [208](pending/208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md),
updated same-day — see 208's row below for its remaining scope.

**[124](../completed/124-market-ohlcv-tradeable-view-tier2-audit.md) CLOSED 2026-07-31**
(commit `82861b0b`, done in parallel with the in-flight `ic_engine` run — pure code, no
corpus dependency) — remaining 10 Tier-2 files all resolved: 9 migrated to
`market_data_ohlcv_tradeable` (several genuine correctness gaps, not just style/DRY —
see the completed file for detail), 1 (`infrastructure_run_historical_pipeline.py`)
mostly reclassified PERMANENT with written rationale. Boundary test allow-list's
PENDING entries: 0.

**Note (2026-07-26):** [179](../completed/179-gate166-concurrent-exposure-diagnostic.md)'s "strategic choice" fork is
now resolved in one direction — T3 (cross-sectional long-short) passed decisively today (see
`docs/research/data-edge-source-thesis.md`, T3 section), making `docs/research/trade-construction-layer.md`
the concrete near-term next step ahead of Phase 164/165. Not yet filed as a todo (it's phase-scoped,
not a `pending/` item) — the recommended move is cost-hurdle-adjusting the spread construction, then
scoping it as a phase via `/gsd-discuss-phase`.

## P2 — Real value, not urgent

| Todo | What |
|---|---|
| [218](pending/218-bil-thin-cell-per-symbol-ic-instability.md) | New 2026-07-31, found spot-checking the in-flight `ic_engine` recompute in parallel while it runs: `BIL` (near-zero-vol T-bill ETF) shows implausible per-symbol IC (0.5-0.73, incl. a calendar feature) on thin regime cells (n_independent 116-160) — isolated to BIL only, no other symbol shows the pattern. Not diagnosed; check `passes_fdr` once the run completes before assuming a live-path bug. |
| [208](pending/208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md) | **Updated 2026-07-31 — characterization run is COMPLETE, not still pending.** Steps 1/2 DONE (`forward_return_writer.py`'s same-ET-session gate removed for 5m/15m/1h, `forward_returns` rebuilt clean). The run confirmed migration 269's grid values hold under corrected semantics — **no re-migration needed, [146](completed/146-lookahead-grid-per-tf-recalibration.md) closed on that basis 2026-07-31.** This todo's remaining scope is now the deeper method question 146 surfaced and handed off: does decay-walk-on-pooled-median-IC even make sense for `hold_max_bars` selection, given IC rises alongside CI width rather than decaying within any tested horizon. Real design pass needed (3 candidate approaches in the file), not mechanical. Not blocking anything, including the in-flight `ic_engine` run. |
| [213](pending/213-rolling-vp-suppressed-for-1d-never-independently-reviewed.md) | New 2026-07-30, found while closing 176: `poc_rolling_dist_atr`/`poc_session_rolling_divergence_atr` (D-18's rolling-track VP additions, tf-agnostic by construction) are suppressed for `tf='1d'` via the same code branch as session VP (which correctly doesn't apply to 1d) -- but the rolling case was never independently reviewed for tf-applicability across any of Phase 163's three design-review passes. Likely dropping real signal (a 1d bar's dislocation from a ~2-year value anchor is a coherent auction-market-theory concept per D-18's own argument), not a considered exclusion. Needs an incremental-IC check before promoting, same discipline as any other structural column. Renumbered from 209 -- collided with a same-day, independently-filed todo from the per-tf-active-scale-set final review. |
| [186](pending/186-ic-math-cross-sectional-block-bootstrap-gap.md) | New 2026-07-26, same review as 185: `ic_math.py` has a per-symbol circular block bootstrap but no cross-sectional (pooled-panel) variant, so T5's within-bar_ts rigor check approximated it ad hoc. Lower urgency than 185 — the approximation is conservative and the script says so; do this once a real (non-exploratory) T3/T5 candidate needs it. |
| [214](pending/214-ic-engine-ensemble-ic-engine-shared-compute-refactor.md) | New 2026-07-30, user question mid-session: `ic_engine.py` (5,239 lines) and `ensemble_ic_engine.py` (1,523 lines) independently duplicate the same per-scale compute pattern instead of sharing one implementation — exactly the duplication that let todo 210's bug (one engine masks on `complete_{scale}`, the other silently didn't) exist undetected. **One narrow slice landed 2026-07-30** (commit `955e6fbe`) — the `{scale: {tf: lookahead_bars}}` dict-construction duplicated across `ic_engine.py`/`ensemble_ic_engine.py`/`ops_ensemble_ablation.py` was consolidated into `lookahead_by_scale_from_apr()` (`services/_batch_utils.py`). The actual compute-core consolidation (fetch → mask → rank-IC → walk-forward folds) this todo describes is still open — real refactor, deliberately deferred until the current IC measurement chain (208/210/209/211's fixes, a fresh corpus rebuild) is stable again. |
| [188](pending/188-t5-replication-15m-deferred-memory-contention.md) | T5's 1d replication (2026-07-27) partially confirmed the non-linear-combiner finding but at ~16x smaller magnitude than the original 1h result -- confirmed SMALL not LARGE. 15m (the tf Phase 167's live construction actually trades) is the directly actionable replication, deferred on memory contention with todo 183's concurrent recompute. **Todo 183 has since completed and the host has ~20GB free (re-verify before running) -- the deferral reason is gone, ready to run now.** The `ctf_momentum` 1d-vs-15m sign flip this originally surfaced is resolved -- see [189](pending/189-ctf-momentum-1d-self-referential-htf-not-cross-timeframe.md). |
| [177](pending/177-bar-history-maxlen-caps-windows-beyond-200.md) | **Step 1 (enumeration) done 2026-07-31** — 22 `FeatureFactoryConfig` fields confirmed >200 bars; 19 genuinely `BarHistory`-capped, 2 (`vix_zscore_window`/`yield_curve_zscore_window`) turned out to be a worse, unrelated dead-code-path bug, split out to [221](../completed/221-live-vix-z-flight-quality-yield-slope-z-permanently-zero.md) (since closed). Steps 2-3 (fix-shape decision + IC verification) still correctly deferred pending corpus rebuild. |
| [101](pending/101-migration-duplicate-number-sweep.md) | `production/migrations/` has 13 duplicate-number groups (001, 031, 038, 050-052, 064, 138, 152, 168, 178, 214-215). Finding + recommended approach only; deliberately not executed given live-DB rename risk. |
| [108](pending/108-hmm-multi-seed-restart-best-likelihood.md) | `regime_writer.py`'s HMM fit uses a single seed with a same-seed convergence retry, not multi-seed-restart-and-keep-best-log-likelihood. Robustness gap, not a proven bug. **Update 2026-08-02:** todo 229 found the `n_restarts > 1` convergence-vs-likelihood tiebreak this todo relies on has been silently degraded to pure-likelihood ranking by the same `monitor_.converged` bug — 229's fix revives the intended tiebreak behavior as a side effect. Re-read 229 before scoping any further work here. |
| [005](pending/005-ic-regime-transition-purge.md) | Purge regime-transition label noise from IC measurement. **Re-verified 2026-08-02: still valid** — `cross_sectional_regime_model.py` (Phase 144's live successor to `equity_regime_model.py`) confirmed to still have zero transition smoothing, same gap as originally found. Gate cleared 2026-07-30; remaining open item is a design decision (fix at the source vs. downstream purge mask — recommend source fix) plus sequencing behind the in-flight `ic_engine` corpus pass completing. |
| [038](pending/038-cross-sectional-collinearity-diagnostic.md) | Cross-sectional feature collinearity diagnostic vs IC |
| [039](pending/039-tag-stratified-ic-population-check.md) | Population-count check before tag-stratified cross-sectional IC |
| [081](pending/081-emission-meta-labeling-and-conviction-cross-ref.md) | Emission meta-labeling gate — check overlap with 065/EM-HYST before building |
| [089](pending/089-ensemble-ic-engine-recurring-cadence.md) | No recurring `ensemble_ic_engine` schedule exists — IC-decay trigger input can go stale |
| [009](pending/009-service-utils-ic-engine-cleanup.md) | Phase B infra cleanup batch — APR compliance sweep, `BaseBatch` promotion, naming vocab, shared-utility DRY fixes. Parts A and D closed 2026-07-31 (commit `bd3c5ced`, done in parallel with the in-flight `ic_engine` corpus run — pure code/infra, no corpus dependency). Part E closed 2026-07-23 via Phase 162-01. Parts B/C (promote 4 scripts to `BaseBatch`+systemd, naming-vocab doc update) remain open — real scoped work, not mechanical. |
| [191](pending/191-feature-scoring-beyond-ic.md) | Feature scoring beyond IC (near-term derived metrics) |
| [052](pending/052-adversarial-data-error-hunt.md) | Adversarial data-error hunt batch job |
| [042](pending/042-15m-chunk-size-retest.md) | Re-test 15m backfill chunk size (likely too conservative) — gate reconfirmed clear 2026-07-19, live probe not yet run (see file) |
| [024](pending/024-feature-decay-observatory.md) | Feature decay/crowding observatory dashboard |
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
| [111](pending/111-stratification-classification.md) | **Unblocked 2026-07-22** — Phase 144's D-05 verdict landed (registered as ROADMAP Phase 145). Bumped P3→P2: real, actionable design work now (the `StratificationDimension` Protocol + `concept_registry` row-grain decision), not a blocked placeholder. Read Phase 144's verdict before starting — a group deficient on both axes (rates/15m/5m) is a live case the design needs to handle. |
| [171](pending/171-rates-dual-write-symbol-hmm-reversion-check.md) | New 2026-07-22, a "don't forget" item recorded when closing Phase 144: `rates.dual_write_symbol_hmm=true` was deliberately temporary shadow-mode measurement; F1's non-trigger answered the question but only on a scoped 12-symbol run. Batch into the next full corpus rebuild (same cluster as [146](completed/146-lookahead-grid-per-tf-recalibration.md)/[155](pending/155-price-sanity-status-historical-backfill.md)) — confirm F1 holds at full scale before reverting the flag, don't revert on a partial sample, don't forget to ever revisit it either. |
| [172](pending/172-path-dependent-frame-statistics-order-sensitivity-sweep.md) | New 2026-07-22, found during Phase 148-05's Gate 2 execution: `_max_drawdown` over `alpha_frames` silently produced a non-reproducible number because same-`bar_ts` frames (genuinely simultaneous cross-sectional positions) were treated as sequential in a cumulative-sum walk — fixed for Gate 2 (aggregate per `bar_ts` before the walk), but a related order-sensitivity symptom also surfaced in `frame_gate_passes`'/`evaluate_frame_gate`'s cluster-mean array construction (dict insertion order feeds a fixed-seed bootstrap), unfixed. Two threads: (1) sweep for other path-dependent statistics over frame-level data elsewhere in the codebase, (2) make `frame_gate_passes`'s cluster-mean array order-deterministic. Did not affect Phase 148's actual gate verdicts. |
| [173](pending/173-ensemble-alpha-1h-1d-oos-scoring-gap.md) | New 2026-07-22, found after Gate 1's real (irreversible) run: `ensemble_alpha` has zero OOS-side rows at `1h` for any weight_version and zero at `1d` for the champion/default weight_version — Gate 1's recorded PASS verdict covers only 5m/15m (640 cells), disclosed in the promotion decision record rather than presented as a full 4-timeframe pass. Cannot re-run Gate 1 to fix (D-04); investigation-first, may overlap todo 089/166's root cause. |
| [223](pending/223-src-intelligence-i1-i7-dead-code-153-files-30k-lines.md) | New 2026-08-01, found during a "clean up docs tests scripts dead code" survey pass: `src/intelligence/`'s I1-I7 orchestration/plugin tree (~153 files, ~30k lines) has no live production entry point (`services/intelligence_pipeline.py` is physically deleted) — reachable only via `shadow_validator.py`'s weekly job, which queries a table (`shadow_registry`) already confirmed dead. One clean orphaned duplicate (`features/i5_patterns/`, 17 files) already deleted same day. The rest needs an explicit delete-vs-archive decision plus a matching call on 18 Group-A dead-pipeline tests and 26+ Group-B SLA/I7-plugin tests (Group B depends on whether the paused IBKR ingestion chain resumes through the v2.x signal path or not). |
| [224](pending/224-commodity-fx-regime-group-reenablement-decision-todo-041.md) | New 2026-08-01, refreshed/filed as its own todo (previously only referenced inline as "todo 041"), **revised same day** into two independent tracks now that the problem is fully understood: (1) near-term, unblocked — **step 1 DONE 2026-08-01 (migration 280): `fx` enabled**, zero effect on the in-flight `ic_engine` run (config loaded once at startup), takes effect next corpus rebuild; still open — unify `commodity_energy`/`commodity_metals`/`commodity_agri` into one `commodity` group (fixes each sub-group's individual thinness, esp. agri's N=1), and fix `DBC`'s `commodity_broad` tag never being wired into any `tag_filter`; (2) blocked on [225](pending/225-multi-vector-systematic-regime-join-hybrid-sensitivity-symbols.md) — the `AMLP`/`GDX`/`OIH`/`XLE`/`XOP` equity-tag collision, unaffected by unification, still needs 225's gradient approach (or an explicit interim exception) before those 5 symbols' commodity membership can actually be enabled. |
| [225](pending/225-multi-vector-systematic-regime-join-hybrid-sensitivity-symbols.md) | New 2026-08-01. **Pilot run same day (read-only, no production writes) came back negative** — 5 hybrid symbols (`OIH`/`XLE`/`XOP`/`AMLP`/`GDX`) × 10 features, BH-FDR-corrected, 4 tests survived at `tf=1d`; the standout (`GDX momentum_z_fast`) failed cross-timeframe replication even under a horizon-matched retest (1h `return_slow`, ~3 trading days) — flat null, no differential. Real information, not wasted effort: recommend downgrading P2→P3 and not building the Fix steps until a better-motivated candidate surfaces or the universe scales. Full methodology and numbers in the todo file's "Pilot result" section. |
| [226](pending/226-regime-writer-n-iter-convergence-headroom-check.md) | New 2026-08-02. **Step 1 DONE 2026-08-02**: log `model.monitor_.iter` per (symbol, tf) cell (commit 5c86ffeb + fix 7a0d7de1). Next step: analyze distribution to decide if n_iter=200 cap is oversized. |
| [227](pending/227-ic-engine-adaptive-bootstrap-resample-early-stop.md) | New 2026-08-02. Contingent on a design decision: does `_blocked_bootstrap_ci` need bit-identical reproducibility (load-bearing like HMM) or is a documented tolerance acceptable? That choice gates whether adaptive/early-stopping resample is feasible or requires a full redesign. |
| [228](pending/228-corpus-pipeline-unmeasured-steps-io-vs-cpu-triage.md) | New 2026-08-02. Blocked on [217](pending/217-corpus-pipeline-step-timing-instrumentation.md) landing + one full pipeline run (step-time data for all 8 steps now available). Then: classify steps 1/6/7/8 as I/O- vs CPU-bound before applying thread-tuning lessons from todos 215/216. |

## P3 — Hygiene, docs, process (opportunistic)

**[222](../completed/222-cross-asset-state-reuses-full-featurecache.md) CLOSED 2026-07-31** —
extracted `CrossAssetState` (`src/intelligence/feature_cache.py`) + shared
`_compute_cross_asset()` free function; `feature_vector_pipeline.py`'s broadcast state no
longer pays for `FeatureCache`'s other ~87 fields. `FeatureCache.update_cross_asset()` now
delegates to the same function (one implementation, not two). `backfill_feature_factory.py`
deliberately left untouched — its incremental algorithm genuinely differs from the live
per-tick recompute, unifying them would be a behavior change to the corpus-computation path.
97/97 directly-affected tests green, full suite green.

| Todo | What |
|---|---|
| [056](pending/056-phase146-147-v2x-retirement-stale.md) | ROADMAP Phase 147/148 text rewritten 2026-07-19 (operator call resolved: archive not delete, decouple from proof gates). Remaining scope: the actual decommission-in-fact execution (git mv v2.x code to archive/, disable dead systemd units, rename-not-drop the frozen v2.x tables) — real multi-file operation, do with a clean git state. |
| [022](pending/022-bi-superset.md) | Self-service BI (Superset) for ad-hoc analytics |
| [115](pending/115-days-to-month-end-exact-redundancy.md) | `days_to_month_end` is an exact affine complement of `month_position` (Pearson correlation -1) — perfectly collinear, remove one. |
| [189](pending/189-ctf-momentum-1d-self-referential-htf-not-cross-timeframe.md) | Mostly resolved 2026-07-27 same-day as filing: `ctf_momentum`'s 1d-vs-15m sign flip was a measurement artifact (`_CTF_HIGHER_TF` maps `1d -> 1d`, self-referential), doc corrected. Remaining: optional design decision + audit of sibling fallbacks, not urgent. |

---

**Not in this list:** anything in `deferred/` (phase-gated or corpus-rerun-batched) or
`completed/` (done). Check those folders directly for that work.
