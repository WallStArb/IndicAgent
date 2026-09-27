# Roadmap: IndicAgent

Full history (every shipped, parked and superseded phase's detail, as of 2026-09-26) is in
`.planning/milestones/v3.4-ROADMAP.md`; milestone summaries in `.planning/MILESTONES.md`.
Phase numbers are stable IDs.

## Milestones

- ✅ **v1.0 MVP** — Phases 0-9 (shipped 2026-02-28)
- ✅ **v1.1 Code Quality Sprint** — Phase 01 (shipped 2026-03-01)
- ✅ **v1.2 Intelligence Palette Expansion** — Phases 02-07 (shipped 2026-03-02)
- ✅ **v1.3 Signal Intelligence Expansion** — Phases 08-11 (shipped 2026-03-04)
- ✅ **v1.4 Quant Foundation** — Phases 12-17 (shipped 2026-03-07)
- ✅ **v1.5 Production Hardening** — Phases 18-22 (shipped 2026-03-10)
- ✅ **v1.6 Signal Quality** — Phases 23-24 (shipped 2026-03-10)
- ✅ **v1.7 Data Integrity** — Phases 25-27 (shipped 2026-03-12)
- ✅ **v1.8 Signal Intelligence** — Phases 28-29 (shipped 2026-03-13)
- ✅ **v1.9 I7 Alpha Engine** — Phases 31-38 (shipped 2026-03-18)
- ✅ **v2.0 Signal Integrity & ML Foundation** — Phases 39-47 (shipped 2026-03-22)
- ✅ **v2.1 Data Foundation & Signal Confidence** — Phases 48-52.8 (shipped 2026-03-28)
- ✅ **v2.2 Operational Excellence** — Phases 53.1–58, 60–63 (shipped 2026-04-08)
- ✅ **v2.3 ML Foundation** — Phases 64, 65, 66 (shipped 2026-05-14; Phase 64 03C USD strength deferred)
- ✅ **v2.4 Observability Hardening** — Phases 67–68 (shipped 2026-04-23)
- ✅ **v2.5 Data Quality & Intelligence Completion** — Phases 69–83 (shipped 2026-05-16; all 15 phases complete including 70, 80, 81, 82, 83)
- ✅ **v2.6 Foundation Hardening & Signal Transform** — Phases 084–092 (shipped 2026-05-20)
- ✅ **v2.7 Mathematical Correctness, Storage & Hardening** — Phases 093, 100, 100.5, 104-109 (shipped 2026-05-29)
- ✅ **v2.8 AI Platform — Part 1** — Phases 094-095, 106-108, 110-116 (shipped 2026-06-08)
- ✅ **v2.9 Signal Quality Renaissance** — Phases 117-122 (shipped 2026-06-13; 5.18M noise signals deleted, 21 setups refactored, param store wired)
- ✅ **v2.10 Data Architecture Evolution** — Phases 123-136 (SHIPPED 2026-06-20; ECL + APR + signal hardening + clean replay + 3-table migration + type safety + post-reboot repair)
- ✅ **v3.0 Intelligence Vectors — AlphaEngine** — Phases 137-140 (SHIPPED 2026-06-25; Feature Factory + IC Engine + Ensemble + Alpha Emission + IC Engine Correctness; full corpus run underway)
- ✅ **v3.1 AlphaEngine Validation + Alpha Scoring** — Phases 140.5-173 (shipped 2026-09-02; archive `.planning/milestones/v3.1-phases/`)
- ✅ **v3.4 Edge Proof** — Phases 174-182 (closed 2026-09-26; 178, 182 complete; 179 and 181 verdicts FAIL; 177 and 180 superseded; archive `.planning/milestones/v3.4-phases/`)
- 🔄 **v3.5 Unified Research Pipeline** — Phases 183-188 (opened 2026-09-26; `docs/plans/2026-09-26-unified-research-to-production-design.md`, adopted with E18)
- ⏸️ **v2.8 AI Platform — Part 2** — Phases 096-099, 101-103 (unblocked; deprioritized until v3.0 validated)
- ⏸️ **Parked** — 145 (v3.15), 149-151 waves 6-7 (v3.2), 152-153 (v4.1), 155, 168, 169; v4.0 156-159 re-scoped into phase 188 (see below)

## Active milestone: v3.5 Unified Research Pipeline

Sequence and rationale: `docs/plans/2026-09-26-unified-research-to-production-design.md` section 16
(the single owner of sequence). Research attempts run in parallel with the build and never queue
behind infrastructure; the alpha track (todos 442, 437, 441, 423, 440) runs first. STATE.md holds
current position only; PRIORITIES.md tiers todos.

| Order | Phase | Lever | Status |
|---|---|---|---|
| 1 | 183 Research layer: runner, ledger, combiner, book test | Spec-as-pre-registration runner, S6 ledger, S7 combiner, S8 book test; every real-data number recorded | All 11 plans done (plan 10 2026-09-26); phase verification pending; E17 precondition built (todo 447, 2026-09-27); attempts (442) continue in this lane |
| 2 | 185 Daily data foundation | Raw IBKR observations kept apart from derived daily bars; scrubbing with validated rules (flag, never delete); venue-move recovery (433); splits and dividends point in time. IBKR-only. Clears the data bar for daily attempts | Accepted 2026-09-26, not planned |
| 3 | 186 Old ensemble chain retirement and ic_engine re-scope | Delete the old chain; summarize then drop dead tables (174 GB to about 60 GB); rebuild `feature_vectors`; refactor map items 1-6 | Not planned; no live ic_engine run |
| 4 | 187 Research core: recipe book, selection, construction | UCR recipe book, StepM selection (E18), construction rules, pod books, costed horizon rule, `generated_family`, DAG manifest, per-writer DB roles | Not planned; waits on family 2's evidence run (183 plan 10 done) |
| 5 | 184 Multi-timeframe research inputs | Causal alignment node; S0 reads `feature_vectors` (revised by 435); prerequisite for feature books | Not planned; waits on 183 |
| 6 | 188 Forward runner and capital tier | `BookTracker`, sealed shadow, full cost model, `portfolio_state` and sizing (re-scoped 156-157) | Not planned; waits on a candidate book |

## Parked

One line each; full detail in `.planning/milestones/v3.4-ROADMAP.md`.

- **145** StratificationDimension formalization: not prioritized; regimes are disclosure and state variables under the unified design.
- **147** I7 CORPUS-07 evaluation: v2.x, archived under the dual intelligence-path plan.
- **149, 150** PrecedentEngine: re-scoped 2026-09-26, precedent predictors enter books as family members.
- **151 waves 6-7** interaction IC sweep: superseded by `interaction_family` and the feature rebuild.
- **152, 153** IC governance and drift monitoring: superseded by per-member monitoring and the decay alarm (phase 188).
- **155** Alternative data vectors: gated on data sources (IBKR-only for now).
- **156, 157** Portfolio state and sizing: folded into phase 188.
- **158, 159** Live execution and fill-calibrated costs: interface only until a book passes forward confirmation.
- **168** Cost-hurdle-adjusted spread construction: blocked (no live construction left to refine).
- **169** Symbol state query layer: design only; needs a live-verification refresh before planning.
- **170 plans 07-08** `feature_registry` retirement: finished inside phase 186.

## Phases

### Phase 183: Research layer: runner, ledger, combiner, book test

**Goal:** No real-data research number exists outside a recorded, reproducible run. Build
steps 4-6 of `docs/plans/2026-09-25-alpha-research-architecture.md` on the package already on
main (`src/intelligence/research/`: panel, snapshot, signals, evaluate, factors, guards): (4) a
runner that refuses a real-data run unless the candidate spec is committed and unrun, writes a
`started` ledger row before computing, runs S3 guards and `require_testable`, and records spec,
snapshot and code hashes; (5) the S6 ledger writer, sole writer of
`concept_registry(domain='construction')` evidence records and the vintage budget (M = 30,
evidence framework E15); (6) the S7 walk-forward ridge combiner over every registered family
member and the S8 book test (joint whole-session shift of the signal stack, combiner refit per
shift), budget-charged. Family 1's first real-data run waits for (4) and (5).
**Requirements**: D-01 through D-29 (D-26 to D-29: E16 adoption)
**Depends on:** none (steps 1-3 on main)
**Plans:** 10 plans in 5 waves

Plans:

- [x] 183-01-PLAN.md - R1 rank-vol-neutral construction and R2 session scoring (wave 1)
- [x] 183-02-PLAN.md - migration 366 research_run ledger, APR budget keys, ledger.py sole writer (wave 1)
- [x] 183-03-PLAN.md - spec schema and canonical hash, git provenance refusals (wave 1)
- [x] 183-04-PLAN.md - S7 walk-forward ridge and exact power-decision primitives (wave 1)
- [x] 183-05-PLAN.md - family 1 members P1-P4, array guard probes (wave 1)
- [x] 183-06-PLAN.md - S8 book test with per-shift combiner refit (wave 2; refit null superseded by 183-11)
- [x] 183-07-PLAN.md - runner evidence mode, evidence records, CLI, family 1 spec (wave 2)
- [x] 183-08-PLAN.md - residual-space synthetic generator and exact power estimator (wave 3)
- [x] 183-09-PLAN.md - runner book mode, book v1 spec, full-size synthetic dry run (wave 4)
- [x] 183-10-PLAN.md - first real-data run: family 1 evidence, then book v1 (wave 5; evidence completed, book v1 refused uncharged; summary 02b021ae3)
- [x] 183-11 (no PLAN.md; owner decision executed inline) - E16 adopted and built: HAC timing t decides, shift null diagnostic, power through the same statistic (183-11-SUMMARY.md)

### Phase 184: Multi-timeframe research inputs

**Revised 2026-09-26 (todos 435, 436, 446; unified design UD-25):** scope follows revision 3 of
the multi-timeframe design. The 5m aggregation moved to phase 185, the kernel table is phase
186's registry, S0 reads the rebuilt `feature_vectors`, and the IC term structure is computed by
the shrunk ic_engine.

**Goal:** Predictors computed on any timeframe can enter a book on one clock without a lookahead,
a filled value or a second implementation of a feature. Build section 7 of
`docs/plans/2026-09-25-multi-timeframe-horizon-design.md` (revision 3): B1 S0 adds `high`, `low`
and `closes_at` (NaT on untraded rows), fetches a warmup prefix, and reads phase 185's derived 15m
and 1h bars; B2 new registry entries (vectorized percentile and 52-week, rolling VWAP) and a
`kernel_source` adapter on phase 186's kernel registry; B3 the causal `align` node with its
guards (prerequisite for feature books); B4 disclosure of the shrunk ic_engine's IC term
structure as a run record that feeds nothing, kappa included; B5 the fixed smoothing menu
(half-lives 5, 21, 63 sessions); B6 the E16 book test holds size on synthetic persistent
predictors; B7 `repro_frozen.py` bit-identical after each item.
**Requirements**: TBD
**Depends on:** Phase 183 (runner, S7, S8), E16 (adopted in the phase 183 session), phase 185's
derived 15m and 1h grid (B1), phase 186's kernel registry and shrunk ic_engine (B2, B4). Daily books
with price-level members declare `panel.total_return` (todo 428, closed 2026-09-26).
**Plans:** 0 plans

Plans:

- [ ] TBD (run /gsd-plan-phase 184 to break down)

### Phase 185: Daily data foundation

**Goal:** Every daily bar research reads traces to raw IBKR observations and a versioned
derivation rule, and no data defect reaches a verdict unmeasured. Build stages D0-D7 of
`docs/plans/2026-09-26-daily-data-foundation.md` (accepted 2026-09-26): D0 bound each verdict's
exposure to venue truncation, missing dividends and survivorship; D1 an append-only 1d
observation store (every route and request type); D2 derived 1d bars written to
`market_data_ohlcv` by the derivation alone; D3 venue-move recovery for 1d and intraday (todo
433), stored only after a listing-venue validation study passes; D4 empty history recorded only
when every route answers "no data"; D5 splits detected from re-fetch overlaps and dividends from
ADJUSTED_LAST against TRADES, point in time, as the independent check on Yahoo's dividends; D6 listing-venue history; D7 daily reconciliation of
SMART against venue, TRADES against ADJUSTED_LAST, daily against aggregated intraday. D8 (forward
survivorship capture) was descoped by the owner 2026-09-26.
IBKR-only: no new data sources (owner, 2026-09-26), except Yahoo's dividend history kept as
reference data (todo 428); the vendor stage stays gated. Revision 2
(2026-09-26, aligned with the unified design): D0 becomes data-quality labels on every attempt
(old verdicts are summary cards, not re-run); D2a scrubbing inside the derivation (flag, never
delete; rules validated on known answers; one historical batch pass folding todos 155, 347, 052);
revisions propagate through content-digest keys; daily
attempts 3, 3b and 4 wait on the minimum data bar (seam audit, scrubbing pass, moved names,
total returns, survivorship bound). D2a reuses the existing price-sanity classifier as one scrubbing
rule; D2a and D7 are the price-integrity layer (no existing service checks historical price
correctness). Order: the
1d re-run for the 384 late-starting names, the D3 study, the seam audit and the D2a pass, none of
which needs D1. D2a's known-answer set includes the 2026-09-26 1d dry run (45 unflagged corrupt
bars; the classifier's cross-symbol corroboration clears Flash Crash stub prints). D2a closes the onboarding
SOP's second gap (scrubbing in the chain).
UD-25 (unified design 14.7, todo 446): D2 also derives 15m and 1h bars from 5m on
session-anchored edges (stored 1h drops the 09:30-10:00 half hour on 39 names, SPY included),
landing before phase 186's `feature_vectors` rebuild; D2a takes over `forward_return_writer`'s
suspect, corroboration and gap flags as flags on bars.
**Requirements**: TBD
**Depends on:** none to start. D3's intraday recovery goes in through a planned corpus
recompute, never under a live ic_engine run (Phase 178's worktree).
**Plans:** 0 plans

Plans:

- [ ] TBD (run /gsd-plan-phase 185 to break down)

### Phase 186: Old ensemble chain retirement and ic_engine re-scope

**Goal:** One route from research to capital. Track A of
`docs/plans/2026-09-26-unified-research-to-production-design.md` (adopted 2026-09-26, sections 11
and 14): delete `ensemble_trainer`, `ensemble_ic_engine`, `alpha_frame_writer`,
`counterfactual_tracker`, the old-chain ops scripts, the phase 179 harness plumbing and the
orchestrator steps after `feature_lifecycle`; write summary cards for every old verdict and
dead process, then drop `ensemble_weights`, `ensemble_alpha`, `alpha_ensemble_ic`, `alpha_events`,
`alpha_frames`, `context_features` and `feature_ic_scores_history` (design section 14.2, amended
2026-09-26: raw data permanent, derived data is cache, conclusions are records); rebuild
`feature_vectors` as a new append-only table with provenance instead of refreshing it in place; shrink ic_engine to the proposer, IC term structure and
member monitoring, purging IC targets that cross `oos_start`; move feature lifecycle to
data-quality gates; database hygiene from the 2026-09-26 best-practices audit (design section
14.5): new writers (shrunk ic_engine, the `feature_vectors` rebuild) load with `COPY` in chunk
order instead of row-at-a-time inserts, drop the duplicate `market_regimes` index (387 MB, same
key as the unused PK), primary keys on every surviving table, and a measured `shared_buffers` and
`work_mem` review under the performance-investigation SOP; the fresh ic_engine's uniqueness key includes scope explicitly (todo 391); one target kernel
(UD-25, design 14.7): the shrunk ic_engine computes targets with `panel.forward_returns` on S0
panels (in symbol chunks), intraday horizons inside one session, and once it reaches parity on
pooled cells `forward_return_writer`, the `forward_returns` table, the fixed
`alpha.ic.lookahead.*` keys and the scripts reading the table are deleted in one change; the
`feature_vectors` rebuild runs on phase 185's derived 15m and 1h grid, never before it; refactor map items 1-6 (design section 14.6): `feature_factory` split into
per-origin modules behind one kernel registry, the shrunk ic_engine written fresh beside the old
one to parity, one `COPY`-based bulk-load primitive in `_batch_utils` (absorbs todos 301, 343,
352), the batch feature path as the rebuild writer, `regime_writer` walk-forward only (290, 291),
lifecycle as data-quality checks; before the rebuild is specified, decide its timeframe set: 5m
holds about 69% of `feature_vectors` rows and no active family reads 5m features, so run the
5m-over-15m incremental IC test at matched horizons first (todo 445, design section 14.2); delete `scripts/analysis/` after summary cards and helper
promotion; consumer checks for `context_writer` (unit active) and
`cross_sectional_spread_tracker`; finish phase 170's `feature_registry` retirement without the
ensemble rehearsal.
**Requirements**: TBD
**Depends on:** no live or resumable ic_engine run (import rule); phase 183 not touching these
modules; the `feature_vectors` rebuild step also on phase 185's derived 15m and 1h grid (UD-25)
and todo 445's timeframe decision.
**Plans:** 0 plans

Plans:

- [ ] TBD (run /gsd-plan-phase 186 to break down)

### Phase 187: Research core: recipe book, selection, construction

**Goal:** Every look at the vintage is recorded and priced, and every book tests the construction
that will trade. Track C of the unified design (sections 4, 6.1, 7, 10, 13, 15): UCR recipe book
(typed domains, append-only `concept_recipe`, attempts with typed results and `informed_by`,
derived research stage, legacy verdict import, generated ledger); runner `exploration` mode and
Romano-Wolf StepM selection (E18); `ConstructionRule` protocol, pod books, costed horizon rule,
the missing-member combining rule, in-fold signs, calendar-anchored refits; `generated_family`
grammar support; contribution accounting with accounting groups; YAML DAG manifest; research
package renames with todo 430 step 4; one database login role per writer with write grants only
on its own tables and read-only roles for readers, generated from the DAG manifest, so
`single_writer` is enforced by the database (services connect as the `postgres` superuser today);
refactor map items 7-8 (design section 14.6): `service_auditor` and the orchestrator read the DAG
manifest, research package split behind the three protocols; an auditor inventory in the DAG manifest (each auditor either live with an owner and an action,
or archived: the v2.x auditors are archived under the dual intelligence-path decision, and
`bar_auditor`'s gap detection returns only with streaming); indexes on every foreign key in the clean UCR schema (`concept_registry.parent_concept_id`,
`research_run.concept_id`, `instrument_classification.scheme` lack them today).
**Requirements**: TBD
**Depends on:** phase 183 plan 10 and family 2 finished (research package free). Until it lands,
the phase 183 runner's M = 30 accounting stays in force.
**Plans:** 0 plans

Plans:

- [ ] TBD (run /gsd-plan-phase 187 to break down)

### Phase 188: Forward runner and capital tier

**Goal:** A frozen book runs forward on the same code that tested it, and capital is sized on
measured net. Track E of the unified design (sections 3, 7.3, 8, 9): `BookTracker` and
`BookPositionWriter` (replacing `alpha_publisher`), sealed shadow for every book in the selection
set, append-only positions with revision alarms, positions parity with research; full cost model
(impact, borrow constraint, capacity curve, implementation shortfall); `portfolio_state`, sizing
and risk limits (re-scoped phases 156-157); challenger protocol with a paired test.
**Requirements**: TBD
**Depends on:** a candidate book in the selection set; todo 438's borrow snapshots running before
any forward span starts.
**Plans:** 0 plans

Plans:

- [ ] TBD (run /gsd-plan-phase 188 to break down)
