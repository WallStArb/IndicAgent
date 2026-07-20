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
| [094](pending/094-alpha-events-long-short-imbalance.md) | Two sign-asymmetric gates (`ic_ci_lower > 0` eligibility filter, `fold_ic > 0` walk-forward criterion) excluded 100% of contrarian features before weighting ever ran. Sign-symmetric redesign shipped (143.1-04, verified live in `ic_engine.py`/`ensemble_trainer.py`). **Now unblocked:** mandatory shadow-mode champion/challenger validation (143.1-08) can proceed — 143.1-07's corpus re-run finished 2026-07-19. **IN PROGRESS as of 2026-07-20 in a separate session/worktree (`worktree-agent-acc3e6a78746c2514`, commit `39537537` at last check, not yet merged to main) — check `git worktree list` / that branch before dispatching this, do not duplicate.** |
| [099](pending/099-bootstrap-ci-staged-validation-gate-not-cleared-5m-residual.md) | P2 — the bootstrap CI staged-validation gate's 6 SUSPECT cells trace to 5 diagnostic-only (`is_pooled=false`) breaches + 1 capital-relevant cell that independently clears its own bound — no longer blocks Plan 07. Underlying statistical question (why 5m autocorrelation/momentum features resist both Fisher-z and block-bootstrap) remains open as non-blocking follow-up. |
| [096](pending/096-frame-hold-horizon-vs-feature-lookahead-mismatch.md) | **Estimator fix CONFIRMED 2026-07-19** — re-ran the (previously stale/crashing) Monte Carlo verification script against live post-fix APR: all four lookahead scales now report near-identical `ic_sharpe` at every true-correlation level (e.g. 0.9957/0.9957/0.9932/0.9906 at rho=0.10), vs. the old bug's documented 2-3.6x deflation at long horizons. **096's own diagnostic scope is done, but this does NOT unblock 088 yet** — checked directly: `ensemble_trainer`/`ensemble_ic_engine` have not run since 2026-07-10 (`alpha_ensemble_ic` has zero rows, both logs empty since 07-11), so production `hold_max_bars` still reflects PRE-fix weights. 143.1-07 only refreshed `ic_engine`'s feature-level values, not the full pipeline. |

**Locked sequencing decision (project owner confirmed, do not reorder without re-confirming):**
093 (`alpha_frames` backfill, done) → **091 (done 2026-07-19, moved to `completed/`)** →
**097 (done 2026-07-19, moved to `completed/`)** →
**094** (E2 sign-path fix + mandatory shadow-mode validation before promotion) → re-run the
E1-vs-E2 A/B judgment (the prior 20/20 result was all-long vs all-long, doesn't carry forward) →
**096** → **088** (deliberately last, informed by 096's finding). Rationale: 091, 097, and 094 all
read or directly affect `ic_ci_lower`/`ic_ci_upper`, and 094 independently requires a full
`ic_engine` re-run — sequencing 091 and 097 first meant one corpus re-run served all three fixes
instead of splitting across multiple. **Status 2026-07-19: the shared corpus re-run (143.1-07)
completed; 091 is fully closed (standing dependence-length flag landed via todo 145, see
`completed/`) and 097 is fully closed. Next in the chain: 094's shadow-mode validation
(143.1-08).**

## P1 — High value, quick, fully unblocked

| Todo | Why now |
|---|---|
| [065](pending/065-emission-layer-calibration-proposals.md) | EM-CAL threshold calibration — both prerequisite gates (rebuild, EIC-04) cleared 2026-07-09 |
| [079](pending/079-anytime-valid-e-values-corpus-reruns.md) | Anytime-valid inference pilot (one tf) — new statistical primitive, deliberately staged small |
| [080](pending/080-ensemble-combination-e-candidates-queue.md) | Posterior-blended weighting (L5-1) — testable now via existing A/B judge, zero new data |
| [147](pending/147-vol-normalized-target-low-bull-divergence.md) | **Root cause CONFIRMED 2026-07-20, blocker CLEARED 2026-07-20** — `low_bull`'s vol-normalized/raw IC rank-correlation collapse is corrupt-print contamination of `true_range_pct` (the vol-normalization denominator), same class as 148/149/151/152: `low_bull`'s CV is 10-100x every other regime's while its mean is normal — traced to a handful of fabricated OHLCV prints (`VWO`/`UUP`/`XRT` corrected via 151; `DIA`/`KRE` corrected via [154](completed/154-dia-kre-corrupt-print-cleanup-residual.md), closed 2026-07-20). **Next action: re-check the CV and re-run `ops_vol_normalized_target_ab.py --all-regimes`** — should resolve as a side effect now that all known contamination is corrected. |
| [146](pending/146-lookahead-grid-per-tf-recalibration.md) | `alpha.ic.lookahead.*`'s uniform 1/5/20/60-bar grid confirmed broken on intraday tfs, now confirmed on 1d too — full-corpus re-run (2026-07-20) + a stride-correction fix to the diagnostic itself (Fable 5 caught the CI was computed on serially-dependent, unstrided observations) found 1d's `extended=60` cell also fails (CI half-width > IC point estimate for every horizon ≥20). Final confirmed Step 2 grid for all 4 tfs is in the todo (1d compresses to 1/2/5/10; 5m/15m/1h candidates unchanged, now confirmed at full scale). **Step 3 (apply to production APR) deliberately rides the NEXT full corpus rebuild — batch together with [155](pending/155-price-sanity-status-historical-backfill.md)'s backfill effects rather than triggering a rebuild for either alone.** |
| [092](pending/092-equity-regime-model-threshold-calibration.md) | **Population imbalance CONFIRMED 2026-07-20** — `low_bull` is 12-17x more populated than `low_bear` across all 4 tfs, root cause isolated to the `breadth_frac` cut (0.40/0.60, fixed, never checked against its own distribution — median is 0.70-0.76, well above the "bull" cutoff). VIX cut is already percentile-based, not affected. Candidate population-balanced cuts: ~0.49/0.83 (5m/15m/1h), ~0.59/0.86 (1d). Still open: whether balancing actually improves regime-conditional IC separation — that's corpus-scale work, next real step. |
| [054](pending/054-shadow-alpha-events-monitoring.md) | Shadow alpha_events monitoring — prevents delayed detection of feature decay/threshold bugs |

## P2 — Real value, not urgent

| Todo | What |
|---|---|
| [101](pending/101-migration-duplicate-number-sweep.md) | `production/migrations/` has 13 duplicate-number groups (001, 031, 038, 050-052, 064, 138, 152, 168, 178, 214-215). Finding + recommended approach only; deliberately not executed given live-DB rename risk. |
| [108](pending/108-hmm-multi-seed-restart-best-likelihood.md) | `regime_writer.py`'s HMM fit uses a single seed with a same-seed convergence retry, not multi-seed-restart-and-keep-best-log-likelihood. Robustness gap, not a proven bug. |
| [103](pending/103-momentum-apr-keys-inert-prewarm-mismatch.md) | `feature.momentum.window_fast/mid/slow` APR keys are silently inert (prewarm list loads nonexistent `_short`/`_long` keys instead); `volatility_rank_z`/`momentum_rank_z`/`volume_rank_z` are unimplemented (always NULL). Touches live hot-path pipeline code. |
| [005](pending/005-ic-regime-transition-purge.md) | Purge regime-transition label noise from IC measurement — re-scoped 2026-07-19, held for 143.1 sequencing (see file) |
| [038](pending/038-cross-sectional-collinearity-diagnostic.md) | Cross-sectional feature collinearity diagnostic vs IC |
| [039](pending/039-tag-stratified-ic-population-check.md) | Population-count check before tag-stratified cross-sectional IC |
| [081](pending/081-emission-meta-labeling-and-conviction-cross-ref.md) | Emission meta-labeling gate — check overlap with 065/EM-HYST before building |
| [088](pending/088-hold-max-bars-censoring-not-tracked.md) | `hold_max_bars` calibration doesn't distinguish confirmed decay from censored data. Locked as a separately-sequenced step (093→091→097→094→A/B re-run→096→088) — see the P0 sequencing decision above. |
| [089](pending/089-ensemble-ic-engine-recurring-cadence.md) | No recurring `ensemble_ic_engine` schedule exists — IC-decay trigger input can go stale |
| [009](pending/009-service-utils-ic-engine-cleanup.md) | Phase B infra cleanup batch — APR compliance sweep, `BaseBatch` promotion, naming vocab, shared-utility DRY fixes, `ic_engine.py` pure-function extraction |
| [029](pending/029-feature-scoring-beyond-ic.md) | Feature scoring beyond IC (near-term derived metrics) |
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
| [153](pending/153-vp-sr-features-null-in-batch-corpus.md) | **NEEDS OPERATOR DECISION** — found 2026-07-19 while re-verifying todo 033 (closed): `poc_dist_atr`/`va_position`/`sr_support_dist`/`sr_resist_dist` are stuck at `FeatureCache` dataclass defaults in **both live and batch** — nothing in v3 ever wires a mutator for them (the real computation lives only in the archived v2.x `i3_structure` plugin, never connected to v3's `FeatureCache`). `feature_ic_scores`' `ic_value=0` is a constant-input artifact. No current blast radius, but a real "can we trust this data" gap: implement for real (port the archived plugin's math into `FeatureCache`) or delete the stub fields entirely — this call is still open. |
| [155](pending/155-price-sanity-status-historical-backfill.md) | New 2026-07-20, filed closing [149](../completed/149-bar-ingestion-price-sanity-guard.md): live pilot measured ~4.1 years to clear the 215M-row historical backlog at `BarAuditor`'s default batch size/cadence. Raising the batch size risks the daemon's 60s systemd watchdog and conflates one-time historical debt with the ongoing live-stream audit. Needs a dedicated one-time backfill tool, decoupled from `BarAuditor`'s cycle, reusing 149's classification primitives and Task 1's TimescaleDB compressed-chunk lessons. Also: oldest-first ordering means the guard protects nothing live until this lands. **Batch its effects into the same next full corpus rebuild as [146](pending/146-lookahead-grid-per-tf-recalibration.md)'s grid fix, not a standalone rebuild.** |
| [156](pending/156-otel-span-coverage-gap-v3-pipeline.md) | New 2026-07-20, found investigating a user question during 149's final review: OTel metrics are universal (every `BaseDaemon` auto-inherits 5 mandatory signals), but spans are opt-in only and just 6 files use them — `ensemble_trainer.py` and `alpha_publisher.py` (the sole `alpha_events` writer) have zero spans, a real gap on the v3.0 critical path. Kafka trace-context propagation already works end-to-end at the transport layer; span creation at each hop is the missing piece. |
| [157](pending/157-no-mechanical-base-class-compliance-check.md) | New 2026-07-20, same investigation as 156: nothing mechanically checks that new services extend `BaseDaemon`/`BaseWriter`/`BaseBatch`, that spans get used, or that `prometheus_client` stays banned — all convention/review-only, unlike the naming/table-boundary checks this project's pre-commit hook and CI already enforce. Candidate fix reuses the existing allow-list/regex boundary-test pattern. |

## P3 — Hygiene, docs, process (opportunistic)

| Todo | What |
|---|---|
| [056](pending/056-phase146-147-v2x-retirement-stale.md) | ROADMAP Phase 147/148 text rewritten 2026-07-19 (operator call resolved: archive not delete, decouple from proof gates). Remaining scope: the actual decommission-in-fact execution (git mv v2.x code to archive/, disable dead systemd units, rename-not-drop the frozen v2.x tables) — real multi-file operation, do with a clean git state. |
| [124](pending/124-market-ohlcv-tradeable-view-tier2-audit.md) | Tier-2 follow-up: 14 remaining `market_data_ohlcv` call sites to classify/migrate to `market_data_ohlcv_tradeable`, split from closed todo 035 |
| [123](pending/123-momentum-velocity-and-macro-spread-features.md) | Momentum-oscillator velocity feature + VWAP acceleration + 2 now-unblocked macro spreads (TIP real-yield, HYG/LQD credit spread) — surfaced by closing todo 060, batch into a future Phase 151 pass |
| [022](pending/022-bi-superset.md) | Self-service BI (Superset) for ad-hoc analytics |
| [111](pending/111-stratification-classification.md) | Stratification & Classification Registries — StratificationDimension formalization revival blocked on Phase 144's D-05 verdict (currently `BLOCKED-ON-143.1-07`). **Registered as ROADMAP Phase 145.** |
| [115](pending/115-days-to-month-end-exact-redundancy.md) | `days_to_month_end` is an exact affine complement of `month_position` (Pearson correlation -1) — perfectly collinear, remove one. |
| [141](pending/141-todo-directory-duplicate-number-sweep.md) | `.planning/todos/` has 8 duplicate-number groups across pending/completed/deferred — todo-system analog of todo 101's migration finding. Finding + recommended approach only. |
| [142](pending/142-api-routes-http-exception-guard-not-generalized.md) | `except HTTPException: raise` guard hand-copied across 5 `src/api/routes/` files, no shared decorator/mechanism prevents a 6th route reintroducing the same bug. |
| [143](pending/143-api-route-tests-no-shared-fake-db-fixture.md) | `tests/unit/api/` has 4 independent hand-rolled DB test doubles, no shared `conftest.py` fixture. |

---

**Not in this list:** anything in `deferred/` (phase-gated or corpus-rerun-batched) or
`completed/` (done). Check those folders directly for that work.
