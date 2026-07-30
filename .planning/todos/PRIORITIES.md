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

**Current probable path (updated 2026-07-30 -- phase-level, see `.planning/STATE.md` for full
detail, not duplicated here):** Phase 164/165/167 all COMPLETE; user has redirected priority
away from Phase 156-159 (execution) toward validating the features/regimes/IC/ensemble stack
first. The per-tf-active-scale-set branch merged 2026-07-30 (`ic_engine.py`'s hardcoded scales
-> per-tf `active_scales_for(tf)`), whose own final review found and same-day fixed todo 208
(the same-ET-session forward-return completeness gate was silently zeroing 1h's completeness
for a reason that doesn't hold up) -- `forward_returns` truncated and rebuilt clean under the
corrected definition, **corpus pipeline currently on step 5/8 (`ic_engine`), started 13:19 EDT,
historically ~27h; nothing that reads `feature_ic_scores`/`ensemble_weights` should start until
it completes** (STATE.md's Tier -1). Three follow-on `_SCALES`-hardcoding cleanups (209/210/211)
are scoped and ready in `docs/plans/2026-07-30-ic-scale-cleanup-plan.md`; a design doc on the
grid's actual per-tf horizon values (`docs/research/2026-07-30-forward-return-horizon-grid-refactor.md`)
recommends aligning them to each tf's real holding period rather than an arbitrary/uniform grid.
Canary RNG seeding fixed (todo 203) but a sibling POOLED-gate anomaly (todo 204) is still
undiagnosed. Full detail and live-verification commands: `.planning/STATE.md`'s "Current saga"
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

## P1 — High value, quick, fully unblocked

| Todo | Why now |
|---|---|
| [065](pending/065-emission-layer-calibration-proposals.md) | EM-CAL threshold calibration — both prerequisite gates (rebuild, EIC-04) cleared 2026-07-09. **Caution added 2026-07-30**: that clearance predates todo 146/208's grid rework (per-tf lookahead grid; 208's session-gate premise is now fixed, but the grid's actual values are still open, see 208's row above). Calibrating against pre-rebuild data now risks redoing this once the corpus/grid settle — same mistake this todo's own history already flagged once. Wait for the in-flight `ic_engine` pass to finish (`.planning/STATE.md`'s Tier -1) before starting. |
| [079](pending/079-anytime-valid-e-values-corpus-reruns.md) | Anytime-valid inference pilot (one tf) — new statistical primitive, deliberately staged small |
| [080](pending/080-ensemble-combination-e-candidates-queue.md) | Posterior-blended weighting (L5-1) — testable now via existing A/B judge, zero new data |
| [054](pending/054-shadow-alpha-events-monitoring.md) | Shadow alpha_events monitoring — prevents delayed detection of feature decay/threshold bugs |
| [124](pending/124-market-ohlcv-tradeable-view-tier2-audit.md) | **Fixed 2026-07-21** — `backfill_feature_factory.py`, `regime_writer.py`, `forward_return_writer.py` all migrated to `market_data_ohlcv_tradeable`; boundary + all directly-relevant unit tests pass, ruff/black clean. Recompute of `confirmed_corrupt` rows (todo 160, expanded 2026-07-22 to 16 symbols via a discovery-mechanism fix) **complete 2026-07-22** — see `completed/160-vwo-dia-kre-corrupt-prints-uncorrected.md`. Remaining 11 Tier-2 files still need individual style/DRY-vs-correctness judgment calls, no live reproduction found for any of them yet. |
| [169](pending/169-no-regime-coverage-completeness-check.md) | **Built and tested 2026-07-24, not yet deployed.** `services/regime_coverage_auditor.py` ships with unit tests (`tests/unit/services/test_regime_coverage_auditor.py`) and matching systemd unit files (`production/systemd/indicagent-regime-coverage-auditor.{service,timer}`, daily 06:00 UTC, same pattern as every other auditor). It already earned its keep once — immediately found 14 symbols, not the 7 known at filing time (closed as [168](../completed/168-seven-symbols-zero-per-symbol-hmm-regime-labels.md)). Remaining: actually enable the timer on the live host (`systemctl enable/start`) — a real persistent infra change, deliberately not done without explicit go-ahead. |
| [179](pending/179-gate166-concurrent-exposure-diagnostic.md) | **Stale entry corrected 2026-07-30 (todo-priorities audit).** Todo 183's corpus recompute (the thing this entry said was still pending) completed 2026-07-26/27 (`completed/183-...`), and 179's own sweep was re-run under corrected labels 2026-07-27 (`scripts/analysis/live_recalibrated_regime_sweep_check.py`, 270 cells, 108 adequately covered, **zero pass** — confirms the old-label finding, not a new negative result). The strategic fork this todo raised is resolved via T3 (Phase 167, independent of this regime question). This investigation reads as concluded, not actionable — **candidate for closing or converting to a decision record** rather than continuing to carry it as an open P1 pending item; the user's call, not made here. |
| [167](pending/167-equity-cross-sectional-vs-symbol-hmm-never-falsifier-tested.md) | **Plan changed 2026-07-29 — no longer a standalone equity-scoped relaunch,** folded into 176's queued sequence (market-data-gap catchup → 176's `--refresh` → one full-corpus `ic_engine` pass). **176's `--refresh` step confirmed run 2026-07-30** (see 176's updated entry above), but the sequence's final step (a full-corpus equity+rates `ic_engine` pass) has not yet run — that pass is what would actually close this todo. Currently blocked behind todo 202's in-flight regime_writer→forward_return_writer→cross_sectional_regime_model→ic_engine relaunch (single-writer discipline: do not run a second `ic_engine` pass concurrently). |
| [210](pending/210-ensemble-ic-worker-scales.md) | **Bumped P2→P1 same day it was filed; premise updated 2026-07-30 after todo 208's session-gate fix, verdict unchanged.** `_run_ensemble_ic_worker`'s per-scale loop has no `complete_{scale}` term at all (unlike `ic_engine.py`, which correctly gates on it), so once `ensemble_alpha` is repopulated it will compute and persist `alpha_ensemble_ic` rows from forward returns whose completeness flag says the horizon doesn't actually exist yet. (The originally-cited illustration — 1h's session-crossing `slow`/`extended` — is now stale since that gate is gone; the underlying gap, silently including incomplete rows, is identical either way.) Fix scoped in `docs/plans/2026-07-30-ic-scale-cleanup-plan.md` Task 1, reusing `ops_ensemble_ablation.py`'s already-correct `apply_complete_gate` pattern. Currently latent only because `ensemble_alpha` is empty; fix before it's next repopulated. |

**Note (2026-07-26):** [179](pending/179-gate166-concurrent-exposure-diagnostic.md)'s "strategic choice" fork is
now resolved in one direction — T3 (cross-sectional long-short) passed decisively today (see
`docs/research/data-edge-source-thesis.md`, T3 section), making `docs/research/trade-construction-layer.md`
the concrete near-term next step ahead of Phase 164/165. Not yet filed as a todo (it's phase-scoped,
not a `pending/` item) — the recommended move is cost-hurdle-adjusting the spread construction, then
scoping it as a phase via `/gsd-discuss-phase`.

## P2 — Real value, not urgent

| Todo | What |
|---|---|
| [208](pending/208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md) | **Downgraded from P0 2026-07-30** — Steps 1/2 DONE (`forward_return_writer.py`'s same-ET-session gate removed for 5m/15m/1h, `forward_returns` rebuilt clean under the corrected definition). What's left is Step 3, the grid's actual per-tf horizon VALUES — see `docs/research/2026-07-30-forward-return-horizon-grid-refactor.md`, which recommends deriving them from each tf's real holding period via `_select_hold_bars_from_decay` rather than re-deriving 146's grid as-is. Next step: the characterization run (`ops_lookahead_horizon_response.py`, safe now, needs one small 5m gap closed first) once the in-flight `ic_engine` run completes. |
| [213](pending/213-rolling-vp-suppressed-for-1d-never-independently-reviewed.md) | New 2026-07-30, found while closing 176: `poc_rolling_dist_atr`/`poc_session_rolling_divergence_atr` (D-18's rolling-track VP additions, tf-agnostic by construction) are suppressed for `tf='1d'` via the same code branch as session VP (which correctly doesn't apply to 1d) -- but the rolling case was never independently reviewed for tf-applicability across any of Phase 163's three design-review passes. Likely dropping real signal (a 1d bar's dislocation from a ~2-year value anchor is a coherent auction-market-theory concept per D-18's own argument), not a considered exclusion. Needs an incremental-IC check before promoting, same discipline as any other structural column. Renumbered from 209 -- collided with a same-day, independently-filed todo from the per-tf-active-scale-set final review. |
| [186](pending/186-ic-math-cross-sectional-block-bootstrap-gap.md) | New 2026-07-26, same review as 185: `ic_math.py` has a per-symbol circular block bootstrap but no cross-sectional (pooled-panel) variant, so T5's within-bar_ts rigor check approximated it ad hoc. Lower urgency than 185 — the approximation is conservative and the script says so; do this once a real (non-exploratory) T3/T5 candidate needs it. |
| [214](pending/214-ic-engine-ensemble-ic-engine-shared-compute-refactor.md) | New 2026-07-30, user question mid-session: `ic_engine.py` (5,239 lines) and `ensemble_ic_engine.py` (1,523 lines) independently duplicate the same per-scale compute pattern instead of sharing one implementation — exactly the duplication that let todo 210's bug (one engine masks on `complete_{scale}`, the other silently didn't) exist undetected. Real refactor, deliberately deferred until the current IC measurement chain (208/210/209/211's fixes, a fresh corpus rebuild) is stable again — don't refactor while the semantics are still moving. |
| [209](pending/209-ops-vol-normalized-target-ab-scales.md) | New 2026-07-30, per-tf active-scale-set Task 3 review finding: `ops_vol_normalized_target_ab.py` (Component F) reads its own independent flat `_SCALES` tuple, same defect class `ic_engine.py`'s 12 call sites were just fixed for — will still fetch/compare all 4 scales for `1h` even though `ic_engine.py` no longer writes rows for `slow`/`extended` there. Small, mechanical, same pattern as the already-fixed sites. |
| [211](pending/211-ops-scripts-stale-scales.md) | New 2026-07-30, per-tf active-scale-set final-review sweep: two more standalone scripts have the same hardcoded-4-scale defect as 209/210 — `ops_ensemble_ablation.py` (mechanical, same fix) and `ops_interaction_primitives_pilot.py` (mechanical fix PLUS an independent pre-existing bug: it still builds the pre-todo-146 global `alpha.ic.lookahead.{scale}` key, which no longer exists in `config_state` since todo 146's per-tf key rename). Batch with 209/210 when next touched. |
| [188](pending/188-t5-replication-15m-deferred-memory-contention.md) | T5's 1d replication (2026-07-27) partially confirmed the non-linear-combiner finding but at ~16x smaller magnitude than the original 1h result -- confirmed SMALL not LARGE. 15m (the tf Phase 167's live construction actually trades) is the directly actionable replication, deferred on memory contention with todo 183's concurrent recompute. **Todo 183 has since completed and the host has ~20GB free (re-verify before running) -- the deferral reason is gone, ready to run now.** The `ctf_momentum` 1d-vs-15m sign flip this originally surfaced is resolved -- see [189](pending/189-ctf-momentum-1d-self-referential-htf-not-cross-timeframe.md). |
| [177](pending/177-bar-history-maxlen-caps-windows-beyond-200.md) | `FeatureVectorPipeline`'s `BarHistory(maxlen=200)` silently caps every live-path window below 200 bars regardless of its APR-configured size. Phase 163's CR-02 found and fixed this for one field (`feature.session_vp.rolling_window`, migration 256 + regression test); this todo tracks the broader gap — several pre-existing windows (`momentum_zscore_window`/`hurst_window`/`vix_zscore_window`, all default 252) already silently exceed 200 too. |
| [101](pending/101-migration-duplicate-number-sweep.md) | `production/migrations/` has 13 duplicate-number groups (001, 031, 038, 050-052, 064, 138, 152, 168, 178, 214-215). Finding + recommended approach only; deliberately not executed given live-DB rename risk. |
| [108](pending/108-hmm-multi-seed-restart-best-likelihood.md) | `regime_writer.py`'s HMM fit uses a single seed with a same-seed convergence retry, not multi-seed-restart-and-keep-best-log-likelihood. Robustness gap, not a proven bug. |
| [005](pending/005-ic-regime-transition-purge.md) | Purge regime-transition label noise from IC measurement — re-scoped 2026-07-19, held for 143.1 sequencing (see file) |
| [038](pending/038-cross-sectional-collinearity-diagnostic.md) | Cross-sectional feature collinearity diagnostic vs IC |
| [039](pending/039-tag-stratified-ic-population-check.md) | Population-count check before tag-stratified cross-sectional IC |
| [081](pending/081-emission-meta-labeling-and-conviction-cross-ref.md) | Emission meta-labeling gate — check overlap with 065/EM-HYST before building |
| [089](pending/089-ensemble-ic-engine-recurring-cadence.md) | No recurring `ensemble_ic_engine` schedule exists — IC-decay trigger input can go stale |
| [009](pending/009-service-utils-ic-engine-cleanup.md) | Phase B infra cleanup batch — APR compliance sweep, `BaseBatch` promotion, naming vocab, shared-utility DRY fixes. Part E (`ic_engine.py` pure-function extraction) closed 2026-07-23 via Phase 162-01; Parts A-D remain open |
| [191](pending/191-feature-scoring-beyond-ic.md) | Feature scoring beyond IC (near-term derived metrics) |
| [050](pending/050-ibkr-apr-migration.md) | Migrate `ibkr.py` hardcoded constants to APR |
| [052](pending/052-adversarial-data-error-hunt.md) | Adversarial data-error hunt batch job |
| [042](pending/042-15m-chunk-size-retest.md) | Re-test 15m backfill chunk size (likely too conservative) — gate reconfirmed clear 2026-07-19, live probe not yet run (see file) |
| [024](pending/024-feature-decay-observatory.md) | Feature decay/crowding observatory dashboard |
| [125](pending/125-tag-calibrator-discovery-oos-gate-not-enforced.md) | TagCalibrator's `discovery_oos_days` OOS-confirmation gate computed but never enforced — new discoveries go live immediately. Zero current blast radius (no live consumer reads the affected tags yet, see 126). |
| [126](pending/126-instrument-tags-valid-to-no-consumer-contract.md) | No `instrument_tags` reader filters on `valid_to` — expiry has no observable effect yet, no contract established for future consumers. Resolve before/alongside 125. |
| [135](pending/135-cross-sectional-regime-grid-shape-never-validated.md) | Cross-sectional regime grid shape (9 equity cells, 6 rates cells) has never been validated as a model-selection question — unlike HMM's K=5, which went through a real BIC study. Distinct from todo 092 (cut-point values within the existing shape). |
| [078](pending/078-frame-outcome-labels-second-outcome-definition.md) | Register frame-outcome (barrier-hit sign) as a second outcome definition alongside forward-return IC, now that `alpha_frames` has real data. Gate cleared 2026-07-12 (todo 093 backfill ran); moved back to pending/ 2026-07-18. Diagnostic value, not a reason to touch 142B's frozen design. |
| [082](pending/082-simulation-validation-lenses-post-142b.md) | Additional read-only simulation/validation lenses over `alpha_frames` (standing permutation nulls, etc.) — same gate-cleared status as 078. No new judgment surface, mechanical. |
| [118](pending/118-migrate-feature-domain-into-concept-registry.md) | Migrate `feature_registry` (`domain='feature'`) into the Concept Registry MVP (shipped 2026-07-13 with only `domain='ensemble_strategy'` seeded). Sequencing blocker resolved (Phase 143 already shipped against `feature_registry` directly, so this is now a plain fold-in, not a race). Touches the live feature lifecycle path — do after 117 proves the actuator pattern. |
| [175](pending/175-structural-candidate-part2-smc-swing-fib-anchored-vwap.md) | Filed 2026-07-23 closing Phase 166: Part 2 of the structural stop/target candidate (SMC/swing/fib/anchored-VWAP, i.e. Phase 164/165's primitives) once those phases land — VP/SR (Part 1, Phase 163) is the only part Phase 166 actually scored. Gated on Phase 164 (not planned) and Phase 165 (researched, not planned). **Same 179 deprioritization as todo 176 applies** — don't resume this without reading 179 first. |
| [155](pending/155-price-sanity-status-historical-backfill.md) | New 2026-07-20, filed closing [149](../completed/149-bar-ingestion-price-sanity-guard.md): live pilot measured ~4.1 years to clear the 215M-row historical backlog at `BarAuditor`'s default batch size/cadence. Raising the batch size risks the daemon's 60s systemd watchdog and conflates one-time historical debt with the ongoing live-stream audit. Needs a dedicated one-time backfill tool, decoupled from `BarAuditor`'s cycle, reusing 149's classification primitives and Task 1's TimescaleDB compressed-chunk lessons. Also: oldest-first ordering means the guard protects nothing live until this lands. **Batch its effects into the same next full corpus rebuild as [146](pending/146-lookahead-grid-per-tf-recalibration.md)'s grid fix, not a standalone rebuild.** |
| [156](pending/156-otel-span-coverage-gap-v3-pipeline.md) | **Step 1 done 2026-07-29** — `ensemble_trainer.py` and `alpha_publisher.py` (the two v3.0 critical-path gaps) now both wrap `execute()` in `observed_span(...)`, tests green. Remaining: step 2 (should `BaseDaemon`/`BaseWriter`/`BaseBatch` auto-wrap spans the way the 5 mandatory metrics signals are automatic?) and step 3 (broader remaining-services audit) — real design/scoping questions, not mechanical follow-through. |
| [157](pending/157-no-mechanical-base-class-compliance-check.md) | New 2026-07-20, same investigation as 156: nothing mechanically checks that new services extend `BaseDaemon`/`BaseWriter`/`BaseBatch`, that spans get used, or that `prometheus_client` stays banned — all convention/review-only, unlike the naming/table-boundary checks this project's pre-commit hook and CI already enforce. Candidate fix reuses the existing allow-list/regex boundary-test pattern. |
| [200](pending/200-service-registry-no-check-against-archived-units.md) | New 2026-07-27, found closing the `feature_vector_writer` deploy gap: `service_auditor.py`'s `_AGENT_ID_TO_UNIT`/`_DAG_ORDER` had silently pointed a live v3.0 agent at an archived v2.x unit for weeks (masking an 18-day undeployed-writer outage) — second occurrence of this exact collision (Phase 138-P0 partially fixed it once already, missing the value half of the rename). Adjacent to 157 but distinct: needs a registry-vs-archived-unit integrity test, not base-class compliance. Renumbered from 193 2026-07-29 (collided with completed/193-ic-engine-checkpoint-blind-to-apr-config-drift.md). |
| [166](pending/166-1d-ensemble-eligibility-small-sample-treatment.md) | New 2026-07-21, split out of todo 164: `1d`'s median effective-N (1,222, min 143) is ~32x fewer than `15m`'s, CI width 3x wider — a genuine small-sample power problem (Type II error risk), not a miscalibrated threshold like `1h`'s. Needs a real small-sample statistical treatment (Bayesian shrinkage IC or a calibrated day-clustered bootstrap), scoped as its own plan. |
| [111](pending/111-stratification-classification.md) | **Unblocked 2026-07-22** — Phase 144's D-05 verdict landed (registered as ROADMAP Phase 145). Bumped P3→P2: real, actionable design work now (the `StratificationDimension` Protocol + `concept_registry` row-grain decision), not a blocked placeholder. Read Phase 144's verdict before starting — a group deficient on both axes (rates/15m/5m) is a live case the design needs to handle. |
| [171](pending/171-rates-dual-write-symbol-hmm-reversion-check.md) | New 2026-07-22, a "don't forget" item recorded when closing Phase 144: `rates.dual_write_symbol_hmm=true` was deliberately temporary shadow-mode measurement; F1's non-trigger answered the question but only on a scoped 12-symbol run. Batch into the next full corpus rebuild (same cluster as [146](pending/146-lookahead-grid-per-tf-recalibration.md)/[155](pending/155-price-sanity-status-historical-backfill.md)) — confirm F1 holds at full scale before reverting the flag, don't revert on a partial sample, don't forget to ever revisit it either. |
| [172](pending/172-path-dependent-frame-statistics-order-sensitivity-sweep.md) | New 2026-07-22, found during Phase 148-05's Gate 2 execution: `_max_drawdown` over `alpha_frames` silently produced a non-reproducible number because same-`bar_ts` frames (genuinely simultaneous cross-sectional positions) were treated as sequential in a cumulative-sum walk — fixed for Gate 2 (aggregate per `bar_ts` before the walk), but a related order-sensitivity symptom also surfaced in `frame_gate_passes`'/`evaluate_frame_gate`'s cluster-mean array construction (dict insertion order feeds a fixed-seed bootstrap), unfixed. Two threads: (1) sweep for other path-dependent statistics over frame-level data elsewhere in the codebase, (2) make `frame_gate_passes`'s cluster-mean array order-deterministic. Did not affect Phase 148's actual gate verdicts. |
| [173](pending/173-ensemble-alpha-1h-1d-oos-scoring-gap.md) | New 2026-07-22, found after Gate 1's real (irreversible) run: `ensemble_alpha` has zero OOS-side rows at `1h` for any weight_version and zero at `1d` for the champion/default weight_version — Gate 1's recorded PASS verdict covers only 5m/15m (640 cells), disclosed in the promotion decision record rather than presented as a full 4-timeframe pass. Cannot re-run Gate 1 to fix (D-04); investigation-first, may overlap todo 089/166's root cause. |

## P3 — Hygiene, docs, process (opportunistic)

| Todo | What |
|---|---|
| [056](pending/056-phase146-147-v2x-retirement-stale.md) | ROADMAP Phase 147/148 text rewritten 2026-07-19 (operator call resolved: archive not delete, decouple from proof gates). Remaining scope: the actual decommission-in-fact execution (git mv v2.x code to archive/, disable dead systemd units, rename-not-drop the frozen v2.x tables) — real multi-file operation, do with a clean git state. |
| [022](pending/022-bi-superset.md) | Self-service BI (Superset) for ad-hoc analytics |
| [115](pending/115-days-to-month-end-exact-redundancy.md) | `days_to_month_end` is an exact affine complement of `month_position` (Pearson correlation -1) — perfectly collinear, remove one. |
| [189](pending/189-ctf-momentum-1d-self-referential-htf-not-cross-timeframe.md) | Mostly resolved 2026-07-27 same-day as filing: `ctf_momentum`'s 1d-vs-15m sign flip was a measurement artifact (`_CTF_HIGHER_TF` maps `1d -> 1d`, self-referential), doc corrected. Remaining: optional design decision + audit of sibling fallbacks, not urgent. |
| [199](pending/199-feature-vectors-missing-1m-timeframe-scope.md) | New 2026-07-29, found mid-execution of todo 176's Step 1 recompute: `_TARGET_TIMEFRAMES = ["5m", "15m", "1h", "1d"]` in `backfill_feature_factory.py:92` is a hardcoded list — confirmed with user that not computing 1m features is intentional, so this is purely an APR "behavioral list" governance cleanup, not a scope gap. |
| [201](pending/201-docs-baseagent-naming-drift-agents-platform-cluster.md) | New 2026-07-29, found during a repo cleanup pass: `docs/agents/*` + `docs/platform/platform-foundation.md` + `docs/architecture/architecture-evolution.md` describe a `BaseAgent` class that no longer exists (`grep -rn "class BaseAgent"` returns nothing) — live base class is `BaseDaemon`. Needs a real contract-verification pass, not a mechanical rename, since the described behavior may have drifted beyond the name. |

---

**Not in this list:** anything in `deferred/` (phase-gated or corpus-rerun-batched) or
`completed/` (done). Check those folders directly for that work.
