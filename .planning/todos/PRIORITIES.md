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
| [091](pending/091-fisher-z-ci-empirical-null-miscalibration.md) | Fisher-z analytic CI empirically miscalibrated — 38% SUSPECT rate across strata; this is the exact mechanism behind every BH-FDR/EIC-04 gate in the stack |
| [051](pending/051-backfill-silent-skip-on-ibkr-disconnect.md) | Backfill script silently completes despite mass symbol skip on IBKR disconnect — no reconnect-to-IBKR path |
| [061](pending/061-feature-vector-pipeline-ddl-in-hot-path.md) | `feature_vector_pipeline` does DDL in its hot path — violates DAG Invariant 2/3 (compute must never own schema mutation) |
| [044](pending/044-tempo-crashloop-config-schema.md) | `indicagent-tempo` container permanently crash-looping on stale config schema |

## P1 — High value, quick, fully unblocked

| Todo | Why now |
|---|---|
| [093](pending/093-alpha-frames-backfill.md) | `alpha_frames` backfill — Phase 142B's writer/tracker shipped but the table still has 0 rows; the standing concrete next step, not gated on anything |
| [068](pending/068-canary-predictors-integrity-check.md) | Cheapest integrity purchase available — negative-control predictors, zero new services, gate: none |
| [065](pending/065-emission-layer-calibration-proposals.md) | EM-CAL threshold calibration — both prerequisite gates (rebuild, EIC-04) cleared 2026-07-09 |
| [072](pending/072-crowding-proxy-regression.md) | Alpha overlap with public-factor signals — runs against data that exists today, no dependency |
| [084](pending/084-ablation-protocol-ensemble-degradation.md) | Pre-committed ablation protocol — buildable now against existing tables, no new schema |
| [079](pending/079-anytime-valid-e-values-corpus-reruns.md) | Anytime-valid inference pilot (one tf) — new statistical primitive, deliberately staged small |
| [080](pending/080-ensemble-combination-e-candidates-queue.md) | Posterior-blended weighting (L5-1) — testable now via existing A/B judge, zero new data |
| [090](pending/090-ic-decomposition-hit-rate-magnitude.md) | Hit-rate × magnitude decomposition — cheap diagnostic columns, no gate change |
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

---

**Not in this list:** anything in `deferred/` (phase-gated or corpus-rerun-batched) or
`completed/` (done). Check those folders directly for that work.
