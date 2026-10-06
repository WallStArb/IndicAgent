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
(the single owner of sequence), superseded on one point by the owner 2026-09-27: build first.
Research attempts (todos 442, 437, 441, 423, 440) are paused until 185 and 186 land, and session
time goes to the build. STATE.md holds current position only; PRIORITIES.md tiers todos.

| Order | Phase | Lever | Status |
|---|---|---|---|
| 1 | 183 Research layer: runner, ledger, combiner, book test | Spec-as-pre-registration runner, S6 ledger, S7 combiner, S8 book test; every real-data number recorded | All 11 plans done (plan 10 2026-09-26); phase verification pending; E17 precondition built (todo 447, 2026-09-27); attempts (442) continue in this lane |
| 2 | 185 Daily data foundation | Raw IBKR observations kept apart from derived daily bars; scrubbing with validated rules (flag, never delete); venue-move recovery (433); splits and dividends point in time. Tradier is the primary 1d source from 2026-10-03 (IBKR serves intraday and the names Tradier cannot). Clears the data bar for daily attempts | Planned 2026-09-27, plan 25 added 2026-10-03: 26 plans in 12 waves; plan-checker passed (`959ec85ea`) before plan 25; ready to execute |
| 3 | 186 Old ensemble chain retirement and ic_engine re-scope | Delete the old chain; summarize then drop dead tables (174 GB to about 60 GB); rebuild `feature_vectors`; refactor map items 1-6 | Planned 2026-09-27: 29 plans written; plan-checker pass in progress (186 session); no live ic_engine run |
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
- **170 plans 07-08** `feature_registry` retirement: migration 311 finished it on 2026-08-10; phase 186 plan 09 removed the residue (the parity verifier script and stale references).

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
B8 (added 2026-10-01): economic series (`economic_series_observation`, todo 480) enter S0 through the
same causal alignment, joined on decision time with an age and a maximum age, captured by a knowledge
cutoff in the panel manifest, and every book using them passes the one-session shift test
(`docs/ideas/signal-macro-context-layer.md`); needs todo 482 first.
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
**Depends on:** none to start. Intraday venue recovery is stored only after phase 186's rebuild,
through content-digest keys, never under a live or resumable ic_engine or rebuild run (D-19, 186 D-32).
Every IBKR history fetch holds one stream lease (D-29, todo 449's single-stream finding).
**Plans:** 26/35 plans executed (27 to 35 close the 2026-10-06 verification gaps)

Plans:

**Wave 1**

- [x] 185-01-PLAN.md - known-answer fixtures, test scaffolding, write-rate and role measurements (wave 1)
- [x] 185-02-PLAN.md - D1 observation store, roles, COPY writer (wave 1)
- [x] 185-03-PLAN.md - provider request records and venue observations (wave 1)
- [x] 185-04-PLAN.md - bar_quality_flag, quarantine view, scrub APR, batch helper (wave 1)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 185-05-PLAN.md - D2a pure scrub rules on known answers (wave 2)
- [x] 185-06-PLAN.md - session grid aggregation and bar content digest (wave 2)
- [x] 185-07-PLAN.md - seams, splits, disputed dates, D3 study pre-registration (wave 2)
- [x] 185-08-PLAN.md - D0 label arithmetic and survivorship APR (wave 2)
- [x] 185-09-PLAN.md - D1 capture in the backfill; IBKR history-stream lease replacing the nightly skip; chain cut-over (wave 2)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 185-10-PLAN.md - historical scrub pass over 1d and 5m (wave 3)
- [x] 185-11-PLAN.md - D2b writer, archive, digest table, single-writer CI (wave 3)
- [x] 185-13-PLAN.md - D3 venue validation study and verdict (wave 3)
- [x] 185-14-PLAN.md - 1d head re-run and moved-name inventory (wave 3)

**Wave 4** *(185-15 blocked on Wave 3 completion; 185-12 gated only on 09-11, its `depends_on`: 13 and 14 may run in parallel, D-15 needs neither)*

- [x] 185-12-PLAN.md - D2b live rewrite, write-path switch, single archive writer, 186 precondition (wave 4)
- [x] 185-15-PLAN.md - D1 bootstrap and split-seam audit (wave 4)

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 185-16-PLAN.md - D-28 data bar check, D0 read helper, S0 hand-off (wave 5)
- [x] 185-17-PLAN.md - D2 1d derivation rule and stage, dry run (wave 5)
- [x] 185-21-PLAN.md - D5 IBKR dividend route from D1, date disputes (wave 5)

**Wave 6** *(blocked on Wave 5 completion)*

- [x] 185-18-PLAN.md - D2 sole 1d writer and historical apply (wave 6)

**Wave 7** *(blocked on Wave 6 completion)*

- [x] 185-19-PLAN.md - D3 rebase and D4 from recorded answers, 1d (wave 7)

**Wave 8** *(blocked on Wave 7 completion)*

- [x] 185-20-PLAN.md - intraday verify-only, empty history, gated recovery (wave 8)
- [x] 185-22-PLAN.md - D5 nightly overlap split detection (wave 8)

**Wave 9** *(blocked on Wave 8 completion)*

- [x] 185-23-PLAN.md - D7 nightly reconciliation audit (wave 9)

**Wave 10** *(blocked on Wave 9 completion)*

- [x] 185-25-PLAN.md - rebuild market_data_ohlcv from real rows, drop the synthetic fill (wave 10)

**Wave 11** *(blocked on Wave 10 completion)*

- [x] 185-26-PLAN.md - nightly Tradier 1d leg and the Tradier-owned skip (wave 11)

**Wave 12** *(blocked on Wave 11 completion)*

- [x] 185-24-PLAN.md - D6 listing venue, docs and todo close-out (wave 12)

**Gap closure** *(185-VERIFICATION.md, 2026-10-06; waves 13 to 16)*

Exit notes: success criterion 8 (reopened ideas re-evaluated on canonical bars) is an obligation on
the first reopened idea, not a 185 deliverable (owner, 2026-10-06). D0's S0 application
(`185-S0-HANDOFF.md`) belongs to the phase 183 research lane through the todo 185-29 files, ranked
in front of daily attempts 3, 3b and 4; D-04 stays unmet at close and re-verification records an
explicit override for it.

**Wave 13**

- [x] 185-27-PLAN.md - Tradier write path: tradier-v1 lineage to D1, new-and-changed-only writes to D1 and market_data_ohlcv, scrub and digests in the loader, lineage/digest writer boundary (wave 13)
- [ ] 185-29-PLAN.md - D0 label inputs name both rules; S0 hand-off todo for the research lane; owner answers and orchestrator calls recorded apart (wave 13)

**Wave 14** *(blocked on Wave 13 completion)*

- [ ] 185-28-PLAN.md - IBKR-only venue view, 7 IBKR-sourced late names re-asked, 6 contradicted empty-history rows reconciled (wave 14)
- [ ] 185-30-PLAN.md - lineage for 1,266 Tradier-owned names, digests for every canonical 1d name, 31 untraced IBKR bars re-asked, replaced 1d legacy flags retired (wave 14)
- [ ] 185-31-PLAN.md - todo 490: intraday raw revision table, value-match archive verify, 7 grid symbols derived (861,047 rows) (wave 14)

**Wave 15** *(blocked on Wave 14 completion)*

- [ ] 185-32-PLAN.md - alignment sweep: fill paths removed or fenced, no-synthetic DB guard and AST CI test, provider matrix (wave 15)
- [ ] 185-33-PLAN.md - D7 lineage, digest, untraced-quarantined and mixed-source checks; content-aware check_d2_landed (186 file, note in the 186 dir); live D2 test (wave 15)
- [ ] 185-34-PLAN.md - D-28 gate conditions 1, 3 and 4 source-aware (wave 15)

**Wave 16** *(blocked on Wave 15 completion)*

- [ ] 185-35-PLAN.md - nightly timer restarted, first night measured, ETHA checked, closing checks, todo 490 closed (wave 16)

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
**Plans:** 29 plans

Plans:

Plans written 2026-09-27 (`09776c12c`); waves and dependencies in `186-PLAN-OUTLINE.md`.

- [ ] 186-17 Postgres tuning (D-38): Task 1 done (targets and the before baseline, `ce1c9686a`);
  Task 2 (recreate the container with the tuned compose block, then the after measurement and the
  baseline drift check) is refused while a todo 449 lane is live and runs in a lane gap before
  186-26; the compose edit sits uncommitted in the `indicagent-wt/186-17` worktree by design,
  committed in the same step as its apply (`186-17-SUMMARY.md`, PARTIAL)
- [x] 186-23 old IC stack one-change deletion (D-22): `ic_engine.py`, `forward_return_writer`, the
  `forward_returns` table and the fixed `alpha.ic.lookahead.*` keys, orchestrator repointed at
  `ic_measure`; gated on 185 D-14 (the 185-12 Task 2 bar-flag port); the 186-20 parity criterion
  was accepted 2026-10-01; merged 2026-10-02 (`6915ffba4`, migration 430 live-applied, 14 GB freed)
- [ ] 186-26 feature_vectors rebuild run (D-32/D-32a): precondition checker, pilot chunk, R-09 disk
  guard, then the full resumable background run with kill-and-resume proven once; gated on todo 449
  coverage, 185 D2b (185-12) and 185-18's historical 1d D2 apply (todo 489 adds the checker gate), with
  todos 478 and 467 decided first; owns the todo 420 orphan-cleanup rerun
- [ ] 186-27 rebuild close-out and name swap (D-34): unit-by-unit provenance verification, sampled
  drift report, atomic swap to `feature_vectors`, compression policy re-enabled, old 89 GB table
  dropped behind its dead-cache card; closes todos 411 and 426; behind 186-26
- [ ] 186-28 ic_engine re-scope close (D-35): the 186-14 fresh IC writer run on the rebuilt table
  (scopes `unstratified` and `regime_volatility` into `feature_ic_scores_v2`), legacy
  `feature_ic_scores` dropped (R-07), D-19 bound verified on v2; its tf set waits on todo 471's
  measurement
- [x] 186-01 summary cards: card schema, card lint with drop-table coverage, 8 legacy_verdict
  cards, 6 dead_cache cards; lint green, merged 2026-09-27 (`42fb59427`)
- [x] 186-02 ledger verdict cards: 18 legacy_verdict cards for the construction verdict ledger
  section 4 rows (5 marked reopened), one pointer paragraph in the ledger with section 4 rows
  byte-identical; card lint green over 32 cards with git checks active; merged 2026-09-29
  (`54a684e4e`)
- [x] 186-03 determinism tool promotion: `repro_frozen` promoted to
  `scripts/research/determinism/` (remapping unpickler, no old-chain imports), bit-identical on
  phase 179 S3 and phase 181 S2/S3 with the shim module blocked; todo 448 item 1 noted; merged
  2026-09-28 (`c3ce3a9d7`)
- [x] 186-04 helper promotion: compute-eligibility audit to scripts/infrastructure (onboarding
  promote step and APR test repointed), date panel + pre-registered cost band + two-pass
  feature-matrix fetch to scripts/research/ (forward_returns join dropped, caller-supplied keep
  mask); 186-16's scripts/analysis deletion unblocked; merged 2026-09-28 (`70b68f4b9`)
- [x] 186-05 database hygiene: duplicate `market_regimes` index dropped (migrations 384-385;
  EXPLAIN-proofed on the PK), PK inventory for all 11 no-PK tables (7 PKs added,
  `drift_monitor` dropped, `market_data_ohlcv` recorded unique-index equivalent, A1 confirmed),
  D-38 baseline JSON + read-only script committed; work_mem drift cause proven (container
  predates the 64MB compose edit, never recreated); merged 2026-09-28 (`a6dd8ea98`)
- [x] 186-06 bulk-load primitive: `bulk_load()` in `services/_batch_utils.py` (COPY in time
  order, provenance-batch idempotency via the batch_key PK, live-schema float32 clamp,
  compression-policy and compressed-chunk refusals, per-chunk `compress_chunk` with the PK
  kept); migration 386 creates `provenance_batch` (guard/no-delete/no-truncate triggers,
  `infra.bulk_load.*` APR keys); todos 301/343/352 closed; merged 2026-09-28 (`843a645b9`)
- [x] 186-07 todo445 5m-over-15m incremental IC: committed counted-look script
  (`scripts/research/todo445_5m_incremental_ic.py`, server-side-cursor streaming DB fetch after
  two live memory incidents); decision keep_5m, rebuild timeframes 15m/1h/1d/5m, 5m name set
  ret_autocorr_1 and sweep_detected at the 233 compute_eligible names; todo 445 closed; merged
  2026-09-28 (`0b4edf3a7`)
- [x] 186-08 kernel registry, causality probe and golden parity fixture: `discover_kernels()` and
  `feature_memory_bars()` (D-25, D-26) in `src/intelligence/features/contract/registry.py`, truncation
  `causality_probe`/`memory_check` (D-27), frozen float32 golden of the current compute path
  (1 synthetic and 16 real cases) with a byte-identical parity test for 186-12 and 186-15; merged
  2026-09-29 (`70552a710`)
- [x] 186-09 feature_lifecycle shrunk to data-quality checks (D-30): computed, finite and symbol
  coverage above `feature.coverage.min_symbol_fraction`, statistic in
  `src/intelligence/statistics/feature_coverage.py`, no reader of `ensemble_weights` left (R-03),
  migration 387, `feature_registry` residue removed (D-31); merged 2026-09-29 (`02590dbcc`)
- [x] 186-10 measure package: proposer, IC term structure, monitoring and `regime_volatility`
  disclosure as pure functions over `ic_math`, targets from `panel.forward_returns` on chunked S0
  panels ending at `oos_start` (D-17, D-18, D-19); merged 2026-09-29 (`78edf26e5`)
- [x] 186-11 ctx-writer retirement: `indicagent-ctx-writer` uninstalled, `context_writer`, `topic_ctx_snapshot`
  and dead `FeatureRepository` deleted, `ctx_events` and `ctx_snapshots` dropped by migration 388,
  unit deny-listed in the registry-integrity test; merged 2026-09-29 (`79a59913a`)
- [x] 186-12 feature_factory split, first four origins: 117 registry kernels for price, volume, calendar,
  control and macro (D-25, D-26), `compute_batch` and `_precompute_series` read them through
  `compute_kernels`, byte-identical against the 186-08 golden; the probe found two lookaheads, fixed
  with their own golden regenerations: intraday macro records now align as-of the daily close (todo
  450 closed) and `gap_z` no longer reads the next bar's open (todo 461 filed); merged 2026-09-29
  (`10967cd67`)
- [x] 186-13 regime kernels: the walk-forward HMM is four registry kernels (trend and volatility, D-29,
  R-10), byte-identical to the unchanged writer on a captured golden; the full-history path and its
  flags are deleted; the segment gate read future bars (RED tests, todo 451) and now gates on the
  training slice, golden regenerated in its own commit; `regime_writer` is a thin wrapper (todos 290
  and 291), migration 410; todo 248 was already deployed (flag true since 2026-08-12); merged
  2026-09-30 locally (`d754a1c98`, push held by the coordinator)
- [x] 186-16 `scripts/analysis/` deletion (D-12): 94 scripts and 26 test files removed except the sleeve
  `config.py` closure, the pilot-only HMM helpers deleted with them, migration 412 retires two
  unread APR keys; `repro_frozen` (promoted to `scripts.research.determinism`) bit-identical before
  and after; merged 2026-09-30 locally (`299798dc7`, push held by the coordinator)
- [x] 186-15 feature_factory split, last origins: SMC, VP/SR, cross-asset and factor-beta, CTF and ret_div
  are registry kernels (139 kernels, nine origins, D-25), byte-identical against the golden, which was
  never regenerated; the CTF availability tests (written first) found todo 243's re-key causal and
  `compute_batch` accepting any dict, now a close-keyed `CtfSeries` that raises TypeError otherwise;
  the dormant pipeline reads the registry (startup refusal on an unowned column) and its live
  cross-asset lookup uses the batch as-of rule; `cross_asset_series.py` deleted, todo 472 filed;
  merged 2026-09-30 locally (`5fd6d17c6`, push held by the coordinator)
- [x] 186-29 sleeve directory removal (D-03, D-11): the five research tests import `HarnessConfig` from
  `scripts.research.determinism.config` (owner-released lane, one line each), `scripts/analysis/` and
  `tests/unit/sleeve_walk_forward/` deleted; the promoted determinism tool reports phase 179 S3 and
  phase 181 S2/S3 bit-identical on the post-deletion tree; merged 2026-10-01 (`4dddba5b9`)
- [x] 186-22 old-chain table drops (D-14, D-06, D-08, R-01): migration 426 drops ensemble_weights,
  ensemble_alpha, alpha_ensemble_ic, alpha_events, alpha_frames, alpha_strategy_scores, context_features,
  feature_ic_scores_history and construction_spreads (50.7 GB freed, jobs 1067-1070/1072/1073 gone, 1071
  kept); orphaned ops readers and the context_features writer deleted, todo 355 closed; old ic_engine is
  non-runnable until 186-23; merged 2026-10-01 (`772c43823`)
- [x] 186-24 feature_vectors_v2 schema (D-34, D-37, D-16): migration 425 creates the empty rebuilt
  hypertable (312 columns derived from the registry, PK symbol/tf/bar_ts, 1-year chunks, compression
  without a policy); Asian pair kept because the kernel computes it, 5 feature columns dropped by
  counted proof; 186-25 and 186-27 must use 312, not 310; merged 2026-10-01 (`b0124e8cf`)
- [x] 186-21 old-chain ops scripts and APR keys (D-10, D-08): seven ops scripts and four unit files
  deleted; the orchestrator is five steps ending at feature_lifecycle, the monitor and verifier drop
  the dead services; migration 424 retires 51 old-chain APR keys per key (kept: `mv_condition_max`,
  `cluster_regime_conditioned`, `alpha.ic.*`); merged 2026-10-01 (`9b37c754e`)
- [x] 186-20 parity replay of stored pooled cells (D-21, R-06): read-only harness over 1,080 stored
  POOLED cells; row sets reproduce exactly, a legacy-arithmetic replica reproduces 1,078 (2 are float32
  noise in the stored value), every fresh-versus-stored difference is attributed (66 NaN-denominator
  zeros, 68 rank-scope), owner accepted the restated criterion 2026-10-01; writer-path cell equals the
  harness replay; report `186-20-PARITY-REPORT.md` on main; stored rows hold IC 0.0 for features with
  missing values (false negatives only, relayed to the research lane); 186-18's orphan cleanup run is
  unblocked
- [x] 186-19 old-chain deletion (D-09): eight services (ensemble_trainer, ensemble_ic_engine,
  alpha_frame_writer, counterfactual_tracker, alpha_publisher, alpha_scorer, ic discovery report,
  cross_sectional_spread_tracker), `gate_math`, three ensemble modules, two unit files and 34 test
  files removed; `ensemble/` keeps covariance, shrinkage, weights with an import-free init; the five
  units are deny-listed in the registry test; `repro_frozen` bit-identical on merged main; last commit
  holding the code is `2d4c2e4e1`; the two ops scripts and orchestrator steps 7-8 left for 186-21
- [x] 186-18 regime bundle on the kernel: trend obs rows start after the nested vol_of_vol warmup
  (RED test, golden regenerated in its own commit, volatility digests unchanged; todo 286), WR-01
  pinned on both kernel families (292); a read-only coverage sweep decided by pre-registered rules:
  `refit_every_bars.1d` kept at 252 (289; 1d regime_volatility is gated off for 98% of segments at
  every schedule, todo 478 filed) and the five auditor symbols diagnosed, so the auditor fails only on
  unregistered or expired gaps with APR exceptions expiring 2026-12-29 (341, migration 420);
  `cross_sectional_regime_model` replaces each (group, tf) atomically with a shrink guard (420,
  migration 419), cleanup run deferred behind 186-20 (J = 510,835); merged 2026-09-30 locally
  (`a67b10a4f`, push held by the coordinator)
- [x] 186-14 fresh IC writer: `services/ic_measure.py` writes `feature_ic_scores_v2` (migration 413, `regime_scope`
  in the PK, legacy table untouched) only through `bulk_load`, one provenance batch per unit, skipped
  before any IC when the identity (per-job code key, APR snapshot, per-symbol bar digests, block
  digest) is unchanged and replaced atomically when it moves (`replace_where`); migrations 414 and 415;
  todo 412 closed, todo 469 filed (serial bootstrap cost); merged 2026-09-30 locally (`0db1aa213`, push
  held by the coordinator)
- [x] 186-25 feature_vectors_v2 rebuild writer (D-28, D-32a, todo 339): `run_rebuild_stage` in
  `services/backfill_feature_factory.py` with provenance-keyed (symbol chunk, tf, calendar-year-range)
  units and kill-and-resume; one `compute_kernels` pass per series from its start (regime included,
  R-10), workers spool rows to files and return paths and counts only, the main process merges in time
  order and streams through `bulk_load` (`preclamped_real`); compression only on a clean full-scope
  run; the v2 row contract pinned to the 312-column 186-24 schema; `services/rebuild_preconditions.py`
  holds the seven pure D-32 checks for 186-26's launcher; todos 339 and 476 closed; merged 2026-10-01
  (`84192f5f4`)

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
`research_run.concept_id`, `instrument_classification.scheme` lack them today); todo 459 in the
recipe book's feature domain: a base-versus-interaction composition key replaces the stale
`0_atomic`/`1_interaction`/`2_theory` tier (metadata, CVR `tier` namespace,
`vocabulary_drift.py`), and the 11 HMM regime columns of `feature_vectors` get recipe rows.
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

### Phase 189: IBKR history fetch consolidation: single fetcher, coverage ledger, priority queue replacing the nightly/bulk lease and lane scripts

**Goal:** Exactly one process fetches IBKR history: a timeframe- and dimension-agnostic oneshot fetcher ranks work from an atomically maintained `ohlcv_coverage` ledger (migration 430) with a deterministic SLA-banded priority queue, holds a fail-fast advisory lock shared by every IBKR history tool, and replaces the nightly timer, lane scripts and two-tier lease.
**Requirements**: none (infra phase; decisions CD-01..CD-14 from 189-CONTEXT.md)
**Depends on:** None
**Plans:** 9 plans

Plans:
- [ ] 189-01-PLAN.md - migration 430 ohlcv_coverage + APR keys + bootstrap; coverage writer; atomic three-way persist
- [ ] 189-02-PLAN.md - pure priority queue over the ledger; fetcher advisory lock
- [ ] 189-03-PLAN.md - per-(symbol, timeframe) item fetch with stall bound, retries, atomic coverage persistence
- [ ] 189-04-PLAN.md - IbkrHistoryFetcher oneshot, systemd units, service registry, read-only dry-run gate
- [ ] 189-05-PLAN.md - manual IBKR tools onto the fetcher lock
- [ ] 189-06-PLAN.md - cutover: stop lanes and nightly, live smoke, install fetcher timer
- [ ] 189-07-PLAN.md - delete nightly, lane scripts, lane guard and their tests
- [ ] 189-08-PLAN.md - absorb the pipeline into _history_fetch.py, lock CI guard, retire lease APR keys
- [ ] 189-09-PLAN.md - CLAUDE.md and docs; close todos 488, 452, 387, 455, 484
