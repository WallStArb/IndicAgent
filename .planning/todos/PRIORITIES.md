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

**Current probable path (updated 2026-07-27 -- phase-level, see `.planning/STATE.md` for full
detail, not duplicated here):** **Phase 167 (Cross-Sectional Trade Construction, T3) is
COMPLETE** -- both live Validation Gates PASSED against the real OOS population
(`gate1_passes=true`, `gate2_passes_overall=true`), unlike Phase 148's per-symbol directional
construction, which failed Gate 2. This clears the stated precondition for Phase 156-159
(execution/sizing); user has redirected priority away from 156-159 toward validating the
features/regimes/IC/ensemble stack first (2026-07-27). T5 (non-linear combiner) partially
replicated at 1d same day -- confirmed SMALL not LARGE (~16x magnitude collapse from the
original 1h finding); 15m replication (the directly actionable tf) deferred, see todo 188.
Todo 183's corpus recompute completed 2026-07-27 (closed); T2's regime-sweep verdict is now
confirmed dead on live data, no longer provisional (unrelated to T3/Phase 167's own validity).
**Explicit user override, same day:** build Phase 164 + Phase 165 regardless of the evidence-gate
reasoning above -- plan 165, execute both, then one combined `--refresh` recompute. See
STATE.md's Tier 0 for full sequencing detail.

---

## P0 — Fix soon (integrity/correctness gaps already surfaced)

**Live P0 as of 2026-07-29:** [202](pending/202-per-tf-lookahead-grid-downstream-consumers-stale.md)
— todo 146's per-tf lookahead grid landed (migration 269 + `ICEngineConfig`/
`EnsembleICConfig`/`forward_return_writer.py`), but `forward_returns` (36.7M rows, all
under the OLD grid) has no automatic rebuild path and its fingerprint is already
invalidated — the next `ic_engine` run will write horizon-mismatched `feature_ic_scores`
unless `infrastructure_truncate_derived_tables.sh` runs first, in order, as part of
whichever corpus rebuild is next (todo 176's queued sequence). Also 4 downstream
measurement/validation scripts (`corpus_manifest_verifier.py`, `ops_ic_shrinkage.py`,
`ops_oos_holdout_eval.py`, + 3 smaller ones) still read the old global grid and will
silently produce wrong verdicts post-rebuild.

The rest of this section (below) is stale/resolved, kept for record only.

| Todo | Gap |
|---|---|
| [099](pending/099-bootstrap-ci-staged-validation-gate-not-cleared-5m-residual.md) | P2 — the bootstrap CI staged-validation gate's 6 SUSPECT cells trace to 5 diagnostic-only (`is_pooled=false`) breaches + 1 capital-relevant cell that independently clears its own bound — no longer blocks Plan 07. Underlying statistical question (why 5m autocorrelation/momentum features resist both Fisher-z and block-bootstrap) remains open as non-blocking follow-up. |
| [096](pending/096-frame-hold-horizon-vs-feature-lookahead-mismatch.md) | **Unblocked 2026-07-21** — estimator fix confirmed 2026-07-19; live-verified directly against the DB (2026-07-21) that the real production pipeline (not just `ic_engine`'s feature-level values) has since re-run under corrected APR: champion `weight_version=run_2025122405150000` shows `ensemble_weights` rows computed 2026-07-19, and `alpha_ensemble_ic` now holds 2,186 real rows (previously claimed zero/stale). 096's own diagnostic scope is done AND its prerequisite for unblocking 088 is now satisfied. |

**Locked sequencing decision (project owner confirmed, do not reorder without re-confirming) —
RESOLVED 2026-07-21, kept for record:**
093 (`alpha_frames` backfill, done) → **091 (done 2026-07-19, moved to `completed/`)** →
**097 (done 2026-07-19, moved to `completed/`)** →
**094 (done 2026-07-21, moved to `completed/` — HOLD verdict, `alpha.ensemble.sign_symmetric`
stays `false`, confirmed twice: 143.1-08's shadow validation and todo 165's regime-stratified
re-evaluation both rejected the sign-symmetric universe decisively across every metric. The
E1-vs-E2 A/B re-run this chain originally called for is moot for promotion — there is no live
weighting-method question left on a universe that's already rejected wholesale)** →
**096** (done, unblocked 2026-07-21) → **088 (done 2026-07-29, moved to `completed/` —
`_select_hold_bars_from_decay` now returns `(hold_bars, censored)` instead of a bare int, and
the censored fraction is recorded in `config_history.reason` at calibration time)**. Rationale:
091, 097, and 094 all read or directly affect `ic_ci_lower`/`ic_ci_upper`, and 094 independently
required a full `ic_engine` re-run — sequencing 091 and 097 first meant one corpus re-run served
all three fixes instead of splitting across multiple. **Status 2026-07-29: the entire chain is
now fully closed** — 143.1-07's corpus re-run (2026-07-19) served 091/097/094 as planned; 091
and 097 are fully closed; 094 concluded with a definitive HOLD (see
`completed/094-alpha-events-long-short-imbalance.md`); 096 and 088 are both done. No open items
remain in this chain.

## P1 — High value, quick, fully unblocked

| Todo | Why now |
|---|---|
| [065](pending/065-emission-layer-calibration-proposals.md) | EM-CAL threshold calibration — both prerequisite gates (rebuild, EIC-04) cleared 2026-07-09 |
| [079](pending/079-anytime-valid-e-values-corpus-reruns.md) | Anytime-valid inference pilot (one tf) — new statistical primitive, deliberately staged small |
| [080](pending/080-ensemble-combination-e-candidates-queue.md) | Posterior-blended weighting (L5-1) — testable now via existing A/B judge, zero new data |
| [146](pending/146-lookahead-grid-per-tf-recalibration.md) | `alpha.ic.lookahead.*`'s uniform 1/5/20/60-bar grid confirmed broken on intraday tfs, now confirmed on 1d too — full-corpus re-run (2026-07-20) + a stride-correction fix to the diagnostic itself (Fable 5 caught the CI was computed on serially-dependent, unstrided observations) found 1d's `extended=60` cell also fails (CI half-width > IC point estimate for every horizon ≥20). Final confirmed Step 2 grid for all 4 tfs is in the todo (1d compresses to 1/2/5/10; 5m/15m/1h candidates unchanged, now confirmed at full scale). **Step 3 (apply to production APR) deliberately rides the NEXT full corpus rebuild — batch together with [155](pending/155-price-sanity-status-historical-backfill.md)'s backfill effects rather than triggering a rebuild for either alone.** |
| [092](pending/092-equity-regime-model-threshold-calibration.md) | **FIXED 2026-07-24 for both enabled regime groups (code + migrations 257/258), live recompute not yet run for either.** Equity's `breadth_frac` (guessed 0.40/0.60 raw-fraction cut) and rates' `curve_z`/`credit_z` (guessed +-0.5/0.0 z-score cuts, actually WORSE imbalance — 30.8x vs equity's 12-17x) both fixed with the same causal-expanding-rank pattern (shared `causal_rank.py` helper), symmetric 0.33/0.67 (and 0.5 median-split for credit) cuts, self-calibrating by construction. TDD, full suite green. Offline re-derivation confirms equity's imbalance roughly halved; re-running the day's regime sweep under the fix surfaced `high_bear` conflating "buyable dip" vs "structural bear" (every real 2008/2018/2020/2022 crash fails, cleanest passes are non-crisis dips) — a well-motivated next research direction, not a confirmed edge. **Remaining: the actual live `market_regimes` recompute (multi-hour, both regime_groups, invalidates `feature_ic_scores`/`ensemble_weights`/`ensemble_alpha` downstream) — deliberately not run yet, next session's decision.** `commodity_momentum_ts`/`fx_dollar_carry` have the identical anti-pattern but are `enabled: false` with zero live data — not fixed blind. |
| [054](pending/054-shadow-alpha-events-monitoring.md) | Shadow alpha_events monitoring — prevents delayed detection of feature decay/threshold bugs |
| [124](pending/124-market-ohlcv-tradeable-view-tier2-audit.md) | **Fixed 2026-07-21** — `backfill_feature_factory.py`, `regime_writer.py`, `forward_return_writer.py` all migrated to `market_data_ohlcv_tradeable`; boundary + all directly-relevant unit tests pass, ruff/black clean. Recompute of `confirmed_corrupt` rows (todo 160, expanded 2026-07-22 to 16 symbols via a discovery-mechanism fix) **complete 2026-07-22** — see `completed/160-vwo-dia-kre-corrupt-prints-uncorrected.md`. Remaining 11 Tier-2 files still need individual style/DRY-vs-correctness judgment calls, no live reproduction found for any of them yet. |
| [169](pending/169-no-regime-coverage-completeness-check.md) | **Built and tested 2026-07-24, not yet deployed.** `services/regime_coverage_auditor.py` ships with unit tests (`tests/unit/services/test_regime_coverage_auditor.py`) and matching systemd unit files (`production/systemd/indicagent-regime-coverage-auditor.{service,timer}`, daily 06:00 UTC, same pattern as every other auditor). It already earned its keep once — immediately found 14 symbols, not the 7 known at filing time (closed as [168](../completed/168-seven-symbols-zero-per-symbol-hmm-regime-labels.md)). Remaining: actually enable the timer on the live host (`systemctl enable/start`) — a real persistent infra change, deliberately not done without explicit go-ahead. |
| [176](pending/176-feature-vectors-historical-backfill-new-structural-columns.md) | **Scope widened 2026-07-28**: originally Phase 163's 17 VP/SR columns only; now covers all 94 new structural columns across Phases 163-165 (17 VP/SR + 36 SMC + 41 swing/fib/trend/session), all NULL on every pre-existing historical row for the same root cause (`FEATURE_VECTOR_INSERT_SQL`'s `ON CONFLICT DO NOTHING`). The 2026-07-24 deprioritization (waiting on 179's regime-eligibility investigation) is superseded by the same-day explicit user override recorded above ("build Phase 164 + Phase 165 regardless... then one combined `--refresh` recompute") — Phase 164/165 have since landed (2026-07-28). Fix mechanism (`--refresh` UPSERT path) already built and column-list-generic; **the actual combined recompute has not been run yet** — pending user go-ahead (multi-hour, full 58-symbol/multi-tf/multi-year corpus; a prior recompute of this scale hit a real ceiling breach, todo 183). |
| [179](pending/179-gate166-concurrent-exposure-diagnostic.md) | **Provisional as of 2026-07-24, re-verification in progress 2026-07-26.** Exhaustive 9-regime × symbol_hmm × 12-historical-episode sweep found every lead either fails its own bootstrap CI or fails to replicate — but ran entirely under OLD (pre-todo-092) regime labels. The strategic fork this todo raised (invest in Phase 164/165 features vs. accept no edge) is now resolved in a third direction: T3 (cross-sectional construction) passed decisively 2026-07-26, independent of this regime question — see Phase 167 (registered). Todo 183's corpus recompute (in progress) is what would let this todo's own sweep be re-run under corrected labels; not yet done. |
| [167](pending/167-equity-cross-sectional-vs-symbol-hmm-never-falsifier-tested.md) | **Plan changed 2026-07-29 — no longer a standalone equity-scoped relaunch.** The prior scoped `ic_engine.py --symbols <49 equity symbols>` pass (started 2026-07-28) was restarted twice for real fingerprint-gate bugs (both fixed, [182](../completed/182-ic-engine-15m-cross-sectional-bootstrap-threads-stale.md)/[198](../completed/198-ic-engine-fingerprint-gate-false-invalidation.md)) and left stopped. Rather than relaunch it narrowly, it's now folded into [176](pending/176-feature-vectors-historical-backfill-new-structural-columns.md)'s queued sequence: market-data-gap catchup → 176's `--refresh` → one full-corpus (equity+rates) `ic_engine` pass, closing this todo as a side effect. Queued, pending a server reboot for safety patches — not yet started. |

**Note (2026-07-26):** [179](pending/179-gate166-concurrent-exposure-diagnostic.md)'s "strategic choice" fork is
now resolved in one direction — T3 (cross-sectional long-short) passed decisively today (see
`docs/research/data-edge-source-thesis.md`, T3 section), making `docs/research/trade-construction-layer.md`
the concrete near-term next step ahead of Phase 164/165. Not yet filed as a todo (it's phase-scoped,
not a `pending/` item) — the recommended move is cost-hurdle-adjusting the spread construction, then
scoping it as a phase via `/gsd-discuss-phase`.

## P2 — Real value, not urgent

| Todo | What |
|---|---|
| [197](pending/197-hmm-forward-filter-window-reset-every-refresh.md) | New 2026-07-27, found profiling feature-compute throughput: `FeatureCache`'s inline forward-filter HMM (K=3, fixed params -- not `regime_writer.py`'s separate fitted K=5 HMM) resets to uniform prior and replays its full window from scratch every 30 bars, ~30% of total compute cost. Real perf opportunity, but changing it changes `hmm_regime_prob`/`hmm_entropy`/`hmm_duration`'s actual values -- needs the same rigor as a regime-label fix (recompute + validation), not a drive-by. |
| [186](pending/186-ic-math-cross-sectional-block-bootstrap-gap.md) | New 2026-07-26, same review as 185: `ic_math.py` has a per-symbol circular block bootstrap but no cross-sectional (pooled-panel) variant, so T5's within-bar_ts rigor check approximated it ad hoc. Lower urgency than 185 — the approximation is conservative and the script says so; do this once a real (non-exploratory) T3/T5 candidate needs it. |
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
