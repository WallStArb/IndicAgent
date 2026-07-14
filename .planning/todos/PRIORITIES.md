# Todo Priorities

**Scope of this index:** `pending/` only — small, single-session, run-it-now items that remind
us what gaps were surfaced. Phases (ROADMAP.md, `/gsd-discuss-phase` workflow) are a separate
execution track and do not appear here; anything that was previously filed as a todo but turned
out to actually be phase-scoped (a new feature family, a batched corpus-rerun item, or hard-gated
on a phase/dataset that doesn't exist yet) has been moved to `deferred/` with a status line
explaining what unblocks it — see that folder, not this list, for those.

**Reorg date:** 2026-07-10. 13 items moved `pending/` → `deferred/` this pass (026, 036, 041,
066, 070, 073-078, 082, 083 — all either hard-gated on a phase that hasn't shipped, or meant to
batch into the v3.15/Phase 144 corpus-rerun window rather than run standalone). Also fixed a
duplicate-089 numbering collision within `pending/` (renamed `089-fisher-z-ci-empirical-null-
miscalibration.md` → `091-...md`; cross-references updated). One deferred item, 026, had a
single sub-scope (P3, empirical threshold calibration) split back out as standalone todo 092 —
fresh evidence flags it as a live-path IC suspect now, unlike the rest of 026's batched scope.

**This file is now the single source of truth for todo-level prioritization** — the
intelligence-lifecycle priority matrix (`docs/research/intelligence-lifecycle-backlog-matrix.md`)
previously kept its own separate "Todos" ranking table for the same
`pending/` items; that table is now collapsed to a pointer here to eliminate the two-places-
that-can-silently-disagree risk. Its former top entry, `alpha_frames` backfill, was a matrix-
only bullet with no corresponding todo file — filed as todo 093 in this same pass so it isn't
invisible to this list.

## Musk 5-Step + Renaissance framing pass (2026-07-13)

CLAUDE.md names both as this project's design north star; this file hadn't actually been run
through either lens before now. Applying Musk's mandate **in order** — make requirements less
dumb → delete → simplify → accelerate → automate — plus Renaissance's "empirical over
theoretical" and "earn promotion through proof" against everything in `pending/`/`deferred/`.
Concrete outcomes below; re-run this lens on new todos before filing, not just retroactively.

**Step 1 — Make requirements less dumb (question the stated premise before scoring it):**
- Todo [020](deferred/020-context-features-cluster.md) claimed to be gated on "007 (tf-agnostic
  table design) and IC engine live" — both have been true for a while. `context_features` exists
  live today with 8,985 rows; the gate note was stale, not the requirement itself. Corrected in
  place rather than left to silently block a re-read forever.
- General rule this surfaced: a "Gate:" line written once at filing time rots. Anything sitting
  in `deferred/` for more than ~2 weeks should have its gate re-checked against live state before
  being cited as still-blocked, not trusted at face value.

**Step 2 — Delete (not defer — actually remove, per Musk's "if you're not adding ~10% back,
you're not deleting enough"):**
- Todo [021](completed/021-analog-engine.md) (AnalogEngine) — closed. Duplicate tracking: its
  own header already called its architecture superseded, and ROADMAP.md's Phase 149/150 now
  carries a fuller, current, actively-maintained design for the same build. Two trackers for one
  build is the exact failure mode this project already caught once for Concept Registry
  (todo 058 vs. 112) — same fix applied here.
- Todo [032](pending/032-ic-engine-pure-function-refactor.md) — already merged into 009
  (2026-07-12, pre-dates this pass), correctly resolved, not re-litigated.
- **Candidate for actual deletion, not just low-priority parking:** [059](pending/059-review-aegisagent-tradeagent-for-trade-construction-reuse.md)
  + [060](pending/060-review-cluster2-legacy-intelligence-backlog.md) are both "read old docs,
  decide salvage-vs-archive" tasks — cheap (2-4h combined), already cross-referenced as the same
  shape of work in 059's own text. Renaissance's "never drop data that could contain signal"
  applies to measured data, not stale vision docs — there's no principled reason to keep carrying
  two open todos whose entire job is deciding what to delete. Run both in one sitting; whatever
  doesn't get salvaged gets archived same-session, not re-deferred.

**Step 3 — Simplify (reduce scope of what survives, don't build infrastructure for unproven
ideas):**
- Todo [080](pending/080-ensemble-combination-e-candidates-queue.md) lists 4 untested weighting
  mechanisms (posterior blending, HRP-lite, Bayesian averaging, trailing-IC) as one queue.
  Renaissance's "earn promotion through proof": test the single most-promising candidate
  (posterior blending, per its own existing note) through the existing A/B judge before building
  scaffolding for the other three — don't design a general "E-candidate framework" for ideas that
  haven't earned it yet.
- Todo [052](pending/052-adversarial-data-error-hunt.md) — keep, but scope to the specific data
  classes already suspected of error, not an open-ended hunt; "instrument everything" doesn't
  mean "audit everything indefinitely."

**Step 4 — Accelerate (only the true critical path, decided last per Musk's ordering — don't
speed up work that steps 1-3 haven't already justified):**
- **Phase 143.1** (corpus re-run, in progress) is the actual bottleneck — todos 091/094/096/097
  all inherit from it and nothing scored above should compete with it for attention.
- Once it clears: todo 065 (EM-CAL, both prerequisite gates already cleared), todo 092 (regime
  threshold calibration, flagged as a live-path IC suspect), and todo 054 (shadow alpha_events
  monitoring — direct application of the Renaissance "shadow mode first" principle by name) are
  the fastest real wins, not busywork.

**Step 5 — Automate (last, and only for what's proven, per Musk — premature automation on an
unproven process just hides the manual step instead of removing it):**
- The gate-staleness problem Step 1 found is itself automatable: a future todo (not filed yet —
  low urgency, this pass already did the one-time correction manually) could cross-check every
  `deferred/` item's stated "Gate:" against live DB/code state on a schedule, rather than relying
  on someone manually re-reading it during a priority pass like this one.
- Do not automate ranking itself (this file's P0-P3 tiers) — that is a judgment call this project
  has explicitly reserved for the project owner (see the P0 section's "do not reorder without
  re-confirming" sequencing decision below); automating it would remove the human judgment step
  Renaissance's own "earn promotion through proof" gate depends on.

---

**Tiers:** P0 = fix soon, real gap/bug surfaced. P1 = high value, quick, fully unblocked. P2 =
real value, not urgent. P3 = hygiene/docs/process, opportunistic.

---

## P0 — Fix soon (integrity/correctness gaps already surfaced)

| Todo | Gap |
|---|---|
| [091](pending/091-fisher-z-ci-empirical-null-miscalibration.md) | Fisher-z analytic CI empirically miscalibrated — 38% SUSPECT rate across strata; this is the exact mechanism behind every BH-FDR/EIC-04 gate in the stack. Bootstrap fix shipped (143.1-01); the connection-lifecycle bug that was stalling the corpus-wide re-run is fixed and closed ([102](completed/102-ic-engine-idle-session-timeout-writes-zero-rows.md)). Re-run (143.1-07) is **in progress**, restarted 2026-07-13T13:13:58 UTC under the corrected todo-096 estimator too, ~9/80 symbols as of 15:19 UTC, projected complete ~2026-07-14T10:00 UTC + ~1-1.5h for steps 6-8. |
| [094](pending/094-alpha-events-long-short-imbalance.md) | **Root cause corrected 2026-07-11** (Fable review, verified against live DB): not a floor-formula issue — two sign-asymmetric gates (`ic_ci_lower > 0` eligibility filter, `fold_ic > 0` walk-forward criterion) exclude 100% of contrarian features before weighting ever runs. Confirmed: 1,527 eligible rows, zero at `ic_sign=-1`. Requires a full `ic_engine` re-run + eligibility/quality-weight/E2-sign-path redesign, not a small patch — effort raised M-L. Full strategy: `docs/plans/2026-07-11-ic-quality-and-sign-symmetry-strategy.md`. Sign-symmetric redesign shipped (143.1-04); mandatory shadow-mode champion/challenger validation (143.1-08) still pending, blocked on 143.1-07's corpus re-run (in progress, see 091 above). |
| [099](pending/099-bootstrap-ci-staged-validation-gate-not-cleared-5m-residual.md) | Downgraded P1→P2 2026-07-11 (ledger E10): the bootstrap CI staged-validation gate's 6 SUSPECT cells traced to 5 diagnostic-only (`is_pooled=false`) breaches + 1 capital-relevant cell that independently clears its own bound — no longer blocks Plan 07. Underlying statistical question (why 5m autocorrelation/momentum features resist both Fisher-z and block-bootstrap) remains open as non-blocking follow-up. |
| [096](pending/096-frame-hold-horizon-vs-feature-lookahead-mismatch.md) | **Estimator fix IMPLEMENTED 2026-07-13** (Fable sign-off obtained, TDD'd, `tests/unit/` green): `_compute_ic_rolling_metrics` now uses a fixed subsampled-bar window (`alpha.ic.sharpe_window_size_subsampled=100`, migration 230) instead of raw-bars÷stride, removing the `sqrt(window_size_ratio)` deflation at long lookaheads. Mandatory threshold rescale shipped in the same migration (`alpha.ensemble_ic.decay_threshold` 0.1→0.05, `alpha.ensemble.sharpe_floor` 0.05→0.025, `alpha.feature_registry.min_ic_sharpe_default` 0.5→0.25). **Remaining, blocking:** corpus re-run to re-derive every historical `ic_sharpe`/`hold_max_bars` value is **in progress** (same 143.1-07 run as 091 above — one re-run serves both fixes). Still blocks 088 (locked sequencing, unchanged) until that re-run completes. Reproduce/verify: `python scripts/analysis/ic_sharpe_stride_bias_check.py`. |
| [119](pending/119-migration-schema-drift-ci-check.md) | **Filed 2026-07-14** (Phase 160 shipped-code review): committed migrations 233/234 had silently diverged from what was actually applied to the live DB — wrong column types, missing columns, wrong CHECK vocab, wrong APR namespace, a data typo. Root cause: worktree-executed migrations got regenerated-from-description instead of merged when folded into `main`. Fixed in commit `6f1b4257`; no automated check exists to catch a recurrence. Project-wide migrations-pipeline gap, not Phase-160-specific. |

**Closed 2026-07-10** (moved to `completed/`, see each file's resolution note): 051 (backfill
IBKR-disconnect silent skip), 061 (`feature_vector_pipeline` DDL in hot path), 044 (`indicagent-tempo`
crash-loop). **Closed 2026-07-12**: 098 (stale idea-doc refresh, both items done via parallel
Fable review), 095 (migrations directory collision, fixed in a concurrent session, commit
`fc5f2691`), 093 (`alpha_frames` backfill + FRAME-04 gate evaluated — gate FAILS 16/17 cells on
current pre-143.1-fix data, recorded as the baseline Phase 143.1-08's shadow comparison diffs
against), 090 (IC decomposition hit-rate × magnitude — confirmed already shipped as 143.1-05,
live in `ic_engine.py`, nothing left to do), 072 (crowding proxy regression — built
`scripts/analysis/crowding_proxy_regression.py`, first run against the live pre-143.1-fix
`alpha_frames` backfill: max R²=0.2674 at 1d/mid_bull, 0.003-0.09 at the primary 5m/15m strata —
no crowding alarm yet; standing diagnostic, re-run each future corpus epoch, see
`docs/analysis/crowding-proxy-report.md`). **Closed 2026-07-13**: 109 (Fisher-z CI bracket clamp
moved into `ic_math.py`, folded into `_fisher_z_ci` itself), 087 (shared
`Float32ChunkAccumulator` built in `services/_batch_utils.py`, wired into `_compute_symbol_tf` +
`_compute_cross_sectional_tf`; `ensemble_ic_engine.py`'s pooled fetch correctly left out — it
reduces via a generator, not the same materialize-a-matrix shape), 102 (idle-session-timeout
connection-lifecycle bug, triple-confirmed fixed across 3 separate run attempts), 084 (ensemble
degradation ablation protocol — leave-one-family-out script, tests, report renderer, and CLI
wiring all shipped and merged to `main`). **058 (Concept Registry MVP) closed 2026-07-13** —
moved to `completed/`, not because the work is built (it isn't — zero `concept_*` tables exist),
but because it duplicated [112](pending/112-concept-registry.md) as a second standalone P1 entry
for the same scope. 112 is now the sole live tracking item; 058 stays as frozen historical record
for its 14 existing citations. Implementation plan remains valid and unexecuted
(`docs/plans/2026-07-13-concept-registry-mvp-implementation-plan.md`).

**Explicit sequencing decision (2026-07-10, project owner confirmed; reaffirmed 2026-07-11 after
094's root cause was corrected, and again 2026-07-11 to insert 097 — see
`docs/plans/2026-07-11-ic-quality-and-sign-symmetry-strategy.md` for the full rationale):** 093
(`alpha_frames` backfill, in progress) → **091** → **097** (vol-normalized return target, split
from todo 077's L3-1, validated as an explicit A/B against the raw-return baseline) → **094** (now
including its E2 sign-path fix and a mandatory shadow-mode validation before promotion) → re-run
the E1-vs-E2 A/B judgment (the prior 20/20 result was all-long vs all-long, doesn't carry forward)
→ 096 (three passes 2026-07-12: found a mismatch, corrected the attribution, then quantitatively
CONFIRMED a `sharpe_window_size`/stride estimator bias in `_compute_ic_rolling_metrics` that
under-measures long-horizon signals — see todo file. Fix touches `ic_engine.py` +
`ensemble_ic_engine.py` and needs a full corpus recalibration, so it now belongs in this same
sequencing conversation rather than running fully independent of 088) → 088 (deliberately last,
now informed by 096's finding). Rationale: 091, 097, and 094 all
read or directly affect `ic_ci_lower`/`ic_ci_upper`, and 094 independently requires a full
`ic_engine` re-run — sequencing 091 and 097 first means one corpus re-run serves all three fixes
instead of splitting across multiple, and 094's eligibility redesign runs against the
already-corrected CI and return-target measurement rather than the old one. Do not reorder
without re-confirming with the project owner.

## P1 — High value, quick, fully unblocked

| Todo | Why now |
|---|---|
| [065](pending/065-emission-layer-calibration-proposals.md) | EM-CAL threshold calibration — both prerequisite gates (rebuild, EIC-04) cleared 2026-07-09 |
| [079](pending/079-anytime-valid-e-values-corpus-reruns.md) | Anytime-valid inference pilot (one tf) — new statistical primitive, deliberately staged small |
| [080](pending/080-ensemble-combination-e-candidates-queue.md) | Posterior-blended weighting (L5-1) — testable now via existing A/B judge, zero new data |
| [097](pending/097-vol-normalized-return-target-pooled-ic.md) | Vol-normalized return target for POOLED-strata IC — split from todo 077's L3-1, 2026-07-11; folded into Phase 143.1 (Component F) as an explicit A/B, not a silent swap |
| [092](pending/092-equity-regime-model-threshold-calibration.md) | Empirical threshold calibration for regime-model vix/breadth cuts — flagged 2026-07-09 as a live-path suspect behind the extreme regime-conditional IC values on the current leaderboard |
| [054](pending/054-shadow-alpha-events-monitoring.md) | Shadow alpha_events monitoring — prevents delayed detection of feature decay/threshold bugs |
| [011](pending/011-alpha-events-is-shadow_column.md) | `is_shadow` column — promotion gate can't be retroactively softened once this lands |

## P2 — Real value, not urgent

| Todo | What |
|---|---|
| [101](pending/101-migration-duplicate-number-sweep.md) | Filed 2026-07-12 (found while resolving todo 095) — `production/migrations/` has 13 duplicate-number groups (001, 031, 038, 050-052, 064, 138, 152, 168, 178, 214-215), not just the one 095 knew about. Finding + recommended approach only; deliberately not executed same-session given live-DB rename risk. |
| [108](pending/108-hmm-multi-seed-restart-best-likelihood.md) | Filed 2026-07-12 (split from deferred todo 026 P2a, verified still open against live code — the one 026 sub-item never batched into Phase 144 or forked elsewhere) — `regime_writer.py`'s HMM fit uses a single seed with a same-seed convergence retry, not multi-seed-restart-and-keep-best-log-likelihood. Robustness gap, not a proven bug. |
| [103](pending/103-momentum-apr-keys-inert-prewarm-mismatch.md) | Filed 2026-07-12 (found while scoping todo 072) — `feature.momentum.window_fast/mid/slow` APR keys are silently inert (prewarm list loads nonexistent `_short`/`_long` keys instead); `volatility_rank_z`/`momentum_rank_z`/`volume_rank_z` are unimplemented (always NULL). Not fixed — touches live hot-path pipeline code, out of scope for the session that found it. |
| [005](pending/005-ic-regime-transition-purge.md) | Purge regime-transition label noise from IC measurement |
| [033](pending/033-zero-ic-feature-refinement.md) | Refine remaining zero-IC features (rerun gate now cleared) |
| [038](pending/038-cross-sectional-collinearity-diagnostic.md) | Cross-sectional feature collinearity diagnostic vs IC |
| [039](pending/039-tag-stratified-ic-population-check.md) | Population-count check before tag-stratified cross-sectional IC |
| [081](pending/081-emission-meta-labeling-and-conviction-cross-ref.md) | Emission meta-labeling gate — check overlap with 065/EM-HYST before building |
| [086](pending/086-hmm-test-coverage-gaps.md) | HMM regime-writer test coverage gaps (occupation gate, smooth-check false positive) |
| [088](pending/088-hold-max-bars-censoring-not-tracked.md) | `hold_max_bars` calibration doesn't distinguish confirmed decay from censored data. **Note (2026-07-12): briefly and incorrectly merged into 096 same day, then reverted** — 088 and 096 are locked as separately-sequenced steps (093→091→097→094→A/B re-run→096→088) per PRIORITIES.md's own "do not reorder" decision and multiple frozen phase artifacts; see 088's file for the full correction. |
| [089](pending/089-ensemble-ic-engine-recurring-cadence.md) | No recurring `ensemble_ic_engine` schedule exists — IC-decay trigger input can go stale |
| [009](pending/009-service-utils-ic-engine-cleanup.md) | Phase B infra cleanup batch — APR compliance sweep, `BaseBatch` promotion, naming vocab, shared-utility DRY fixes, `ic_engine.py` pure-function extraction (merged 012 + 032 here 2026-07-12, all three were gated on the same sprint) |
| [029](pending/029-feature-scoring-beyond-ic.md) | Feature scoring beyond IC (near-term derived metrics) |
| [050](pending/050-ibkr-apr-migration.md) | Migrate `ibkr.py` hardcoded constants to APR |
| [052](pending/052-adversarial-data-error-hunt.md) | Adversarial data-error hunt batch job |
| [053](pending/053-oos-look-log-audit-trail.md) | OOS-look audit trail log |
| [042](pending/042-15m-chunk-size-retest.md) | Re-test 15m backfill chunk size (likely too conservative) |
| [024](pending/024-feature-decay-observatory.md) | Feature decay/crowding observatory dashboard |

## P3 — Hygiene, docs, process (opportunistic)

| Todo | What |
|---|---|
| [056](pending/056-phase146-147-v2x-retirement-stale.md) | Phase 147/148 gate definitions stale (filename kept as-is) — needs an operator call (archive vs delete v2.x) before those phases are planned |
| [035](pending/035-market-ohlcv-active-bars-view.md) | `market_data_ohlcv` active-bars filter belongs at one boundary, not 4 call sites |
| [064](pending/064-indicagent-test-db-schema-sync.md) | Test DB schema sync — unblocks integration tests needing a live-migrated schema |
| [059](pending/059-review-aegisagent-tradeagent-for-trade-construction-reuse.md) | Review AegisAgent/TradeAgent for v4.0 trade-construction reuse |
| [060](pending/060-review-cluster2-legacy-intelligence-backlog.md) | Review legacy intelligence backlog docs — salvage or clear |
| [022](pending/022-bi-superset.md) | Self-service BI (Superset) for ad-hoc analytics |
| [110](pending/110-controlled-vocabulary.md) | Controlled Vocabulary — design complete, previously untracked by any todo. No dependency blocks it. **Registered as ROADMAP Phase 160** (supersedes orphaned Phase 135). |
| [111](pending/111-stratification-classification.md) | Stratification & Classification Registries — StratificationDimension formalization revival blocked on Phase 144's D-05 verdict (currently `BLOCKED-ON-143.1-07`). **Registered as ROADMAP Phase 145.** |
| [104](pending/104-quarterly-seasonality-opex-fable-review.md) | Fable rigor pass on the quarterly-seasonality/OPEX idea (`docs/ideas/signal-quarterly-seasonality-opex-risk-off.md`) before it's considered for Phase 151's scope — review-gating step, not itself a phase. |

---

**Concept Registry / Controlled Vocabulary / Stratification cluster (2026-07-13):** consolidated
to exactly 3 top-level todos, one per system, each intended to become a full GSD phase next —
the prior scatter (058, 105, 106, 076, 041 as separate standalone items) was the actual clutter,
not a virtue. Deferred/speculative sub-item content (105, 106, 076, 041) was folded directly into
the relevant canonical design doc rather than kept as separate files — `concept-unified-registry.md`
(regime_model domain seeding sequence), `stratification-dimension-unification.md` (new candidate
dimensions + formalization revival note), `stratification-instrument-tag-calibrator.md` (tag
taxonomy open question) — since those were forward-looking notes on ideas already fully described
in their own docs, not standalone actionable work.

- [110 — Controlled Vocabulary](pending/110-controlled-vocabulary.md) — previously had zero todo tracking it at all
- [111 — Stratification & Classification](pending/111-stratification-classification.md) — moved out of `deferred/` 2026-07-13 (its own frontmatter already said `status: pending`, directory placement was the mismatch); registered as ROADMAP Phase 145, gated on Phase 144's D-05 verdict

---

**Not in this list:** anything in `deferred/` (phase-gated or corpus-rerun-batched) or
`completed/` (done). Check those folders directly for that work.
