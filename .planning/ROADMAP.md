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

## v3.4 rationale

Why v3.4 (phases 174-182) was sequenced as it was, moved here 2026-10-31 (todo 568) from the
superseded edge-proof program doc (archived as a stub the same day at
`docs/plans/archive/2026-09-24-edge-proof-program.md`). When the milestone was set (2026-09-24),
14 constructions had run to a definitive verdict with zero PASS and the feature corpus was
saturated at about 8 independent bets out of about 290 columns, so new primitives mostly got
subsumed. The one positive result on record, todo 378's cross-asset diagnostic (signed
`vol_normalized` ann. Sharpe about 1.19 vs `equal_weight` 0.18), was discounted: mostly in-sample
(about 90% of the window scored ensemble weights fitted through 2025-12-24), compared against a
long-only signal-free arm instead of a null, and underpowered out of sample (9-month holdout,
t about 1.0). The levers were ranked off that: weight-level walk-forward on the cross-asset sleeve
first (turns 9 months of true OOS into about 7 years of pseudo-OOS, the only lever that could
produce a PASS/FAIL within weeks), then breadth (n_eff about 6 to 12+), the data floor, recompute
throughput (about 3.3 days to about 1.1) and a parallel construction track. Outcomes: 179 FAIL
(best arm excess +0.22, adjusted p 0.36), 181 FAIL (H-A, H-B, TSMOM p 0.22), 178 and 182 complete,
177 and 180 superseded. One-line phase entries: `.planning/MILESTONES.md` and
`.planning/milestones/v3.4-ROADMAP.md`.

## Active milestone: v3.5 Unified Research Pipeline

Sequence: `docs/plans/2026-09-26-unified-research-to-production-design.md` section 16, reordered by
the owner 2026-10-27 toward one goal: start testing families with new features, factors and
regimes as soon as the data allows. Build first (2026-09-27) is lifted at plan 191-20's 1d
re-derive; from then on, family 2 and the daily families (441, 423, 440) run while the rebuild
runs. STATE.md holds current position; PRIORITIES.md holds the lane order and the todo tiers.

| Order | Phase | Lever | Status |
|---|---|---|---|
| 1 | 191 Unified raw bar table | One raw table, canonical as a selection; Tradier retired. Settles canonical 1d for every daily test | Complete (plans 01-25, 2026-10-31). Residual: the restore toolchain and backup removal are todo 574, on or after 2026-11-12 (integration-test residue 572 closed 2026-11-01) |
| 1b | 192 Massive flat files and entity identity (to be created with /gsd-phase when the plan is upgraded; todo 600) | One bulk vendor for all symbols from 2003 (minute aggregates, unadjusted SIP): the flat-file leaf, the pilot basis study and the file manifest; identity, definition-epoch and session-calendar tables only as the pilot proves each need (todo 600) | Plan upgraded and archive verified 2026-11-10; every raw load 2026 to 2003 done and gated 2026-11-11 (403.3M Massive rows, compare 0 real differences, canonical unchanged); step 7 tooling landed (1561842d7); admission executes on the lead's call (the section 8a load checks, then step 7) |
| 2 | 186 Old ensemble chain retirement and ic_engine re-scope | Rebuild `feature_vectors` and the regime columns; fresh IC store | 25/29. 186-17 Task 2 and 186-28 remain; 186-26 stage 1/1b 1d done 2026-10-30 (5,424,063 rows), stage 2 intraday paused 2026-11-01 at 650/1,252 symbols pending todo 584's stored-value fixes (the corpus is recomputed once at the new pin); 186-27 swap landed 2026-11-04 on the empty table (migration 570, one name `feature_vectors`); the rerun waits on complete data, which is now Massive admission execution (todo 600: archive acquired and verified 2026-11-10; the 186-31 step runner converged; on admission day the canonical one-pass rebuild per the admission design replaces the rerun's data step, then the rerun runs at the new pin) |
| 3 | 184 Multi-timeframe research inputs | S0 reads `feature_vectors` across timeframes through the causal align node (todo 435); the gate for every feature family | Plans 01-10 landed 2026-11-04 (a feature member runs S0->S8 on a synthetic panel; admission per todo 588: feature 1h/15m->1d, rk_high_dist 126, the 1h+15m book); 11 open; 12 (dry S0 on real data) waits on 186-27; 13-14 on todo 482 |
| 4 | 187 Research core: recipe book, selection, construction | Counting, StepM selection, construction and horizon rules, pod books, recipe book | Plans 01-11 landed, and 15 Task 2 (`PanelSpec.fields`, which with 09 and 10 unblocks 184's wiring); 12 next, then 13-15. E17 daily statistic landed 2026-10-30 (todo 547); the Step B v2 battery passed 2026-10-31, so StepM selection is unblocked; the owner holds the S1-drift option A/B decision. Governance (16 DAG manifest, 17 per-writer DB roles, 18 package renames) moves after the first feature family |
| 5 | Testing | Family 2's one evidence run and the daily price-only families at 191-20's re-derive; feature and regime families after 184 | 1d re-derive landed 2026-10-29; the lane waits on the owner's S1-drift A/B call (todo 547) and the clean-data rule; E17 verdict: every battery cell passes except the pre-registered cause-3 S1-drift pattern on `residual_momentum_12_1_z` |
| 6 | 188 Forward runner and capital tier | `BookTracker`, sealed shadow, full cost model, `portfolio_state` and sizing | Not planned; waits on a candidate book |

Done: 183 (research layer, 11 plans), 185 (daily data foundation, 53 plans), 191 (unified raw
bar table, 25 plans); 189 and 190 are functionally done (stale boxes noted in STATE.md).

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

**Status:** complete (11 plans). The runner refuses a real-data run unless the spec is committed and unrun, writes a `started` ledger row first and records spec, snapshot and code hashes; the S6 ledger is the sole writer of research evidence and the vintage budget (M = 30 until phase 187 replaces it); the S7 walk-forward ridge combiner and S8 book test are built. E16 adopted (HAC timing t decides; 183-11). First real-data run: family 1 evidence completed, book v1 refused uncharged. Full plan list and requirements: `git show 1cd2d632a:.planning/ROADMAP.md`.

### Phase 184: Multi-timeframe research inputs

**Plan now (owner 2026-10-27):** this phase gates every feature family, so it is planned in
parallel with 191 and 186 and runs on the rebuilt table after 186-27.

**Revised 2026-09-26 (todos 435, 436, 446; unified design UD-25):** scope follows revision 3 of
the multi-timeframe design. The 5m aggregation moved to phase 185, the kernel table is phase
186's registry, S0 reads the rebuilt `feature_vectors`, and the IC term structure is computed by
the shrunk ic_engine.

**Goal:** Predictors computed on any timeframe can enter a book on one clock without a lookahead,
a filled value or a second implementation of a feature. Supported at phase close (Codex review 2026-10-27):
daily books with 1d, 1h, 15m and 5m sources and 1h books with 1d sources, horizon 1, equal weight;
every other route is refused at spec load until an E17 battery cell certifies it. Build section 7 of
`docs/plans/archive/2026-09-25-multi-timeframe-horizon-design.md` (revision 3): B1 S0 adds `high`, `low`
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
**Requirements**: MTF-B1a to MTF-B1k, MTF-B2a to MTF-B2c, MTF-B3a to MTF-B3c, MTF-B4, MTF-B5, MTF-B6, MTF-B7, MTF-B8a, MTF-B8b (184-RESEARCH.md)
**Depends on:** Phase 183 (runner, S7, S8), E16 (adopted in the phase 183 session), phase 185's
derived 15m and 1h grid (B1), phase 186's kernel registry and shrunk ic_engine (B2, B4). Daily books
with price-level members declare `panel.total_return` (todo 428, closed 2026-09-26).
**Plans:** 14 plans in 8 waves (planned 2026-10-27; Codex-reviewed, 184-REVIEWS.md). Wave 1 (01-03) is new files only and can run on indicagent-5b's go; the wiring wave (06-11) waits on 187-08, 187-09, 187-10 and 187-15 Task 2 and lands before 187-18; 12 waits on 186-27; 13-14 wait on todo 482.

Plans:

- [x] 184-01-PLAN.md - shared MTF fixtures, `clock.closes_at`, the causal `align` node (one implementation, int32 source-row index) (wave 1)
- [x] 184-02-PLAN.md - research kernels package and `kernel_source` (wave 1)
- [x] 184-03-PLAN.md - smoothing menu, member memory, lag term structure in statistics (wave 1)
- [x] 184-04-PLAN.md - pure S0 feature-read decisions (provenance pin, warmup mask, coverage floor) and the read boundary (wave 2)
- [x] 184-05-PLAN.md - E17 battery for persistent predictors and battery-certificate admission (wave 3)
- [x] 184-06-PLAN.md - spec surface for feature and kernel members; `closes_at` in 187-15's fields (wave 2)
- [x] 184-07-PLAN.md - S0 bar side: closes_at, warmup prefix, derived-vendor refusal (wave 3)
- [x] 184-08-PLAN.md - S0 feature block with every todo 435 gate; compact source evidence and align index for finer sources (wave 4)
- [x] 184-09-PLAN.md - runner spec-time memory, route refusal, S0 request (wave 5)
- [x] 184-10-PLAN.md - member dispatch on the book clock and S3 for input members (wave 6)
- [ ] 184-11-PLAN.md - IC term structure by lag as a record nothing reads (wave 7)
- [ ] 184-12-PLAN.md - one dry S0 build on the rebuilt table, gated on 186-27 (wave 5)
- [ ] 184-13-PLAN.md - economic block in S0, gated on todo 482 (wave 6)
- [ ] 184-14-PLAN.md - economic members and the one-session shift test (wave 8)

### Phase 185: Daily data foundation

**Status:** complete (53 plans, waves 1-26). Built stages D0-D7 of `docs/plans/archive/2026-09-26-daily-data-foundation.md`: data-quality labels, an append-only 1d observation store, derived 1d bars written by the derivation alone, venue-move recovery (todo 433), empty history recorded only when every route answers "no data", splits and dividends detected point in time, listing-venue history (D6) and daily reconciliation (D7). D8 (forward survivorship capture) was descoped 2026-09-26 and the survivorship bound retired 2026-10-09 (todo 514). The Tradier-primary 1d path became IBKR-primary (185-47) and was then deleted by phase 191; the v2.x AI stack was removed (185-45). Full plan list: `git show 1cd2d632a:.planning/ROADMAP.md`.

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
  todos 478 and 467 decided first; owns the todo 420 orphan-cleanup rerun; todo 560 (volume-basis guard) closes before the launch

- [ ] 186-27 rebuild close-out and name swap (D-34): unit-by-unit provenance verification, sampled
  drift report, atomic swap to `feature_vectors`, compression policy re-enabled, old 89 GB table
  dropped behind its dead-cache card; closes todos 411 and 426; behind 186-26

- [ ] 186-28 ic_engine re-scope close (D-35): the 186-14 fresh IC writer run on the rebuilt table
  (scopes `unstratified` and `regime_volatility` into `feature_ic_scores_v2`), legacy
  `feature_ic_scores` dropped (R-07), D-19 bound verified on v2; its tf set waits on todo 471's
  measurement

- [x] 186-30 run identity for the corpus rerun (todo 593): migration 578 (corpus_run,
  corpus_run_step, provenance_batch.run_id), the rebuild's run_id, Jan-1 span and chunk_indices,
  ic_measure and canary --run-id; landed 2026-11-05

- [x] 186-31 corpus rerun step runner (todo 593): `services/corpus_rerun.py` span-major DAG under
  one run id, `services/corpus_rerun_budget.py` span planner and per-unit disk guard, adoption
  list, runbook; the dead shell orchestrator deleted; landed 2026-11-05

- [x] 186-32 corpus rerun data gate (todo 593): migration 579 (nine infra.corpus_rerun.* keys),
  `run_data_gate` per name-year continuity on the NYSE calendar with the survivorship caveat;
  landed 2026-11-05

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
**Order (owner 2026-10-27):** plans 08-15 first; 16, 17 and 18 and the FK indexes move after the
first feature family, since none of them is needed to test one.
**Plans:** 18 plans, each with review amendments (Codex and AGY, 187-REVIEWS.md). Status
2026-10-28: plans 01-11 landed (ridge and kappa 0.2 books certified; kappa 0.5 refused) and 15 Task 2; migration 530 typed the concept domains live. StepM:
the attestation is a complete 13-cell battery at 4,000 sessions (owner decision 2026-10-27;
at 1,500 sessions two cells failed, at 4,000 both hold); until it runs and holds, no selection
set counts as a result. 03's backfill (8 of 20 replays, then `--apply`) is approved by the owner (2026-10-27), one at a time under a memory cap. E17 v2 (todo 549): step A found 5.40% size, but its interval treated an H0 simulation's correlated arms as independent (design effect 1.5 to 2.1) and fresh 4,000-session runs show 4.3 to 4.9%; owner 2026-10-28: rerun step A with a cluster-robust interval over every gating cell before building fixed-b (unit `e17-step-a-rerun`); fixed-b, if it still stands, is a versioned statistic with old records kept and family 1 re-scored as new rows; the StepM attestation and the fitted-book certificate rerun under the step B battery rule. Plan 18 renames the research package and waits
until family 2's one evidence run (after plan 191-20's 1d re-derive) has finished; plans 08-17 do not
move a recorded spec hash and proceed now.

Plans:

- [x] 187-01-PLAN.md - migration 515: recipe book and selection-universe schema (wave 1)
- [x] 187-02-PLAN.md - S6 ledger records each attempt's E17 D_s series and headline numbers
- [x] 187-03-PLAN.md - replay backfill of the pre-515 series (code landed; 8 of 20 replays and --apply pending)
- [x] 187-04-PLAN.md - Romano-Wolf StepM in statistics/
- [x] 187-05-PLAN.md - StepM through the E17 H0 battery (code landed; full 13-cell run pending)
- [x] 187-06-PLAN.md - the E18 switch: exploration mode, no M refusal, select_books, migration 516
- [x] 187-07-PLAN.md - ConstructionRule protocol, five rules, E17 parity harness
- [x] 187-08-PLAN.md - horizon rule (fourth part of the book) and the E17 memory rule for fitted books; fitted books run under a battery certificate
- [x] 187-09-PLAN.md - combining rules: missing members, in-fold signs, calendar-anchored refits
- [x] 187-10-PLAN.md - pod books (P&L-level combination across clocks)
- [x] 187-11-PLAN.md - recipe book identity and recipe writes on the clean schema
- [x] 187-12-PLAN.md - ConceptRegistryService on the clean schema; todo 459 (landed 2026-10-28, migrations 533 and 535)
- [x] 187-13-PLAN.md - summary cards and the generated ledger (landed 2026-10-28, migration 536; render timer installed, not enabled)
- [x] 187-14-PLAN.md - contribution accounting (S8 extension) (landed 2026-10-29, migrations 538 and 539; sampled Shapley and cluster groups wait on 187-15; multi-family books wait on todo 562)
- [x] 187-15-PLAN.md - generated_family grammar support in the spec (Task 2, `PanelSpec.fields`, landed 2026-10-28)
- [ ] 187-16-PLAN.md - YAML DAG manifest read by service_auditor and the orchestrator
- [ ] 187-17-PLAN.md - single_writer enforced by per-writer database roles
- [ ] 187-18-PLAN.md - research package split and renames, todo 430 step 4 (after family 2)

### Phase 188: Forward runner and capital tier

**Goal:** A frozen book runs forward on the same code that tested it, and capital is sized on
measured net. Track E of the unified design (sections 3, 7.3, 8, 9): `BookTracker` and
`BookPositionWriter` (replacing `alpha_publisher`), sealed shadow for every book in the selection
set, append-only positions with revision alarms, positions parity with research; full cost model
(impact, borrow constraint, capacity curve, implementation shortfall); `portfolio_state`, sizing
and risk limits (re-scoped phases 156-157); challenger protocol with a paired test.
**Requirements**: TBD
**Depends on:** a candidate book in the selection set; todo 438's borrow snapshots (running daily since 2026-10-31).
**Plans:** 0 plans

Plans:

- [ ] TBD (run /gsd-plan-phase 188 to break down)

### Phase 189: IBKR history fetch consolidation

**Status:** functionally done (plans 01-10; cutover executed 2026-10-06). One oneshot fetcher ranks work from the atomically maintained `ohlcv_coverage` ledger (migration 432) through a deterministic priority queue and holds the advisory lock every IBKR history tool shares; the nightly and lane scripts are deleted. Plan 189-11 (5m backfill completion) is superseded: the 534 campaign stopped gating on 2026-11-10 when Massive became the data-complete path (todo 600), and the IBKR leg falls to the deletion list after admission. Full plan list: `git show 1cd2d632a:.planning/ROADMAP.md`.

### Phase 190: Provider history plane unification

**Status:** complete (7 plans; cutover 2026-10-10, parity PASS). One multi-provider fetcher (`ohlcv_history_fetcher`) with a provider dimension on queue items, per-provider heads and quarantine (todo 526, closed), leaves in `src/providers/<vendor>.py` behind one protocol, and a two-tier ledger. Design: `docs/plans/archive/2026-10-09-provider-history-plane-unification-design.md`. Full plan list: `git show 1cd2d632a:.planning/ROADMAP.md`.

### Phase 191: Unified raw bar table

**Status:** complete (25 plans, 2026-10-31; todo 533, design `docs/plans/2026-10-12-unified-raw-bar-table-design.md`). One raw table `ohlcv_raw` for every vendor and timeframe, last-wins with a revision log; canonical `market_data_ohlcv` is a rebuildable selection by policy carrying vendor and kind; the two old stores are dropped; Tradier is retired and its code deleted. Residual: the restore toolchain and backups go under todo 574 (due 2026-11-12). Phase 192 (Massive) builds on this layer. Full plan list: `git show 1cd2d632a:.planning/ROADMAP.md`.
