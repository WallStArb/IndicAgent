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

---

## P0 — Fix soon (integrity/correctness gaps already surfaced)

| Todo | Gap |
|---|---|
| [091](pending/091-fisher-z-ci-empirical-null-miscalibration.md) | Fisher-z analytic CI empirically miscalibrated — 38% SUSPECT rate across strata; this is the exact mechanism behind every BH-FDR/EIC-04 gate in the stack. Bootstrap fix shipped (143.1-01). Corpus re-run (143.1-07) is **in progress**: per-symbol pass at 53/80 as of 2026-07-18 06:05 UTC (~14h elapsed, healthy), cross-sectional POOLED pass has not started yet (duration uncertain once it does, prior first-group alone took ~9h and this covers many more regime×tf groups). Check `logs/ic_engine.log` (`grep symbol_computed\|cross_sectional`) and `ps aux \| grep ic_engine` for current progress. |
| [094](pending/094-alpha-events-long-short-imbalance.md) | Two sign-asymmetric gates (`ic_ci_lower > 0` eligibility filter, `fold_ic > 0` walk-forward criterion) exclude 100% of contrarian features before weighting ever runs. Sign-symmetric redesign shipped (143.1-04); mandatory shadow-mode champion/challenger validation (143.1-08) still pending, blocked on 143.1-07's corpus re-run (in progress, see 091 above). |
| [099](pending/099-bootstrap-ci-staged-validation-gate-not-cleared-5m-residual.md) | P2 — the bootstrap CI staged-validation gate's 6 SUSPECT cells trace to 5 diagnostic-only (`is_pooled=false`) breaches + 1 capital-relevant cell that independently clears its own bound — no longer blocks Plan 07. Underlying statistical question (why 5m autocorrelation/momentum features resist both Fisher-z and block-bootstrap) remains open as non-blocking follow-up. |
| [096](pending/096-frame-hold-horizon-vs-feature-lookahead-mismatch.md) | Estimator fix implemented: `_compute_ic_rolling_metrics` now uses a fixed subsampled-bar window (`alpha.ic.sharpe_window_size_subsampled=100`, migration 230) instead of raw-bars÷stride, removing the `sqrt(window_size_ratio)` deflation at long lookaheads. Threshold rescale shipped in the same migration. **Remaining, blocking:** corpus re-run to re-derive every historical `ic_sharpe`/`hold_max_bars` value is in progress (same 143.1-07 run as 091 above). Still blocks 088 until that re-run completes. Reproduce/verify: `python scripts/analysis/ic_sharpe_stride_bias_check.py`. |
| [119](pending/119-migration-schema-drift-ci-check.md) | Committed migrations can silently diverge from what's actually applied to the live DB (wrong column types, missing columns, wrong CHECK vocab, wrong APR namespace). No automated check exists to catch a recurrence. **Merged with [064](completed/064-indicagent-test-db-schema-sync.md)** (indicagent_test has no schema) — one integration test replaying migrations against `indicagent_test` and diffing against production schema fixes both gaps at once. |

**Locked sequencing decision (project owner confirmed, do not reorder without re-confirming):**
093 (`alpha_frames` backfill, done) → **091** → **097** (vol-normalized return target, explicit
A/B against the raw-return baseline) → **094** (E2 sign-path fix + mandatory shadow-mode
validation before promotion) → re-run the E1-vs-E2 A/B judgment (the prior 20/20 result was
all-long vs all-long, doesn't carry forward) → **096** → **088** (deliberately last, informed by
096's finding). Rationale: 091, 097, and 094 all read or directly affect
`ic_ci_lower`/`ic_ci_upper`, and 094 independently requires a full `ic_engine` re-run —
sequencing 091 and 097 first means one corpus re-run serves all three fixes instead of splitting
across multiple.

## P1 — High value, quick, fully unblocked

| Todo | Why now |
|---|---|
| [065](pending/065-emission-layer-calibration-proposals.md) | EM-CAL threshold calibration — both prerequisite gates (rebuild, EIC-04) cleared 2026-07-09 |
| [079](pending/079-anytime-valid-e-values-corpus-reruns.md) | Anytime-valid inference pilot (one tf) — new statistical primitive, deliberately staged small |
| [080](pending/080-ensemble-combination-e-candidates-queue.md) | Posterior-blended weighting (L5-1) — testable now via existing A/B judge, zero new data |
| [097](pending/097-vol-normalized-return-target-pooled-ic.md) | Vol-normalized return target for POOLED-strata IC — folded into Phase 143.1 (Component F) as an explicit A/B, not a silent swap |
| [092](pending/092-equity-regime-model-threshold-calibration.md) | Empirical threshold calibration for cross-sectional regime-model vix/breadth cuts — live-path suspect behind extreme regime-conditional IC values on the current leaderboard |
| [054](pending/054-shadow-alpha-events-monitoring.md) | Shadow alpha_events monitoring — prevents delayed detection of feature decay/threshold bugs |

## P2 — Real value, not urgent

| Todo | What |
|---|---|
| [101](pending/101-migration-duplicate-number-sweep.md) | `production/migrations/` has 13 duplicate-number groups (001, 031, 038, 050-052, 064, 138, 152, 168, 178, 214-215). Finding + recommended approach only; deliberately not executed given live-DB rename risk. |
| [108](pending/108-hmm-multi-seed-restart-best-likelihood.md) | `regime_writer.py`'s HMM fit uses a single seed with a same-seed convergence retry, not multi-seed-restart-and-keep-best-log-likelihood. Robustness gap, not a proven bug. |
| [103](pending/103-momentum-apr-keys-inert-prewarm-mismatch.md) | `feature.momentum.window_fast/mid/slow` APR keys are silently inert (prewarm list loads nonexistent `_short`/`_long` keys instead); `volatility_rank_z`/`momentum_rank_z`/`volume_rank_z` are unimplemented (always NULL). Touches live hot-path pipeline code. |
| [005](pending/005-ic-regime-transition-purge.md) | Purge regime-transition label noise from IC measurement |
| [033](pending/033-zero-ic-feature-refinement.md) | Refine remaining zero-IC features (rerun gate now cleared) |
| [038](pending/038-cross-sectional-collinearity-diagnostic.md) | Cross-sectional feature collinearity diagnostic vs IC |
| [039](pending/039-tag-stratified-ic-population-check.md) | Population-count check before tag-stratified cross-sectional IC |
| [081](pending/081-emission-meta-labeling-and-conviction-cross-ref.md) | Emission meta-labeling gate — check overlap with 065/EM-HYST before building |
| [086](pending/086-hmm-test-coverage-gaps.md) | HMM regime-writer test coverage gaps (occupation gate, smooth-check false positive) |
| [088](pending/088-hold-max-bars-censoring-not-tracked.md) | `hold_max_bars` calibration doesn't distinguish confirmed decay from censored data. Locked as a separately-sequenced step (093→091→097→094→A/B re-run→096→088) — see the P0 sequencing decision above. |
| [089](pending/089-ensemble-ic-engine-recurring-cadence.md) | No recurring `ensemble_ic_engine` schedule exists — IC-decay trigger input can go stale |
| [009](pending/009-service-utils-ic-engine-cleanup.md) | Phase B infra cleanup batch — APR compliance sweep, `BaseBatch` promotion, naming vocab, shared-utility DRY fixes, `ic_engine.py` pure-function extraction |
| [029](pending/029-feature-scoring-beyond-ic.md) | Feature scoring beyond IC (near-term derived metrics) |
| [050](pending/050-ibkr-apr-migration.md) | Migrate `ibkr.py` hardcoded constants to APR |
| [052](pending/052-adversarial-data-error-hunt.md) | Adversarial data-error hunt batch job |
| [053](pending/053-oos-look-log-audit-trail.md) | OOS-look audit trail log |
| [042](pending/042-15m-chunk-size-retest.md) | Re-test 15m backfill chunk size (likely too conservative) |
| [024](pending/024-feature-decay-observatory.md) | Feature decay/crowding observatory dashboard |
| [125](pending/125-tag-calibrator-discovery-oos-gate-not-enforced.md) | TagCalibrator's `discovery_oos_days` OOS-confirmation gate computed but never enforced — new discoveries go live immediately. Zero current blast radius (no live consumer reads the affected tags yet, see 126). |
| [126](pending/126-instrument-tags-valid-to-no-consumer-contract.md) | No `instrument_tags` reader filters on `valid_to` — expiry has no observable effect yet, no contract established for future consumers. Resolve before/alongside 125. |
| [135](pending/135-cross-sectional-regime-grid-shape-never-validated.md) | Cross-sectional regime grid shape (9 equity cells, 6 rates cells) has never been validated as a model-selection question — unlike HMM's K=5, which went through a real BIC study. Distinct from todo 092 (cut-point values within the existing shape). |
| [078](pending/078-frame-outcome-labels-second-outcome-definition.md) | Register frame-outcome (barrier-hit sign) as a second outcome definition alongside forward-return IC, now that `alpha_frames` has real data. Gate cleared 2026-07-12 (todo 093 backfill ran); moved back to pending/ 2026-07-18. Diagnostic value, not a reason to touch 142B's frozen design. |
| [082](pending/082-simulation-validation-lenses-post-142b.md) | Additional read-only simulation/validation lenses over `alpha_frames` (standing permutation nulls, etc.) — same gate-cleared status as 078. No new judgment surface, mechanical. |
| [117](pending/117-feature-registry-operator-override-actuator-missing.md) | `feature_registry`'s `deprecated` status is reachable in the CHECK constraint and reasoned about in code comments, but no actuator exists — no CLI/ops script/dashboard endpoint calls `record_transition_sync(reason='operator_override')` anywhere. An operator who wants to kill a bad feature today has to bypass the audit trail entirely (manual SQL UPDATE). Worth building before Concept Registry migrates `domain='feature'` in (todo 118), so the actuator pattern is proven on the simpler system first. |
| [118](pending/118-migrate-feature-domain-into-concept-registry.md) | Migrate `feature_registry` (`domain='feature'`) into the Concept Registry MVP (shipped 2026-07-13 with only `domain='ensemble_strategy'` seeded). Sequencing blocker resolved (Phase 143 already shipped against `feature_registry` directly, so this is now a plain fold-in, not a race). Touches the live feature lifecycle path — do after 117 proves the actuator pattern. |
| [120](pending/120-alpha-frames-missing-is-shadow.md) | `alpha_frames` has no `is_shadow` column — once Phase 144 promotion flips `alpha.publisher.is_shadow` to `false`, shadow and live frames will silently mix in the same table with no way to isolate the pre-promotion shadow window for the promotion-gate math. Not urgent (no promotion has happened yet, every row today is unambiguously shadow) but should land before Phase 144's promotion gate is ever exercised. |

## P3 — Hygiene, docs, process (opportunistic)

| Todo | What |
|---|---|
| [056](pending/056-phase146-147-v2x-retirement-stale.md) | Phase 147/148 gate definitions stale (filename kept as-is) — needs an operator call (archive vs delete v2.x) before those phases are planned |
| [124](pending/124-market-ohlcv-tradeable-view-tier2-audit.md) | Tier-2 follow-up: 14 remaining `market_data_ohlcv` call sites to classify/migrate to `market_data_ohlcv_tradeable`, split from closed todo 035 |
| [123](pending/123-momentum-velocity-and-macro-spread-features.md) | Momentum-oscillator velocity feature + VWAP acceleration + 2 now-unblocked macro spreads (TIP real-yield, HYG/LQD credit spread) — surfaced by closing todo 060, batch into a future Phase 151 pass |
| [022](pending/022-bi-superset.md) | Self-service BI (Superset) for ad-hoc analytics |
| [131](pending/131-vocabulary-drift-should-extend-basebatch.md) | `vocabulary_drift.py`'s oneshot entrypoint hand-rolls the D-06 lifecycle instead of extending `BaseBatch`, like every other batch oneshot does. Consistency, not a bug. |
| [132](pending/132-vocabulary-drift-hardcoded-namespace-taxonomies.md) | `vocabulary_drift.py` hardcodes the `regime_group` taxonomy and namespace-query dict it exists to govern drift against — self-referential gap, needs a startup assertion or a new controlled_vocabulary namespace. |
| [111](pending/111-stratification-classification.md) | Stratification & Classification Registries — StratificationDimension formalization revival blocked on Phase 144's D-05 verdict (currently `BLOCKED-ON-143.1-07`). **Registered as ROADMAP Phase 145.** |
| [114](pending/114-ensemble-measurement-missing-functional-slot.md) | `predictive measurement`'s glossary definition is narrower than its own stated intent — doesn't explicitly cover its ensemble-grain recurrence (`ensemble_ic_engine.py`, same operation as feature-grain `ic_engine.py`, different input/position). Docs-only fix, no code/schema change. |
| [115](pending/115-days-to-month-end-exact-redundancy.md) | `days_to_month_end` is an exact affine complement of `month_position` (Pearson correlation -1) — perfectly collinear, remove one. |
| [116](pending/116-above-wk-vwap-miscategorized-calendar-group.md) | `above_wk_vwap` is registered `group_name='calendar'` in `feature_registry` but is price-dependent/stateful, not a pure calendar primitive — miscategorized. |
| [129](pending/129-ic-engine-short-lived-conn-helper.md) | `ic_engine.py`'s 3 dsn-based worker connections still hand-rolled (`open → use → close`) instead of a shared helper — narrowed 2026-07-17 after the `main()`-side half was already fixed via todo 130. |
| [137](pending/137-api-routes-no-request-level-smoke-test.md) | No generic guard catches a broken function-local import in an API route (the exact bug class todo 130 fixed) — needs a parametrized smoke test hitting every registered route with mocked deps. |
| [138](pending/138-drift-route-swallows-db-errors-as-healthy-empty.md) | `GET /api/drift` returns 200 + empty state on any DB failure, indistinguishable from genuine "no drift" — should distinguish degraded from empty, like `vocabulary.py` does. |

---

**Not in this list:** anything in `deferred/` (phase-gated or corpus-rerun-batched) or
`completed/` (done). Check those folders directly for that work.
