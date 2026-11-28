# Todo Priorities

**Scope of this index:** `pending/` only: small, single-session, run-it-now items. Phases
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
model complexity · never drop data that could contain signal · earn capital through proof
(count every look, select with StepM, promote on positive net expectation; E15-E18) · segment by regime · automate manual tasks · empirical over theoretical ·
resist overfitting. A todo that would earn its way to P0/P1 under these tests (a live-path
integrity gap, an unproven claim masquerading as settled) outranks one that's merely convenient.

**Pointers, not duplicated here:** phase status and in-flight runs live in `.planning/STATE.md`;
the sequence in `docs/plans/2026-09-26-unified-research-to-production-design.md` section 16; ideas (not work) live only
in `docs/research/construction-verdict-ledger.md` for now (interim: the adopted unified design,
phase 187, makes UCR the recipe book and renders the ledger from it). Before re-deriving
stratification candidates read `docs/research/stratification-dimension-unification.md`
(cross-links 135/167/224/225/111). The v2.x remainder is todo 509 (plan 185-45 removed the rest;
the pre-removal tree is the local tag `archive/v2x-ai-stack-2026-10`). History of past triage passes lives in
git and in each todo's own closure note, not in this file. Durable reasoning behind this file (process rules,
active sequencing decisions): `docs/research/priorities-decision-log.md`.

## Critical path (current 2026-11-26)

Next actions in order: `.planning/STATE.md` Handoff and Queue. The heavy slot runs one job at a time under the DIMM watchdog (`docs/operations/guarded-run-runbook.md`). Done: the four family 10 counted runs and the StepM read (ledger 2026-11-25b), the single re-pin landing (639c244b1, pin 0f593f92f8b4). Now: the member verdict refresh, a fresh preflight and a new pilot at the new pin, then `stage_1d` to `feature_complete`, then the 1d IC measure (todo 471). In parallel before the Massive lapse: the final capture of every entitled dataset with its ubuntu2 copy (todo 600 item 9, `docs/operations/massive-final-capture.md`). The dated Massive plan call (renew or lapse before about 2026-12-10) is in `docs/plans/2026-11-15-massive-plan-lapse-deadlines.md`.

Ranked P0 and P1 order by the path to a counted test (lead pass 2026-11-24; "code key" = the todo edits code a live or resumable run imports, so it lands only when that run is quiet):

| Rank | Todo | Blocker | Owner | Size | Code-key note |
|---|---|---|---|---|---|
| 1 | 584 | verdict refresh, new pilot at pin 0f593f92f8b4 (waits on the 06:00Z audit), then `stage_1d` | lead, indicagent-fb | heavy slot, hours | is the pin |
| 2 | 649 | timer `indicagent-split-feed-auditor.timer` installed 2026-11-26 (daily 07:45Z, first run clean); left: the mechanical closing criteria in the todo (28 clean runs, earliest 2026-12-25, plus two alert gaps) | ops session | small, no code edit | none |
| 3 | 600 | final capture of every entitled dataset (running 2026-11-26, worker lane) plus the ubuntu2 copy; owner decision: renew or lapse by 2026-12-10 | lead, owner | decision | none |
| 4 | 669 | after the four family 10 runs and the StepM read; one route plus new battery cells | research session | medium | edits `src/intelligence/research`: `repro_frozen` bit-identical, rebinds, never beside a live counted run; before the pin of any counted corpus test |
| 5 | 588 | part C (real-data dry S0) needs the scope-all rerun (item (e) deleted 2026-11-25: S0 refuses rk_vwap_dev loudly; tag `archive/588e-volume-basis-2026-11`) | research session | medium | S0 code: after the pilot |
| 5b | 670, 671 | P1 by lead ruling 2026-11-24: sweep recorder and synthetic check landed in the re-pin (639c244b1); the todos close after the ledger line 2026-11-25c is confirmed by the owner | research session | medium each | 671 adds a writer; 670 a synthetic check; no live-run edit |
| 7 | 471 | width-pin measurement runs only after the pilot and with no heavy job live | lead | one heavy run | none |
| 8 | 547, 586 | owner rulings (S1 drift, which also decides use of the 2026-11-25b StepM read: certify `reversal_21` and its book or hold the family; persistence statistic, branch `wip/586-persistence-statistic`) | owner | decision then medium | `statistics/`: `repro_frozen` |
| 9 | 558, 461, 466, 583, 571 | all after the corpus rerun lands the rebuilt columns; the 461 and 466 ledger and card annotations are done (5f1af57f6), only the re-measurements remain | worker sessions | small each | 571 and 583 write the DB after the rerun |
| 10 | 614 rows 9 and 11 | rows 3, 10 and 13 are landed and row 16 is split-on-touch (lead ruling 2026-11-27); row 9 (seam witness) and row 11 (migration 621, the database pins UTC) are ready on branch `wip/614-row9`, outside every pin closure, and land after the pilot with `tools/lint_env_check.sh` | worker session | small | yes, after the pilot |
| 11 | 439 part 2, 435, 441, 423, 440, 442, 601, 603 | the corpus rerun and phase 186-28 IC run; 442 is paused and owned by phase 183 | after the rerun | per todo | research edits wait for quiet |
| 12 | 615, 622, 624 | data-quality items, now P3 under the 2026-11-20 materiality rule; 609 is folded into 584 | lead | none to small | none |

Sequence: `docs/plans/2026-09-26-unified-research-to-production-design.md` section 16; session lanes
and the lead's order in `.planning/STATE.md`. The goal is to test features, factors and regimes as
soon as the data is complete. The owner rule (2026-10-30, 2026-11-04) holds: no real-data hypothesis
test and no corpus compute until the data gate passes. The gate is now Massive admission (todo 600),
not IBKR coverage.

| Lane | Order |
|---|---|
| Data (phase 191 done, 192 Massive) | Raw loads 2026 to 2003 done and gated 2026-11-11; 8a checks done as the admission record (r5 pushed a0a9eb851, gates nothing per owner ruling; first verdicts 2014-2026 ok both timeframes) -> the placed-span load and the A11 witness gate -> step 7 done (2026-11-16) -> data gate 186-32 -> the 584 pin and one corpus rerun -> 186-28 fresh IC run. The IBKR deletion (Part F) lands only after the rebuild proves itself; todo 574 (Tradier removal) done 2026-11-12 |
| Build (phase 186, 25/29) | 186-26 is the corpus rerun on the new universe: pin `09708ae249f2`, pilot next (todo 584, `docs/operations/corpus-rerun-runbook.md`); 186-28 after it with `ic_tfs` = 1d only (todo 471, 15m and 5m wait on 667); 186-17 Task 2 unblocked |
| Research inputs (phase 184) | Plans 01-10 landed; 12 (dry S0 on real data) waits on the rebuilt table (1h and 5m need a scope-all rerun); 13-14 on todo 482; admission holes are todo 588 |
| Research core (phase 187) | Selection core plans 08-15; StepM attestation passed 2026-11-23; governance (16-18) after the first feature family; the S1-drift call on the momentum members is the owner's (todo 547) |
| Testing | Counted: daily residual, seasonality and family 9 (null); family 10 counted runs pending (todo 663); feature and regime families after the corpus rerun and 184 |
| Quick, independent | 554 landed (legacy feature_vectors readers deleted); consolidation of the pending P2 and P3 rows is done (batches 1 to 5) and 13 of the 25 deferred todos are re-checked; the remaining deferred todos are listed in `docs/research/priorities-decision-log.md` |

Verified against live state 2026-11-24: the P0 and P1 rows (lead pass 2026-11-22 and the pre-rerun window), every pending P2 and P3 row (consolidation batches 1 to 5; 512, 520 and 522 are owner rules and ideas, reported only), and every deferred todo. All deferred todos were re-checked against live state 2026-11-24 (batches D1 to D3); 527, 565, 567 and 596 stay deferred until the corpus rerun finishes.

## P0: Gates the data gate or the first counted test

| Todo | Why now |
|---|---|
| [584](pending/584-corpus-rerun-fix-manifest.md) | P0, the critical path. One list of stored-value fixes before the pin moves, then one corpus rerun. Every code item has landed, the stage 2 membership is rebuilt and repinned (22be5378a), and the scope-1d data gate and `d2_landed` pass (ledger 2026-11-21e to 21g). The 1d-first run a4f6ad40 stopped at the pilot feature column screen (todo 652, P3, parked); the daily counted run waits on the owner's E21 ruling. Readiness table in the todo. Todo 609 (stage 2 universe) is folded here: s0 to s8 are done and pinned (22be5378a); only this rerun is left. |
| [588](pending/588-184-admission-holes-from-wave-review.md) | P0, gates the first counted test with an input member. Parts A and B landed 2026-11-04. Part C (184-12 real-data dry S0 build) needs stored 1d, 1h and 5m columns, so it runs after a scope-all rerun, not the 1d-first run. |
| [600](pending/600-massive-flat-files-all-history-vendor.md) | P0, step 7 done through D4 (2026-11-16). Canonical is Massive then Alpaca. Part F is closed (no `ohlcv_raw` ibkr rows from 2003-09-10). Remaining before the plan lapses about 2026-12-10: the renewal decision, filings sizing by 2026-12-01 and the nightly leaf (items 1, 5, 7, 9, 10); the off-site copy was declined by the owner. |

## P1: High value, fully unblocked or on the critical path

**Unblocked by the Massive loads (run now)**

| Todo | Why now |
|---|---|
| [649](pending/649-splits-after-the-massive-seam-need-a-detector.md) | P1. SNDK 8:1 split (ex-date 2026-11-20) failed the nightly on a basis-change flag; second post-seam split in two days after VIXM. The SNDK row is applied (91c77af37); measure the base rate, then decide a proposal-only detector from the Alpaca corporate-actions feed. Detector built 2026-11-23 (services/split_feed_auditor.py, migration 612); the timer is installed (2026-11-26). |
| [614](pending/614-refactor-audit-2026-11-14.md) | New 2026-11-14, P1. Sixteen ranked refactor candidates from the lead audit. Rows 1, 2, 6, 8 and 12 (the rebuild code key hole, the survivorship caveat that reads zero after step 7, dead v2.x schema, zero-fill in the streaming path) land before the 584 run is created; 3, 9, 10, 11 and 13 after step 7 proves itself. |

**Pre-rerun window (lands before the corpus rerun at the new pin; 571 right after it)**

| Todo | Why now |
|---|---|
| [558](pending/558-pre-rebuild-feature-pass-decisions-and-registry-cleanup.md) | Add-list landed (584-8) and rank_z retired (035c11902). After the corpus rerun: measure `ret_acf1_z` against `ret_autocorr_1` and fill `redundancy_group` (0 of 424) from measured correlations; coordinate with the 571 concept reset. |
| [466](pending/466-regime-columns-lookahead-dependents-303-304-benchmark.md) | The research read refuses non-rebuild regime columns (`feature_inputs.py:494`). Annotations of the 303/304 ledger rows and cards are done (5f1af57f6); left: rerun their benchmark on the corpus rerun's regime columns; `feature_matrix.py` was deleted with todo 554. |
| [461](pending/461-gap-z-read-the-next-bars-open.md) | `gap_z` lookahead fixed in code (186-12, db4ef4e80). The ledger note and the n1 combiner card caveat are done (5f1af57f6); left: re-measure `gap_z` IC on the corpus rerun's rows and confirm the drift report shows it moving. |
| [471](pending/471-ic-measure-intraday-full-universe-memory-and-time.md) | Ruled 2026-11-24: scope-1d pin width 16 with `ic_tfs` = 1d only; no 5m or 15m until 667 (time chunks); 1h only at width 4. Open: record the 25-name `--dry-run` RSS at widths 4, 8, 16 and 32 after the block 2 rerun, then pin the width in the scope-1d APR. |
| [583](pending/583-hmm-regime-null-on-whole-names-in-the-1d-rebuild.md) | K=3 decided (E20, migration 566, 07d980e87); HMM NaN is judged only on written segments (661). After the rerun: measure the K=3 refusal share across the full 1d universe and declare regime-unknown names before any regime-segmented 1d spec. |
| [571](pending/571-reset-the-concept-layer-after-the-186-26-rebuild.md) | P1, owner-approved, runs after the corpus rerun reaches feature_complete. Demote the 306 `active` features to `candidate` through `ConceptRegistryService` and clear the 590 old evaluations; back up first. |

**Quick and independent**

| Todo | Why now |
|---|---|
| [439](pending/439-forward-span-integrity-write-once-oos-start-and-ic-purge.md) | Parts 1 and 3 done 2026-10-26: `oos_start` is write-once (migration 506) and the 7 forward-span looks are disclosed in the ledger. Part 2 (purge IC targets crossing it) lands with phase 186 (186-20, 186-28). |

**Research: counted tests wait on the clean-data rule (E21 adopted 2026-11-13); the order after them is 547/586, 441 + 423, 440, then the feature and regime families**

| Todo | Why now |
|---|---|
| [442](pending/442-attempt1-single-family-and-pod-books-e17-memory-rule.md) | Paused (build first). `spec.py` refuses a book mixing families 1 and 2: run single-family books plus a pod book; E17's L must add combiner and partial-adjustment reach, with H0 battery cells, before fitted combiners run. Phase 183 session owns the files. |
| [441](pending/441-price-only-daily-families-931-names-prereg.md) | Residual momentum is in the daily residual family with 423: prereg `docs/plans/2026-10-27-daily-residual-momentum-reversal-prereg.md` (draft after two Codex rounds), members, B1 universe (1,269 unseen names) and B2 battery built (ee8c264df). Left: the full B2 battery, B3 power, the spec, registration, then the run after 191-20's 1d re-derive. Industry momentum (needs point-in-time industry labels) and sector lead-lag (intraday) stay open here. |
| [423](pending/423-phase181-short-term-reversal-prereg.md) | Residual reversal R1-R3 are members of the daily residual family (see 441); the screen's 231 names and the TSMOM sleeve are excluded by the B1 rule. Runs with 441's h = 5 spec. |
| [547](pending/547-e17-hac-lag-for-overlapping-targets.md) | E17 daily statistic landed 2026-10-30 (flat-top kernel plus influence series); daily battery down from 40+ size failures to 3 marginal ones. Owner decision: certify reversal members and book, hold `reversal_5_skip1` and momentum (S1 drift), or hold the family. B3 power still open. The horizon-tied HAC lag is part of [669](pending/669-shared-horizon-5-1d-feature-route-in-the-runner.md) (one statistic fix with 586). |
| [586](pending/586-persistent-battery-gating-cell-failure.md) | New 2026-11-04, plan 184-05. Ten gating cells of the persistent-predictor E17 battery exceed size (long tau, 1d and 5m sources, 21 and 63 smoothing, the hourly book, rk_price_percentile 126); oversize grows with persistence, consistent with an HAC lag that does not scale with weight persistence (cf. 547). Members on those routes stay refused. Part of [669](pending/669-shared-horizon-5-1d-feature-route-in-the-runner.md): no separate fix. |
| [440](pending/440-generated-family-grammar-daily-ohlcv-931-names.md) | Unpauses at 191-20's 1d re-derive (owner 2026-10-27). Attempt 3b (ledger family 12): a registered grammar over daily OHLCV primitives, in-fold selection plus ridge, never materialized. |
| [435](pending/435-wire-feature-vectors-into-research-panel-all-timeframes.md) | Built as phase 184 B1 (plan 184 now, owner 2026-10-27). The research layer never reads `feature_vectors` (both families use raw 15m returns), against the adopted architecture. Wire features into S0 at 5m/15m/1h/1d with pinned windows, masked warmup and a coverage floor, after the 186 rebuild. |
| [603](pending/603-base-feature-scouting-and-data-adjacency-register.md) | New 2026-11-09, P1. Lowest rung of research: a data adjacency register (what sources serve versus what we store), admission gates that never peek at returns, and rejections recorded as registry rows; design in `docs/ideas/base-feature-scouting-and-the-research-ladder.md`. |
| [669](pending/669-shared-horizon-5-1d-feature-route-in-the-runner.md) | New 2026-11-24, P1 (lead). Stored 1d feature members run only at horizon 1 in the runner, so every corpus family at horizon 5 waits on one route plus new persistent battery cells. Gates: `repro_frozen`, battery rebinds. After the pilot, before the pin of any counted corpus test; never beside a live counted run. Ruling 2026-11-24: design B (statistic fix first with a methodology-change entry, `repro_frozen`, battery rebinds); it carries the HAC-lag work of 547 and 586; the member check shows 161 of 282 stored 1d columns above 20 bars (21 more hide a builder window behind declared memory 0), so a short-memory certificate is not planned. |
| [674](pending/674-pass-through-columns-declare-memory-zero-and-understate-their-window.md) | New 2026-11-24, P1 (lead, a silent wrong answer). 21 stored columns (H-B and market-residual members among them) declare memory 0 although their builder windows are 21 to 311 bars, so a certificate bound, the warmup mask and the E17 memory L would treat them as memoryless. Fix before any certificate of 669; edits the rebuild closure, so it moves `rebuild_code_key()`: land after the pilot passes and before `stage_1d` is launched, never during a live run. |
| [675](pending/675-session-coverage-judges-a-session-the-capture-has-not-delivered.md) | New 2026-11-25, P2 (lead; ruled in ledger 2026-11-25e, code after the pilot data gate). One missing trailing session fails any name under 1,000 sessions on `session_coverage`, judged against a session the nightly capture has not delivered; it refused pilot run 0e020c5a. Proposal only (a ledger entry before any rule change). |
| [670](pending/670-synthetic-stepm-check-with-sweep-scale-null-cells.md) | New 2026-11-24, P1 (lead ruling, IC waits on it; behind 669). A full 1d sweep adds about 1,100 cells to the 16 series and could drop `reversal_21`; check synthetically (about 1,100 correlated null cells, no real-data compute) and set the sweep's `n_looks`. Before any sweep. |
| [671](pending/671-ic-measure-sweep-cell-writer.md) | New 2026-11-24, P1 (lead ruling, IC waits on it; behind 669). No writer records IC sweep cells as counted attempts (E21), so a sweep would be an uncounted look. One writer into the ledger; prerequisite of the first real-data sweep with 670. |

## P2: Real value, not urgent

| Todo | Why now |
|---|---|
| [686](pending/686-code-health-report-hotspots-ratchets-escaped-defects.md) | New 2026-11-27, P2, owner ruling (constant refinement is north star). The code loop of `docs/foundation/harness-improvement-sop.md`: one read-only report of file hotspots, `fixes <sha>` escaped defects and every ratchet baseline, so the refactor queue is ranked by evidence. Pairs with 685. |
| [687](pending/687-hmm-stationary-prior-of-an-absorbing-chain-misdecodes-bar-0.md) | New 2026-11-27, P2 (lead ruling; todo 677 side finding). The stationary prior of an absorbing fitted chain puts zero mass on the first regime, so bar 0 of a one-switch segment decodes wrong. Measure first (bar 0 vs bar 1 labels per series in `market_regimes`, light reads after nothing heavy is live); the kernel is in the rebuild pin, so any fix lands at the next re-pin. |
| [688](pending/688-one-reference-hmm-forward-filter-in-tests.md) | New 2026-11-27, P3 (cb review of 677). The numpy reference HMM forward filter is copied in two test files; keep one. Tests only. |
| [685](pending/685-harness-signals-logger-and-the-lead-retro.md) | New 2026-11-27, P2, owner ruling (harness improvement SOP is core). Step 1 of `docs/foundation/harness-improvement-sop.md`: a read-only logger of session idle time, claims and CI, plus the lead's notes on owner interventions, so harness changes are judged on evidence. First judgment: does pull-based claiming (`1850fb596`) cut idle minutes and owner pokes over 14 days. |
| [663](pending/663-family-10-volume-shock-kernels-spec-and-run.md) | New 2026-11-22, P2, spec, members, battery and run blocked on todo 653 (member panel source plus S1 residual e). Kernels on main; data gates 563 and 560 cleared, prereg gates 4 and 5 open (heavy slot). |
| [665](pending/665-ic-measure-feature-list-reads-the-dormant-featurevector-dataclass.md) | New 2026-11-24, P3. `ic_measure` chooses its feature columns from the dormant `FeatureVector` dataclass plus table extras; take them from `feature_vectors_numeric_columns()` and refuse a registry column the table lacks. Results unchanged. |
| [667](pending/667-ic-measure-time-chunk-mode-for-intraday-tfs.md) | New 2026-11-24, P2. `ic_measure` holds a whole tf in memory (targets of every horizon, a dense [bars, names, width] block): 15m needs width 4 or less and 5m fits at no width. Time-chunk mode, bit-identical on tfs that fit; prerequisite of the scope-all pin. |
| [656](pending/656-integration-test-harness-redesign.md) | New 2026-11-22, P2, blocked on the residual run being counted. Integration harness redesign: a capped disposable test cluster on the production image (port 5442; 5433 is ssfi's), planned in `docs/plans/2026-11-23-integration-harness-plan.md`: delete 17 integration functions first, then the cluster, then the baseline bump, a database per session copied from a hashed template, the six live-data tests deleted (monitoring belongs to the D7 audit), the schema sync kept behind `--live-catalog`, an interim session lock, a baseline bump that closes 655, CI after 654. |
| [654](pending/654-database-image-timescaledb-ha-with-pgvector-and-toolkit.md) | New 2026-11-22, P2, owner direction, blocked on a planned rebuild window. Move the database from the Alpine custom image to the pinned Debian `timescaledb-ha:pg18` (pgvector and toolkit included) with a `C.UTF-8` database, by dump and restore after an ubuntu2 rehearsal; the standby and WAL archive move with it. Not before the counted runs finish. |
| [653](pending/653-family-9-close-member-input-spec-battery-and-run.md) | New 2026-11-22, P2, blocked on the daily residual and H-C seasonality runs being counted. The family 9 kernel is on main; the close member input (edits two runner statistic functions, so both existing battery records rebind in the same commit), the spec, the battery and the run follow. |
| [650](pending/650-forward-feed-covers-a-quarter-of-the-stage-2-members.md) | Nightly reads only the 1,529 active names; 4,615 stage 2 members get no bars after the 2026-11-16 seam. State the book-holdable set, then choose an SOP stage 2 exception or a separate feed. Due before the first book freeze, not the pin. |
| [559](pending/559-cointegration-spread-family-preregistration.md) | New 2026-10-28, owner reopened the cointegration concept (ledger section 2). Pre-register a spread family tested on its trading statistic (static and Kalman hedge ratios, OU half-life), disclosing the 2026-08-07 pilot and the 471-pair screen as seen data; no look before the pre-registration. Placement and the draft are the assistant's (needs an Opus or Fable pass). |
| [548](pending/548-style-spread-regime-slot-and-time-series-construction.md) | New 2026-10-27. The owner's participation-state idea (RSP/SPY and style spreads) cannot run through the runner: S7 has no regime input slot (part A) and the runner is R1 only (part B's time-series book). Part B's synthetic power check comes first and needs neither. |
| [536](pending/536-forward-span-read-guard-for-ad-hoc-queries.md) | Ad hoc SQL past `alpha.validation.oos_start` is unrestricted and unlogged, which can void the one-spend forward confirmation. Add a capped role or view, or audited reads, with a sink and a test. Must land before the first book's forward confirmation. |
| [627](pending/627-sweep-bad-bar-pairs-2007-06-13.md) | New 2026-11-17, P2. Five names show a one-day reversal pair on 2007-06-13 and 2007-06-14 (A3 sweep); a vendor day-file bad bar per name; measure the class, list the bars or a day rule. |
| [634](pending/634-book-and-power-path-bind-session-dates-for-calendar-members.md) | New 2026-11-18, P2 in effect. The book and power-calibration paths do not bind session dates for calendar members, so a book with an H-C member raises a TypeError. Loud, and no book holds one yet. |

**With phase 186 and the streaming revival**

| Todo | Why now |
|---|---|

**Research follow-ups (paused with the attempts)**

| Todo | Why now |
|---|---|
| [456](pending/456-todo445-rerun-zero-commission-and-longer-horizons.md) | Owner review of 445. Part A is moot (`name_set_5m` feeds no code and Alpaca commission is zero). Open: part B, multi-day horizons for 5m features residualized on 15m, 1h and 1d, run as an `ic_measure` question after todos 667 and 668. |
| [457](pending/457-family1-slot-subsets-through-the-runner.md) | Family 1 reopen on the stage 2 5m tier: slot-subset mask and keep gate in the runner with the E17 battery (442); rerun slots counted, outside-runner looks disclosed. Includes 460's auction-print check on a Massive source and the auction-to-auction hold. Blocked on a runner keep gate (phase 187 work). |
| [437](pending/437-first-cut-cost-model-commission-and-spread.md) | Promotion needs positive net expectation; today only flat bps bands exist. Alpaca commission is zero, so the model is regulatory fees plus a quoted or Abdi-Ranaldo spread validated on the tape slice, as distributions. |

**Data and ingestion**

| Todo | Why now |
|---|---|
| [516](pending/516-spin-off-action-type-as-a-research-layer-distribution.md) | CTVA is held with no 1d bars or membership. Add a `spin_off` action type and a research-layer distribution event (unknown, never zero) before release; measure the general spin-off class across members. Items 2 and 3 are done (fe47d2f0a); the CHECK constraint still admits only split, reverse_split and void. |
| [589](pending/589-bulk-load-unit-scoped-recompress-for-renamed-units.md) | New 2026-11-04, P2, from the 584 item 4 review. A completed unit renamed after its `feature_vectors` chunk compressed (restated bar, APR change, onboarding) is refused loudly by `bulk_load`; add a unit-scoped decompress-load-recompress path under the headroom guard. Matters from the first restatement after the rerun's chunks compress. |
| [597](pending/597-intraday-bars-not-scrubbed-nightly.md) | New 2026-11-05, P1. The 594 rules reach 1d nightly but new 5m/15m/1h bars are scrubbed only by a manual pass, so a bad intraday print is served until someone runs it; the grid derivation timer runs the scrub on what it touched. Also measure adjacent bad-print pairs (CORT 2007-09-11). |
| [606](pending/606-feature-registration-wired-into-the-add-list-path.md) | New 2026-11-09, P2. Close the forgotten-concept-row class: wire feature registration into the add-list path plus a CI reconciliation (every stored column has a concept row; every active row has a column or a kernel-only annotation). Found by the 601 reconciliation (two live instances, fixed by migration 585). |
| [568](pending/568-docs-cleanup-outdated-thresholds-gates-and-v2x-content.md) | Owner 2026-10-30. Done except the reset follow-ups: the voided-results pointer for the frozen ledger sections 2 and 4, the summary cards and the FAMILY2 files, which wait on the owner's freeze lift; the stale `test_spec_hashes_pinned` docstring can be fixed now. |
| [443](pending/443-postgres-exporter-chunk-scrape-cost-and-idle-in-transaction-timeout.md) | The postgres exporter's per-chunk scrape is the top database consumer (305 min in 3 days) and the idle-in-transaction timeout is 1 hour. Two config changes, measured before and after. Item 1 (exporter scrape) applied 2026-11-01 and verified: exporter cost now about 1.6 min/day, out of the top 5. Live state 2026-11-26: `idle_in_transaction_session_timeout` is still 1h (psql `show`); migration 315 APR-backs the write-session idle timeout. Remaining: the idle-in-transaction timeout cut, sequenced after the 186-26 rebuild ends and compression 1078/1076 re-enable (the rebuild's compute workers legitimately idle in transaction; the timeout is reloadable, no restart). |
| [520](pending/520-future-timestamp-guard-on-ingested-bars.md) | New 2026-10-09. The writer guard landed in 191-02 (`services/ohlcv_raw_writer.py`, APR `threshold.bar_integrity.future_bar_tolerance_s`, tested). Open remainder: the D7 1d condition, explicit deferral D-191-H (owner acknowledgement pending). |
| [522](pending/522-alpaca-execution-mechanics-shadow.md) | New 2026-10-09, pilot Workstream B. Paper-only order lifecycle validation (20 single-share orders, EOD flat, idempotent reconnect) plus the fixed slippage instrumentation spec. Single session, zero risk, independent of the 189-10 lanes; fastest path to measured own-flow slippage. |

**Held under the IC proposal and in-fold selection methods**

| Todo | Why now |
|---|---|
| [38](pending/038-cross-sectional-collinearity-diagnostic.md) | Held idea: a time series of feature cross-section breadth (participation ratio) as a candidate regime dimension, tested through the runner and counted. Member-level breadth and uniqueness outputs exist (`contribution.py`, `statistics/correlation.py`); the old `ic_engine` path is gone. Not on the counted-test path. Absorbs 039's breadth point. |

**Regime and IC engine**

| Todo | Why now |
|---|---|
| [420](pending/420-market-regimes-orphan-rows-from-pre-tradeable-writer.md) | Mechanism landed (186-18, 53f9af42f). About 3.5M orphan rows remain in `market_regimes`, frozen at 2026-08-14, with no reader in the rebuild or research path. Run the dry run and the counted cleanup with the first regime refit on Massive canonical, before any family reads these labels. |
| [512](pending/512-exclude-or-replace-names-whose-data-defect-is-not-worth-fixing.md) | New 2026-10-08, owner policy relayed (confirmation pending). Names whose data defect needs per-name hand work leave the compute set with a reason code and date; raw data stays; replacement only by a pre-fixed liquidity-rank rule through the onboarding SOP. Disclose in D0's survivorship bound. |
| [644](pending/644-closed-list-disclosure-at-book-freeze-and-confirmation.md) | Required at the first book freeze: member counts per month-end after the stage 2 list, plus excluded newcomers once 643 lands. Put the code in the report, not in `universe_membership.py` (inside the rebuild closure). Owner-adopted. |
| [672](pending/672-ohlcv-revision-load-fk-cascade-to-restrict.md) | New 2026-11-24, P3. `ohlcv_revision.load_id` still cascades on delete of a load row; switch to RESTRICT in a quiet window. Extracted from the closed todo 535. |
| [676](pending/676-ci-unit-job-has-no-database-so-the-live-db-tests-never-run-in-ci.md) | New 2026-11-26, P2. CI has no Postgres, so about 55 `requires_db` unit tests (append-only trigger, advisory locks, bulk load, stage lock) run only on the host. Design: a timescaledb service container plus a migration replay; cost unmeasured; first step is a local scratch replay to list the migrations that fail on an empty database. |
| [679](pending/679-ci-skips-eleven-tests-that-read-untracked-data.md) | New 2026-11-26, P2. Eleven CI skips on untracked data: nine Massive reader tests (commit tiny fixtures) and three frozen-artifact tests (stay on `repro_frozen` on the host; CI prints "frozen artifacts not checked in CI"). Related to 676. |

## P3: Hygiene, docs, process, performance (opportunistic)

**Dated**

| Todo | Why now |
|---|---|
| [684](pending/684-stored-dividend-yield-ignores-massive-coverage.md) | New 2026-11-27, P3. The stored `dividend_yield` reads Yahoo coverage only, the snapshot counts Massive too: Massive-only names (ACC, ACCO, ACES, ACAT, ACAS) are all NaN in the stored column. Fix at the next re-pin (kernel reads Massive) or read the yield from the snapshot in the family. No counted test reads it today. |
| [682](pending/682-skip-the-compression-bound-replan-when-stage-units-are-pending.md) | New 2026-11-26, P3. Every stage call ends with a fixed 600 s `compression_bound` replan that compresses nothing when units are pending (pilot eca9e854: 602 s and 600 s). Skip it when units are pending. Edits fingerprinted `backfill_feature_factory.py`: waits for stage_1d and feature_complete, lands in the post-stage re-pin window. |
| [658](pending/658-mypy-baseline-typing-debt-added-by-the-ci-resync.md) | 38 mypy baseline errors (mostly `research/construction.py`). Fix with real annotations only alongside the next planned research edit; blocked while the family 10 runs and the block 2 rerun are live (battery code keys). Run `repro_frozen` after. |
| [652](pending/652-1d-first-corpus-run-stopped-at-the-pilot-feature-screen.md) | New 2026-11-22, P3. Run a4f6ad40 passed data_gate and pin_gate (23/23) and stopped at the pilot feature column screen (G1 23, G2 84, G3 221, G6 10 on 25 first-alphabetical names). Do the pilot sample rule and 5% null gate fit a 1d scope; are the structure/zone NaNs warm-up? Parked, not on the counted-test path. |
| [483](pending/483-record-2026-midterm-forward-window-result.md) | Due after 2027-05-03: record the committed midterm window (S&P 500, 2026-11-03 to 2027-05-03) as one observation. The economic series end 2026-09-30 by design (todo 480, loaded by hand, timer disabled); refresh `YAHOO_GSPC_CLOSE` before then (run the oneshot by hand or enable the timer, an owner sudo step). |
| [487](pending/487-run-spec-synthetic-defaults-cannot-express-spec-gates.md) | `run_spec --mode synthetic` defaults (30 names, 400 sessions from 2006-07-03) cannot meet a real spec's power ratio or trading start; validate loudly, name the minimal flags, print each member's refusal reason on its RESULT line. |
| [615](pending/615-split-rows-missing-for-renamed-names-ln2-level-shift-check.md) | New 2026-11-14, P3 (demoted 2026-11-24 under the 2026-11-20 materiality rule; was P1). SGH placed under PENG shows a 2-for-1 level step (2022-02-02) and `corporate_action` holds no split row for PENG or SGH; a check over the placed pairs finds every unexplained ln k step. The PENG 2-for-1 row is recorded (todo 630); the ln k check over the other placed pairs is unverified. Its gate (before the d2-v6 rebuild at step 7) has passed. |
| [622](pending/622-unrecorded-level-breaks-clbk-atro-and-d7-blindness.md) | New 2026-11-16, P3 (demoted 2026-11-24 under the 2026-11-20 materiality rule; was P1). CLBK 2026-07-21 (x2.2, probably a share exchange) and ATRO 2026-06-15 (x1.2, ambiguous) show level breaks with no corporate_action row; D7 split_continuity cannot see an unrecorded break. The CLBK row is recorded (2.2, calendar_audit) and the sweep gate that closes the class landed; the ATRO disposition and the todo's gates are not re-verified. |
| [624](pending/624-reused-ticker-history-in-canonical-sn.md) | New 2026-11-17, P3 (demoted 2026-11-24 under the 2026-11-20 materiality rule; was P1). SN canonical mixes Sanchez Energy (2016 to 2019) with SharkNinja (from 2023-07-31): a reused ticker. Ruling: the pit ticker map owns identity, no proven-start floor. SNEX and RTX are applied; open: SW and the SLM identity contradiction, which wait on the pit map's identity. |
| [601](pending/601-slop-audit-measure-then-delete.md) | New 2026-11-09, P3 (demoted 2026-11-24 under the 2026-11-20 materiality rule; was P1). Slop audit: measure which of the 311 `feature_vectors` columns have no reader, check the duplicate feature factory, delete what Massive replaces; delete only on evidence. Merged 2026-11-26: the vulture whitelist triage (todo 309, about 163 whitelisted functions and methods) and the Ring 0 `metrics.py` domain-name cleanup (todo 465); file lists are in the todo body. |
| [631](pending/631-void-the-gsat-2021-02-08-operator-row.md) | New 2026-11-17, P3. The GSAT 2021-02-08 operator row (0.609687, Alpaca route) contradicts every vendor's 2021 move; measure, then void and reselect GSAT. |

**Kernel and feature code (phase 186 follow-ups)**

| Todo | Why now |
|---|---|
| [550](pending/550-promote-research-kernel-rolling-percentile.md) | 186-27 gate met; the 0.5 warmup is now NaN. Vectorize `_price_percentile_series_full` under the parity test and delete `rk_price_percentile`. Edits the rebuild code key: lands after the corpus rerun. |
| [475](pending/475-macro-kernels-branch-on-symbol-and-timeframe-names.md) | `kernels/macro.py` and `residual.py` still hardcode SPY/TLT and the six-symbol basket. Move membership to ITR tags read at the builder edge, bit-identical. Edits the rebuild code key: lands after the corpus rerun. |
| [472](pending/472-ctf-source-builder-hard-coded-constants-not-apr.md) | Remaining non-APR numbers (the HMM part is gone): the S/R default lookback 120 and strength cap 2.0 in `vp_sr.py` (seed equal APR values; the `1e-10` guards are mathematical, exempt, and go to todo 680's `EPS` cleanup). Edits the rebuild code key: lands after the corpus rerun. |
| [680](pending/680-feature-code-audit-delete-dead-helpers-one-config-declaration-split-on-seams.md) | New 2026-11-26, P3. Read-only feature code audit: delete the test-only `_rsi` and HMM obs builders, the unreachable `vol_ratio` branch and the unstored `days_to_month_end` compute; one declaration per config key (four copies today); split `price.py` and `vp_sr.py` on their section seams in one re-pin batch with 472, 474, 475, 550. Edits the rebuild code key: after the pilot, `stage_1d` and 471. |
| [458](pending/458-family1-slot-alpha-as-execution-timing-overlay.md) | Untested: family 1 slot alpha as entry and exit timing on a slower book's recorded trades. Blocked until a daily book with a trade list exists; drop the IBKR BRK.B note. |

**Regime and IC engine**

| Todo | Why now |
|---|---|
| [108](pending/108-hmm-multi-seed-restart-best-likelihood.md) | Walk-forward HMM fits one seed per segment. First measure seed spread (log-likelihood, label agreement) read-only on a few names; implement only if fits are brittle. Edits the rebuild code key: next rerun pin. |

**Process and tooling**

| Todo | Why now |
|---|---|
| [681](pending/681-per-run-memory-peak-from-the-run-cgroup-and-a-host-memory-budget.md) | New 2026-11-26, P2. No run exposes its true memory peak. Run each heavy job in a transient user scope, read `memory.peak` from the surviving parent (a SIGKILLed child still leaves it), write a node_exporter textfile and a status line; Grafana beside the DIMM and MemAvailable series; then a measured host budget. Part A landed 2026-11-26 (4d4dc6599; live probe: SIGKILLed 300 MiB child left a 305 MiB peak, exit 137; wrapped unit run served 7 series by node_exporter). Part B landed 2026-11-27 (4410528bd, test fix 03613536f); part C landed; D (budget) fills in as the first real peaks arrive. Was: B (launcher wiring) waits for the pilot, `stage_1d` and 471 launchers to be quiet; nothing in a pin closure. |
| [383](pending/383-gsd-sdk-state-and-gap-checker-hardcoded-field-path-assumptions.md) | GSD upstream bugs (`state.planned-phase` no-op, gap-checker's bare CONTEXT.md, `phase.add` reusing a number). Send upstream feedback once, then close; no local patch. |
| [324](pending/324-gradient-vocabulary-naming-check-unenforced.md) | The gradient-scale vocabulary (naming-system section 7) is not enforced anywhere. Add a `gradient_scale` registry namespace and a CI check on `FeatureVector` field names and APR keys. The `has_live_source` blocker is moot. |
| [331](pending/331-vocabulary-drift-auditor-windowed-query-blind-spot.md) | P3, no merge. The vocabulary drift auditor runs by hand (last run 2026-09-10) and its 30-day window misses rare codes. Decide scheduling and all-time scope together; at minimum document the limitation in the CVR doc. |

**Registries and universe**

| Todo | Why now |
|---|---|
| [272](pending/272-instrument-tag-peer-group-coverage-auditor.md) | No audit of thin `instrument_tags` peer groups: convertible and fx_usd are N=1, fi_preferred and fx_commodity N=2. Build it with the regime rebuild, before any regime-segmented counted spec. |
| [397](pending/397-universe-dimension-views-and-instruments-boundary-test.md) | Add only the CI boundary test on raw `FROM instruments` reads, with an allow-list. Drop the dimension views: they edit `settings.py`, inside the rebuild closure, and research now reads `universe_membership`. |

**v2.x retirement**

| Todo | Why now |
|---|---|
| [509](pending/509-v2x-remainder-after-185-45-fvp-coupling-dashboard-surface-ml-chain.md) | Cleanup: remove the vacuous I7 CI step (it scans a missing `src/intelligence/trading/`) and pre-commit check 3, the trading entries in `tools/duplicate_test_allowlist.txt`; `shadow_registry` (36 rows, no code reader) needs an owner call (owner-action-sheet item 8). Verified 2026-11-26: `.github/workflows/ci.yml` line 114 (I7) scans `src/intelligence/trading/`, which does not exist, and `tools/duplicate_test_allowlist.txt` still lists `tests/unit/intelligence/trading` entries. Small, P3; docs-only batch edited no module. |
| [621](pending/621-collapse-massive-step7-evidence-after-part-f.md) | Unblocked: Part F closed (eb734e451). Collapse `logs/massive_step7` (1.2 GB) to a summary card plus sha256 files and the evidence it cites; add README stubs for the phase179, phase181 and massive_step7 run dirs (619's remainder). |
| [637](pending/637-rerun-legacy-batteries-for-true-pass-records.md) | Rebind E17 battery records for family 1, periodicity and family 2 before their next real run (457, 460, 442). `LEGACY_WAIVERS` is empty, so `static_gate` refuses them until then. Not on the path of H-C, 9 or 10. |
| [639](pending/639-recertify-fitted-book-certificate-after-e17-memory-fix.md) | New 2026-11-18, P2, owner lead. The fitted-book certificate is void on purpose after the E17 memory fix; rerun the battery and recertify. Not blocking: no first counted family uses a fitted book. |
| [642](pending/642-delete-the-fetcher-lock-guards-the-ledger-lock-replaced.md) | After 640, delete the coverage-rebuild writer-unit refusal and the audit's fetcher-lock poll, plus their APR keys (migration). Edit the audit only while its timer is quiet. |
| [643](pending/643-alpaca-asset-list-witness-for-the-closed-list.md) | B-A witness: capture Alpaca's asset list nightly into raw and measure whether the asset id is stable first. Not blocking. Keep any edit to `src/intelligence/bars/*` until after the rerun pin (inside the code key). |

**Not in this list:** `deferred/` (phase-gated or recompute-batched) and `completed/`.
| [616](pending/616-ohlcv-coverage-zero-no-raw-update-temp-spill.md) | The NOT EXISTS anti-join in `_ZERO_NO_RAW_SQL` still spills: the symbol-scoped rebuild call (`ohlcv_coverage_writer.py:412`) wrote about 19 GB of temp blocks in 2 calls since today's stats reset. Rewrite the shape with a row-equal test. Ops efficiency only. |
| [531](pending/531-schema-names-without-glossary-entries-rename-or-gloss.md) | Three of nine relations are already dropped. Verify and drop `parity_certification_state` (no code reference: verified 2026-11-26, it appears only in `tests/integration/fixtures/schema_baseline_2026-11-05.sql`; small, P3). Gloss `integrity_monitor`, `dlq_events`, `remediation_ledger` and `instrument_metadata` (gloss only: renaming `integrity_monitor` moves the pin). `market_data_5m` stays the D-191-H deferral. |
| [481](pending/481-rates-regime-curve-label-measures-rate-direction-not-slope.md) | The rates curve tier tracks the 10-year yield direction with the slope sign inverted; option 3, the four-quadrant label, is resolved. Builds only with a `market_regimes` rebuild and the null-arm control; no counted family reads it today. |
| [474](pending/474-kernels-fill-neutral-values-for-undefined-instead-of-nan.md) | Most fills are fixed (8df1ac702, ac32408ab). Left: the first HTF bar's zero return, `ext_ctf_*` 0.0 before the first HTF close, and the masked cold prefixes in price and volume. Kernel edits: they belong to the post-rerun code window. Materiality unclear. |
| [504](pending/504-dividend-event-writer-source-registry-and-per-symbol-failure-policy.md) | Owner request 2026-10-07. Failure policy done (68f836774, todo 541). Left: retire the dead IBKR source and its default (`_DEFAULT_CLI_SOURCES`), and reconcile Yahoo against Massive pairwise by a source registry. Verified 2026-11-26: `services/dividend_event_writer.py:104` still has `_DEFAULT_CLI_SOURCES = ["ibkr", "yahoo"]` and `tests/unit/services/test_dividend_event_writer_massive.py:117` pins it; small, P3. Dividends already reach `panel.total_return` through the coverage rules. |
