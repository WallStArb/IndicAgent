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
intelligence-lifecycle priority matrix (`docs/research/2026-07-08-intelligence-lifecycle-
backlog-matrix.md`) previously kept its own separate "Todos" ranking table for the same
`pending/` items; that table is now collapsed to a pointer here to eliminate the two-places-
that-can-silently-disagree risk. Its former top entry, `alpha_frames` backfill, was a matrix-
only bullet with no corresponding todo file — filed as todo 093 in this same pass so it isn't
invisible to this list.

**Tiers:** P0 = fix soon, real gap/bug surfaced. P1 = high value, quick, fully unblocked. P2 =
real value, not urgent. P3 = hygiene/docs/process, opportunistic.

---

## P0 — Fix soon (integrity/correctness gaps already surfaced)

| Todo | Gap |
|---|---|
| [091](pending/091-fisher-z-ci-empirical-null-miscalibration.md) | Fisher-z analytic CI empirically miscalibrated — 38% SUSPECT rate across strata; this is the exact mechanism behind every BH-FDR/EIC-04 gate in the stack. Bootstrap fix shipped (143.1-01); corpus-wide re-run in flight (143.1-07) as of 2026-07-12 to exercise it against fresh data. |
| [094](pending/094-alpha-events-long-short-imbalance.md) | **Root cause corrected 2026-07-11** (Fable review, verified against live DB): not a floor-formula issue — two sign-asymmetric gates (`ic_ci_lower > 0` eligibility filter, `fold_ic > 0` walk-forward criterion) exclude 100% of contrarian features before weighting ever runs. Confirmed: 1,527 eligible rows, zero at `ic_sign=-1`. Requires a full `ic_engine` re-run + eligibility/quality-weight/E2-sign-path redesign, not a small patch — effort raised M-L. Full strategy: `docs/plans/2026-07-11-ic-quality-and-sign-symmetry-strategy.md`. Sign-symmetric redesign shipped (143.1-04); mandatory shadow-mode champion/challenger validation (143.1-08) still pending, blocked on 143.1-07's corpus re-run. |
| [099](pending/099-bootstrap-ci-staged-validation-gate-not-cleared-5m-residual.md) | Downgraded P1→P2 2026-07-11 (ledger E10): the bootstrap CI staged-validation gate's 6 SUSPECT cells traced to 5 diagnostic-only (`is_pooled=false`) breaches + 1 capital-relevant cell that independently clears its own bound — no longer blocks Plan 07. Underlying statistical question (why 5m autocorrelation/momentum features resist both Fisher-z and block-bootstrap) remains open as non-blocking follow-up. |

**Closed 2026-07-10** (moved to `completed/`, see each file's resolution note): 051 (backfill
IBKR-disconnect silent skip), 061 (`feature_vector_pipeline` DDL in hot path), 044 (`indicagent-tempo`
crash-loop). **Closed 2026-07-12**: 098 (stale idea-doc refresh, both items done via parallel
Fable review).

**Explicit sequencing decision (2026-07-10, project owner confirmed; reaffirmed 2026-07-11 after
094's root cause was corrected, and again 2026-07-11 to insert 097 — see
`docs/plans/2026-07-11-ic-quality-and-sign-symmetry-strategy.md` for the full rationale):** 093
(`alpha_frames` backfill, in progress) → **091** → **097** (vol-normalized return target, split
from todo 077's L3-1, validated as an explicit A/B against the raw-return baseline) → **094** (now
including its E2 sign-path fix and a mandatory shadow-mode validation before promotion) → re-run
the E1-vs-E2 A/B judgment (the prior 20/20 result was all-long vs all-long, doesn't carry forward)
→ 096 (can run in parallel, read-only) → 088 (deliberately last). Rationale: 091, 097, and 094 all
read or directly affect `ic_ci_lower`/`ic_ci_upper`, and 094 independently requires a full
`ic_engine` re-run — sequencing 091 and 097 first means one corpus re-run serves all three fixes
instead of splitting across multiple, and 094's eligibility redesign runs against the
already-corrected CI and return-target measurement rather than the old one. Do not reorder
without re-confirming with the project owner.

## P1 — High value, quick, fully unblocked

| Todo | Why now |
|---|---|
| [093](pending/093-alpha-frames-backfill.md) | **Backfill+scoring done as of 2026-07-12** (11.8M frames, 2.64M scored, verified live via psql) — the one remaining step, `CounterfactualTracker --evaluate-gate`'s FRAME-04 verdict, was explicitly deferred at 142B ship time and still hasn't been run; it's read-only and safe to run any time, independent of the in-flight 143.1-07 corpus re-run |
| [096](pending/096-frame-hold-horizon-vs-feature-lookahead-mismatch.md) | Check whether frame `max_hold_bars` is commensurate with the `lookahead_bars` each feature's IC was actually selected at — could independently explain todo 093's 77%-timeout pattern; read-only, can run in parallel with everything else |
| [095](pending/095-migrations-directory-split-collision.md) | `db/migrations/` vs `production/migrations/` — 3 docs claim the former is canonical, reality is the opposite (213 files vs 3, latter stale 34+ days); confirmed migration-number collisions (120/121); fresh `infrastructure_db_setup.sh` run likely fails on a raw pg_dump snapshot colliding with 213 already-applied incremental migrations |
| [068](pending/068-canary-predictors-integrity-check.md) | Cheapest integrity purchase available — negative-control predictors, zero new services, gate: none |
| [065](pending/065-emission-layer-calibration-proposals.md) | EM-CAL threshold calibration — both prerequisite gates (rebuild, EIC-04) cleared 2026-07-09 |
| [072](pending/072-crowding-proxy-regression.md) | Alpha overlap with public-factor signals — runs against data that exists today, no dependency |
| [084](pending/084-ablation-protocol-ensemble-degradation.md) | Pre-committed ablation protocol — buildable now against existing tables, no new schema |
| [079](pending/079-anytime-valid-e-values-corpus-reruns.md) | Anytime-valid inference pilot (one tf) — new statistical primitive, deliberately staged small |
| [080](pending/080-ensemble-combination-e-candidates-queue.md) | Posterior-blended weighting (L5-1) — testable now via existing A/B judge, zero new data |
| [090](pending/090-ic-decomposition-hit-rate-magnitude.md) | Hit-rate × magnitude decomposition — cheap diagnostic columns, no gate change |
| [097](pending/097-vol-normalized-return-target-pooled-ic.md) | Vol-normalized return target for POOLED-strata IC — split from todo 077's L3-1, 2026-07-11; folded into Phase 143.1 (Component F) as an explicit A/B, not a silent swap |
| [092](pending/092-equity-regime-model-threshold-calibration.md) | Empirical threshold calibration for regime-model vix/breadth cuts — flagged 2026-07-09 as a live-path suspect behind the extreme regime-conditional IC values on the current leaderboard |
| [058](pending/058-concept-registry-mvp-seed-ensemble-strategy.md) | Concept registry MVP — build trigger already fired (Phase 142B.1 complete) |
| [054](pending/054-shadow-alpha-events-monitoring.md) | Shadow alpha_events monitoring — prevents delayed detection of feature decay/threshold bugs |
| [011](pending/011-alpha-events-is-shadow-column.md) | `is_shadow` column — promotion gate can't be retroactively softened once this lands |

## P2 — Real value, not urgent

| Todo | What |
|---|---|
| [005](pending/005-ic-regime-transition-purge.md) | Purge regime-transition label noise from IC measurement |
| [033](pending/033-zero-ic-feature-refinement.md) | Refine remaining zero-IC features (rerun gate now cleared) |
| [038](pending/038-cross-sectional-collinearity-diagnostic.md) | Cross-sectional feature collinearity diagnostic vs IC |
| [039](pending/039-tag-stratified-ic-population-check.md) | Population-count check before tag-stratified cross-sectional IC |
| [081](pending/081-emission-meta-labeling-and-conviction-cross-ref.md) | Emission meta-labeling gate — check overlap with 065/EM-HYST before building |
| [086](pending/086-hmm-test-coverage-gaps.md) | HMM regime-writer test coverage gaps (occupation gate, smooth-check false positive) |
| [088](pending/088-hold-max-bars-censoring-not-tracked.md) | `hold_max_bars` calibration doesn't distinguish confirmed decay from censored data |
| [089](pending/089-ensemble-ic-engine-recurring-cadence.md) | No recurring `ensemble_ic_engine` schedule exists — IC-decay trigger input can go stale |
| [087](pending/087-shared-chunked-cursor-helper.md) | Shared chunked-cursor-to-numpy helper — now a 4th hand-rolled copy exists (today's pilot-script fix) |
| [012](pending/012-structural-compliance.md) | APR compliance sweep — promote batch scripts to proper `BaseBatch` classes |
| [029](pending/029-feature-scoring-beyond-ic.md) | Feature scoring beyond IC (near-term derived metrics) |
| [050](pending/050-ibkr-apr-migration.md) | Migrate `ibkr.py` hardcoded constants to APR |
| [052](pending/052-adversarial-data-error-hunt.md) | Adversarial data-error hunt batch job |
| [053](pending/053-oos-look-log-audit-trail.md) | OOS-look audit trail log |
| [042](pending/042-15m-chunk-size-retest.md) | Re-test 15m backfill chunk size (likely too conservative) |
| [024](pending/024-feature-decay-observatory.md) | Feature decay/crowding observatory dashboard |

## P3 — Hygiene, docs, process (opportunistic)

| Todo | What |
|---|---|
| [056](pending/056-phase146-147-v2x-retirement-stale.md) | Phase 146/147 gate definitions stale — needs an operator call (archive vs delete v2.x) before those phases are planned |
| [057](pending/057-doc-crossref-phase-renumbering-sweep.md) | 10 idea docs still reference pre-2026-07-04 phase numbers |
| [009](pending/009-service-utils-ic-engine-cleanup.md) | `service_utils`/`ic_engine` shared-code cleanup |
| [032](pending/032-ic-engine-pure-function-refactor.md) | `ic_engine.py` pure-function refactor |
| [035](pending/035-market-ohlcv-active-bars-view.md) | `market_data_ohlcv` active-bars filter belongs at one boundary, not 4 call sites |
| [064](pending/064-indicagent-test-db-schema-sync.md) | Test DB schema sync — unblocks integration tests needing a live-migrated schema |
| [059](pending/059-review-aegisagent-tradeagent-for-trade-construction-reuse.md) | Review AegisAgent/TradeAgent for v4.0 trade-construction reuse |
| [060](pending/060-review-cluster2-legacy-intelligence-backlog.md) | Review legacy intelligence backlog docs — salvage or clear |
| [063](pending/063-roadmap-altdata01-two-shape-update.md) | ROADMAP Phase 154 doc-sync (15 min) |
| [085](pending/085-adversarial-review-cadence.md) | Adopt adversarial review as a recurring practice (process, not code) |
| [022](pending/022-bi-superset.md) | Self-service BI (Superset) for ad-hoc analytics |
| [100](pending/100-staged-validation-gate-should-split-bound-by-is-pooled.md) | Filed 2026-07-11 (ledger E10) — future staged-validation gates of this shape should pre-commit separate SUSPECT bounds for capital-relevant vs diagnostic-only strata, not one pooled total. Design fix for next time, not urgent (E10 already resolved the one live incident manually). |

---

**Not in this list:** anything in `deferred/` (phase-gated or corpus-rerun-batched) or
`completed/` (done). Check those folders directly for that work.
