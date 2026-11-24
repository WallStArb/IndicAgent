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

## Critical path (current 2026-11-23)

Next actions in order: `.planning/STATE.md`, Handoff, "Queue" (lanes A to D: the StepM attestation and selection, the `reversal_21` R-1 disclosure, todo 653, then families 9 and 10; data integrity, corpus rerun and hygiene lanes follow). The dated Massive plan call (renew or lapse before about 2026-12-10) is in `docs/plans/2026-11-15-massive-plan-lapse-deadlines.md`.

Sequence: `docs/plans/2026-09-26-unified-research-to-production-design.md` section 16; session lanes
and the lead's order in `.planning/STATE.md`. The goal is to test features, factors and regimes as
soon as the data is complete. The owner rule (2026-10-30, 2026-11-04) holds: no real-data hypothesis
test and no corpus compute until the data gate passes. The gate is now Massive admission (todo 600),
not IBKR coverage.

| Lane | Order |
|---|---|
| Data (phase 191 done, 192 Massive) | Raw loads 2026 to 2003 done and gated 2026-11-11; 8a checks done as the admission record (r5 pushed a0a9eb851, gates nothing per owner ruling; first verdicts 2014-2026 ok both timeframes) -> the placed-span load and the A11 witness gate -> step 7 done (2026-11-16) -> data gate 186-32 -> the 584 pin and one corpus rerun -> 186-28 fresh IC run. The IBKR deletion (Part F) lands only after the rebuild proves itself; todo 574 (Tradier removal) done 2026-11-12 |
| Build (phase 186, 25/29) | 186-17 Task 2 unblocked (the fetcher-gap condition died with the IBKR fetcher); 186-26 rerun waits on the data gate (rows discarded 2026-11-04, migration 569); 186-27 landed (migration 570); 186-28 after the rerun, tf set from 471 |
| Research inputs (phase 184) | Plans 01-10 landed; 12 (dry S0 on real data) waits on the rebuilt table; 13-14 on todo 482; admission holes are todo 588 |
| Research core (phase 187) | Selection core plans 08-15; governance (16-18) after the first feature family; E17 v2 battery (todos 547, 586) before StepM selection and the book rule |
| Testing | Waits on the clean-data rule (E21 adopted 2026-11-13): family 2, daily price-only families 441 + 423, then 440; feature and regime families after the rebuild and 184 |
| Quick, independent | 443 (remaining item sequenced after the 186-26 rebuild; see its P2 row below) |

Unverified against live state: every P2 and P3 row (the P0 and P1 rows and the pre-rerun window rows 558, 466, 461, 470, 471, 448, 564, 583, 588 Part C and 608 were checked 2026-11-24). Treat the "why now" text of the unchecked rows as possibly stale.

## P0: Gates the data gate or the first counted test

| Todo | Why now |
|---|---|
| [584](pending/584-corpus-rerun-fix-manifest.md) | P0, the critical path. One list of stored-value fixes before the pin moves, then one corpus rerun. Every code item has landed, the stage 2 membership is rebuilt and repinned (22be5378a), and the scope-1d data gate and `d2_landed` pass (ledger 2026-11-21e to 21g). The 1d-first run a4f6ad40 stopped at the pilot feature column screen (todo 652, P3, parked); the daily counted run waits on the owner's E21 ruling. Readiness table in the todo. |
| [588](pending/588-184-admission-holes-from-wave-review.md) | P0, gates the first counted test with an input member. Parts A and B landed 2026-11-04. Part C (184-12 real-data dry S0 build) needs stored 1d, 1h and 5m columns, so it runs after a scope-all rerun, not the 1d-first run. |
| [600](pending/600-massive-flat-files-all-history-vendor.md) | P0, step 7 done through D4 (2026-11-16). Canonical is Massive then Alpaca. Part F is closed (no `ohlcv_raw` ibkr rows from 2003-09-10). Remaining before the plan lapses about 2026-12-10: the renewal decision, filings sizing by 2026-12-01 and the nightly leaf (items 1, 5, 7, 9, 10); the off-site copy was declined by the owner. |

## P1: High value, fully unblocked or on the critical path

**Unblocked by the Massive loads (run now)**

| Todo | Why now |
|---|---|
| [649](pending/649-splits-after-the-massive-seam-need-a-detector.md) | P1. SNDK 8:1 split (ex-date 2026-11-20) failed the nightly on a basis-change flag; second post-seam split in two days after VIXM. The SNDK row is applied (91c77af37); measure the base rate, then decide a proposal-only detector from the Alpaca corporate-actions feed. Detector built 2026-11-23 (services/split_feed_auditor.py, migration 612); the timer is not yet installed. |
| [609](pending/609-stage2-universe-from-massive-pit-liquidity-rule.md) | P1. Stage 2 point-in-time universe (preregistered). s0 to s8 are done, membership rebuilt (1,042,561 rows, 12,857 securities) and pinned (22be5378a, todo 648 closed); the 2004-2015 shortfall against the 2,950 floor is disclosed, not gated. Left: the corpus rerun on the pin (todo 584). |
| [614](pending/614-refactor-audit-2026-11-14.md) | New 2026-11-14, P1. Sixteen ranked refactor candidates from the lead audit. Rows 1, 2, 6, 8 and 12 (the rebuild code key hole, the survivorship caveat that reads zero after step 7, dead v2.x schema, zero-fill in the streaming path) land before the 584 run is created; 3, 9, 10, 11 and 13 after step 7 proves itself. |
| [615](pending/615-split-rows-missing-for-renamed-names-ln2-level-shift-check.md) | New 2026-11-14, P1. SGH placed under PENG shows a 2-for-1 level step (2022-02-02) and `corporate_action` holds no split row for PENG or SGH; a check over the placed pairs finds every unexplained ln k step. The PENG 2-for-1 row is recorded (todo 630); the ln k check over the other placed pairs is unverified. Its gate (before the d2-v6 rebuild at step 7) has passed. |
| [622](pending/622-unrecorded-level-breaks-clbk-atro-and-d7-blindness.md) | New 2026-11-16, P1. CLBK 2026-07-21 (x2.2, probably a share exchange) and ATRO 2026-06-15 (x1.2, ambiguous) show level breaks with no corporate_action row; D7 split_continuity cannot see an unrecorded break. The CLBK row is recorded (2.2, calendar_audit) and the sweep gate that closes the class landed; the ATRO disposition and the todo's gates are not re-verified. |
| [624](pending/624-reused-ticker-history-in-canonical-sn.md) | New 2026-11-17, P1. SN canonical mixes Sanchez Energy (2016 to 2019) with SharkNinja (from 2023-07-31): a reused ticker. Ruling: the pit ticker map owns identity, no proven-start floor. SNEX and RTX are applied; open: SW and the SLM identity contradiction, which wait on the pit map's identity. |
| [627](pending/627-sweep-bad-bar-pairs-2007-06-13.md) | New 2026-11-17, P2. Five names show a one-day reversal pair on 2007-06-13 and 2007-06-14 (A3 sweep); a vendor day-file bad bar per name; measure the class, list the bars or a day rule. |
| [631](pending/631-void-the-gsat-2021-02-08-operator-row.md) | New 2026-11-17, P3. The GSAT 2021-02-08 operator row (0.609687, Alpaca route) contradicts every vendor's 2021 move; measure, then void and reselect GSAT. |

**Pre-rerun window (lands before the corpus rerun at the new pin; 571 right after it)**

| Todo | Why now |
|---|---|
| [558](pending/558-pre-rebuild-feature-pass-decisions-and-registry-cleanup.md) | Add-list landed (584-8) and rank_z retired (035c11902). After the corpus rerun: measure `ret_acf1_z` against `ret_autocorr_1` and fill `redundancy_group` (0 of 424) from measured correlations; coordinate with the 571 concept reset. |
| [466](pending/466-regime-columns-lookahead-dependents-303-304-benchmark.md) | The research read refuses non-rebuild regime columns (`feature_inputs.py:494`). Open: annotate the 303/304 cards and ledger rows with the lookahead bias and rerun their benchmark on the rerun's columns; `feature_matrix.py` was deleted with todo 554. |
| [461](pending/461-gap-z-read-the-next-bars-open.md) | `gap_z` lookahead fixed in code (186-12, db4ef4e80). Annotate ledger lines 171-179 and the n1 combiner card's fold-1 G1 breach now; re-measure `gap_z` IC on the corpus rerun's rows. |
| [471](pending/471-ic-measure-intraday-full-universe-memory-and-time.md) | Ruled 2026-11-24: scope-1d pin width 16 with `ic_tfs` = 1d only; no 5m or 15m until 667 (time chunks); 1h only at width 4. Open: record the 25-name `--dry-run` RSS at widths 4, 8, 16 and 32 after the block 2 rerun, then pin the width in the scope-1d APR. |
| [583](pending/583-hmm-regime-null-on-whole-names-in-the-1d-rebuild.md) | K=3 decided (E20, migration 566, 07d980e87); HMM NaN is judged only on written segments (661). After the rerun: measure the K=3 refusal share across the full 1d universe and declare regime-unknown names before any regime-segmented 1d spec. |
| [571](pending/571-reset-the-concept-layer-after-the-186-26-rebuild.md) | New 2026-10-30, P1, owner-approved, runs after the 186-26 rebuild and todo 564's batch. Demote the 306 `active` features to `candidate` through `ConceptRegistryService` and clear the 590 old evaluations; back up first. |

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
| [547](pending/547-e17-hac-lag-for-overlapping-targets.md) | E17 daily statistic landed 2026-10-30 (flat-top kernel plus influence series); daily battery down from 40+ size failures to 3 marginal ones. Owner decision: certify reversal members and book, hold `reversal_5_skip1` and momentum (S1 drift), or hold the family. B3 power still open. |
| [586](pending/586-persistent-battery-gating-cell-failure.md) | New 2026-11-04, plan 184-05. Ten gating cells of the persistent-predictor E17 battery exceed size (long tau, 1d and 5m sources, 21 and 63 smoothing, the hourly book, rk_price_percentile 126); oversize grows with persistence, consistent with an HAC lag that does not scale with weight persistence (cf. 547). Members on those routes stay refused. |
| [440](pending/440-generated-family-grammar-daily-ohlcv-931-names.md) | Unpauses at 191-20's 1d re-derive (owner 2026-10-27). Attempt 3b (ledger family 12): a registered grammar over daily OHLCV primitives, in-fold selection plus ridge, never materialized. |
| [435](pending/435-wire-feature-vectors-into-research-panel-all-timeframes.md) | Built as phase 184 B1 (plan 184 now, owner 2026-10-27). The research layer never reads `feature_vectors` (both families use raw 15m returns), against the adopted architecture. Wire features into S0 at 5m/15m/1h/1d with pinned windows, masked warmup and a coverage floor, after the 186 rebuild. |
| [601](pending/601-slop-audit-measure-then-delete.md) | New 2026-11-09, P1. Slop audit: measure which of the 311 `feature_vectors` columns have no reader, check the duplicate feature factory, delete what Massive replaces; delete only on evidence. |
| [603](pending/603-base-feature-scouting-and-data-adjacency-register.md) | New 2026-11-09, P1. Lowest rung of research: a data adjacency register (what sources serve versus what we store), admission gates that never peek at returns, and rejections recorded as registry rows; design in `docs/ideas/base-feature-scouting-and-the-research-ladder.md`. |
| [636](pending/636-daily-residual-null-battery-rerun-with-m3.md) | New 2026-11-18, P1. The daily residual E17 battery pass: A4 (2026-11-21) dropped M3 after the 5,000,000 and 6,000,000 pooled blocks failed on it; the reduced family (M1, M2, `reversal_21`, their book) passed pooled on seed bases 7,000,000 and 8,000,000 and the record `research/battery_passes/daily_residual_2026-11-21.json` is bound (the H-C seasonality record was rebound at the same commit). Left: the E21 clean-data lift, total-return coverage and the first counted run. |
| [634](pending/634-book-and-power-path-bind-session-dates-for-calendar-members.md) | New 2026-11-18, P2 in effect. The book and power-calibration paths do not bind session dates for calendar members, so a book with an H-C member raises a TypeError. Loud, and no book holds one yet. |

## P2: Real value, not urgent

| Todo | Why now |
|---|---|
| [663](pending/663-family-10-volume-shock-kernels-spec-and-run.md) | New 2026-11-22, P2, spec, members, battery and run blocked on todo 653 (member panel source plus S1 residual e). Kernels on main; data gates 563 and 560 cleared, prereg gates 4 and 5 open (heavy slot). |
| [665](pending/665-ic-measure-feature-list-reads-the-dormant-featurevector-dataclass.md) | New 2026-11-24, P3. `ic_measure` chooses its feature columns from the dormant `FeatureVector` dataclass plus table extras; take them from `feature_vectors_numeric_columns()` and refuse a registry column the table lacks. Results unchanged. |
| [666](pending/666-ic-measure-targets-are-price-only-and-skip-dividends.md) | New 2026-11-24, P2. `ic_measure` targets are price-only open-to-open returns although every 1d horizon crosses sessions (CLAUDE.md: such a spec declares `panel.total_return`). Decide before the first IC run after the corpus rerun: measure the effect on `dividend_yield`-linked columns and on the overall IC rank, then disclose or move to total return. |
| [667](pending/667-ic-measure-time-chunk-mode-for-intraday-tfs.md) | New 2026-11-24, P2. `ic_measure` holds a whole tf in memory (targets of every horizon, a dense [bars, names, width] block): 15m needs width 4 or less and 5m fits at no width. Time-chunk mode, bit-identical on tfs that fit; prerequisite of the scope-all pin. |
| [668](pending/668-ic-measure-checkpoint-grain-per-horizon-or-block.md) | New 2026-11-24, P2 (todo 470 merged). A kill loses a whole (job, tf) unit, hours at 15m and 5m; checkpoint per horizon or block and cache the digests if measured to matter. Prerequisite of the scope-all pin. |
| [656](pending/656-integration-test-harness-redesign.md) | New 2026-11-22, P2, blocked on the residual run being counted. Integration harness redesign: a capped disposable test cluster on the production image (port 5442; 5433 is ssfi's), planned in `docs/plans/2026-11-23-integration-harness-plan.md`: delete 17 integration functions first, then the cluster, then the baseline bump, a database per session copied from a hashed template, the six live-data tests deleted (monitoring belongs to the D7 audit), the schema sync kept behind `--live-catalog`, an interim session lock, a baseline bump that closes 655, CI after 654. |
| [654](pending/654-database-image-timescaledb-ha-with-pgvector-and-toolkit.md) | New 2026-11-22, P2, owner direction, blocked on a planned rebuild window. Move the database from the Alpine custom image to the pinned Debian `timescaledb-ha:pg18` (pgvector and toolkit included) with a `C.UTF-8` database, by dump and restore after an ubuntu2 rehearsal; the standby and WAL archive move with it. Not before the counted runs finish. |
| [653](pending/653-family-9-close-member-input-spec-battery-and-run.md) | New 2026-11-22, P2, blocked on the daily residual and H-C seasonality runs being counted. The family 9 kernel is on main; the close member input (edits two runner statistic functions, so both existing battery records rebind in the same commit), the spec, the battery and the run follow. |
| [650](pending/650-forward-feed-covers-a-quarter-of-the-stage-2-members.md) | Nightly reads only the 1,529 active names; 4,615 stage 2 members get no bars after the 2026-11-16 seam. State the book-holdable set, then choose an SOP stage 2 exception or a separate feed. Due before the first book freeze, not the pin. |
| [559](pending/559-cointegration-spread-family-preregistration.md) | New 2026-10-28, owner reopened the cointegration concept (ledger section 2). Pre-register a spread family tested on its trading statistic (static and Kalman hedge ratios, OU half-life), disclosing the 2026-08-07 pilot and the 471-pair screen as seen data; no look before the pre-registration. Placement and the draft are the assistant's (needs an Opus or Fable pass). |
| [548](pending/548-style-spread-regime-slot-and-time-series-construction.md) | New 2026-10-27. The owner's participation-state idea (RSP/SPY and style spreads) cannot run through the runner: S7 has no regime input slot (part A) and the runner is R1 only (part B's time-series book). Part B's synthetic power check comes first and needs neither. |
| [536](pending/536-forward-span-read-guard-for-ad-hoc-queries.md) | Ad hoc SQL past `alpha.validation.oos_start` is unrestricted and unlogged, which can void the one-spend forward confirmation. Add a capped role or view, or audited reads, with a sink and a test. Must land before the first book's forward confirmation. |

**With phase 186 and the streaming revival**

| Todo | Why now |
|---|---|

**Research follow-ups (paused with the attempts)**

| Todo | Why now |
|---|---|
| [460](pending/460-family1-auction-price-check-and-auction-to-auction-hold.md) | New 2026-09-29, family 1 iteration 4. About two thirds of the open-plus-close book's gross depends on the stored 09:30 open being a tradable auction price (unchecked); then test an open-auction-to-close-auction hold, which crosses no spread. Decides whether a standalone slot book can be net positive. |
| [456](pending/456-todo445-rerun-zero-commission-and-longer-horizons.md) | New 2026-09-29, owner review of todo 445. The 5m name set (`ret_autocorr_1`, `sweep_detected`) was pruned by a hurdle that charges $0.0035/share commission, but the live book will likely use a zero-commission broker; horizons also stop at half a session. Part A rederives the name set at zero commission from recorded p-values (no new look); Part B tests multi-day horizons against 1h/1d counterparts (counted look, after the 185/186 pause). |
| [457](pending/457-family1-slot-subsets-through-the-runner.md) | New 2026-09-29, family 1 iterations 2-3 (iteration 1, the horizon specs, already ran through the runner). The opening and closing slot subsets, the 30-cell conviction grid and the 32-cell liquid-close grid ran outside the runner, so they are not in the E18 selection universe. After phase 187 adds a slot-subset mask and the keep gate, rerun them in exploration mode on the 233 and the 201-name sets. |
| [560](pending/560-volume-kernels-span-the-volume-basis-seam.md) | New 2026-10-28, P1. The volume guard is transitive (downstream kernels masked over their memory), path-dependent kernels run through a seam, a dropped bar masks to the kernel's reset anchor or past a 5% dropped share, and the ctf series no longer collapses to neutral; four independent reviews (two Opus). The launch-gate framing is stale (stage 2 launched 2026-10-31); the review question is closed (four independent reviews, family final at 107f9a395); open: research panel provenance (184). |
| [437](pending/437-first-cut-cost-model-commission-and-spread.md) | Paused (build first). Promotion needs positive net expectation; today only flat bps bands exist. Commission (likely zero at the execution broker) plus validated Abdi-Ranaldo spread, as distributions. |

**Data and ingestion**

| Todo | Why now |
|---|---|
| [516](pending/516-spin-off-action-type-as-a-research-layer-distribution.md) | New 2026-10-08, from 185-51 (todo 515 option 1). CTVA is held and frozen at its raw 2026-09-30 bar: a `spin_off` action type that d2-v2 never applies as a split, a d2-v2 rule that keeps the pre-restatement observations, and the distribution as a research-layer total-return event like dividends (428); then release the hold. Also ELE, IESC, MSM, TIGO (write names without a 1d symbol row, still true) and d2-v2's one-session effective_date offset. Gate: before CTVA's hold is released and before 186-26 reads CTVA. |
| [498](pending/498-otel-collector-drops-every-job-labelled-metric.md) | New 2026-10-06, found at the 189-06 cutover. The OTel collector drops every metric carrying a `job` label (`duplicate label names`, since 2026-06-22), so `job_completed_total` and the fetcher's staleness gauge never reach Prometheus and the D-06 oneshot contract is dark. Rename the label or stop the constant `job` label; sweep dashboards and alert rules. |
| [454](pending/454-ultra-thin-traded-series-treatment.md) | New 2026-09-28, filed from the 185-10 historical scrub pass (todo 052 defect-class sweep; docs/research/scrub-historical-pass.md). Ultra-thin traded series: RCAT clears volume>0 for years at volume <= 30 shares; 6 of the top 20 largest 1d moves are this one name; no scrub rule fires (too sparse for the 61-bar window). Measure the class distribution, then decide with the owner: universe eligibility dimension vs informational rule. Raw bars untouched either way (D-09). |
| [589](pending/589-bulk-load-unit-scoped-recompress-for-renamed-units.md) | New 2026-11-04, P2, from the 584 item 4 review. A completed unit renamed after its `feature_vectors` chunk compressed (restated bar, APR change, onboarding) is refused loudly by `bulk_load`; add a unit-scoped decompress-load-recompress path under the headroom guard. Matters from the first restatement after the rerun's chunks compress. |
| [597](pending/597-intraday-bars-not-scrubbed-nightly.md) | New 2026-11-05, P1. The 594 rules reach 1d nightly but new 5m/15m/1h bars are scrubbed only by a manual pass, so a bad intraday print is served until someone runs it; the grid derivation timer runs the scrub on what it touched. Also measure adjacent bad-print pairs (CORT 2007-09-11). |
| [606](pending/606-feature-registration-wired-into-the-add-list-path.md) | New 2026-11-09, P2. Close the forgotten-concept-row class: wire feature registration into the add-list path plus a CI reconciliation (every stored column has a concept row; every active row has a column or a kernel-only annotation). Found by the 601 reconciliation (two live instances, fixed by migration 585). |
| [568](pending/568-docs-cleanup-outdated-thresholds-gates-and-v2x-content.md) | New 2026-10-30, P2. Candidates and the 547/560/564 todo sweep done 2026-10-31 (see the todo's status section); open: the reset follow-ups, which need the owner's one-line freeze lift on ledger sections 2 and 4, then reduce the voided-results docs to status + pointer. |
| [598](pending/598-alpaca-nightly-logs-to-journald-not-its-log-file.md) | New 2026-11-06, P2. The Alpaca nightly never calls `setup_service_logging()`, so per-session debug lines go to journald (about 1 GB per re-ask session); log to its own file at info and aggregate the per-row line. Lands with the next nightly-area change, in a worktree. |
| [443](pending/443-postgres-exporter-chunk-scrape-cost-and-idle-in-transaction-timeout.md) | The postgres exporter's per-chunk scrape is the top database consumer (305 min in 3 days) and the idle-in-transaction timeout is 1 hour. Two config changes, measured before and after. Item 1 (exporter scrape) applied 2026-11-01 and verified: exporter cost now about 1.6 min/day, out of the top 5. Remaining: the idle-in-transaction timeout cut, sequenced after the 186-26 rebuild ends and compression 1078/1076 re-enable (the rebuild's compute workers legitimately idle in transaction; the timeout is reloadable, no restart). |
| [520](pending/520-future-timestamp-guard-on-ingested-bars.md) | New 2026-10-09. The writer guard landed in 191-02 (`services/ohlcv_raw_writer.py`, APR `threshold.bar_integrity.future_bar_tolerance_s`, tested). Open remainder: the D7 1d condition, explicit deferral D-191-H (owner acknowledgement pending). |
| [612](pending/612-d2v6-no-unserved-primary-for-dropped-placeholder-only-sessions.md) | New 2026-11-13, P2. A session whose only raw answer is a dropped zero-volume placeholder gets no bar (correct) and no `unserved_primary` record; outcome-neutral for D1. Decide after the 186-26 rebuild: count the class in the daily report or accept and document. |
| [522](pending/522-alpaca-execution-mechanics-shadow.md) | New 2026-10-09, pilot Workstream B. Paper-only order lifecycle validation (20 single-share orders, EOD flat, idempotent reconnect) plus the fixed slippage instrumentation spec. Single session, zero risk, independent of the 189-10 lanes; fastest path to measured own-flow slippage. |

**Held under the IC proposal and in-fold selection methods**

| Todo | Why now |
|---|---|
| [038](pending/038-cross-sectional-collinearity-diagnostic.md) | Held under the `ic_proposal`/`in_fold_selection` methods: cross-sectional feature collinearity diagnostic against IC. |
| [039](pending/039-tag-stratified-ic-population-check.md) | Held under the `ic_proposal`/`in_fold_selection` methods: population-count check before tag-stratified cross-sectional IC. |

**Regime and IC engine**

| Todo | Why now |
|---|---|
| [420](pending/420-market-regimes-orphan-rows-from-pre-tradeable-writer.md) | Triage 2026-09-26: regime refit bundle anchored on 248. New 2026-09-24 (179 V4). 186-18 landed the atomic per-(group, tf) replace with a shrink guard and measured it: 3.51M orphans (1.22M weekend, 2.29M weekday), J = 510,835 join feature_vectors, so the cleanup run (`--accept-orphan-delete=N --accept-changed=M --reason`, then VACUUM) waits for 186-20's parity report and is owned by the 186-26 executor. |
| [504](pending/504-dividend-event-writer-source-registry-and-per-symbol-failure-policy.md) | New 2026-10-07. The dividend writer hard-codes Yahoo and IBKR in its reconciliation and metrics, and one bad symbol (PSKY) fails the unit nightly. Make sources a registry, reconcile pairwise, and fail the run only past an APR threshold with an alert. 191-10 moved its IBKR derivation to `ohlcv_raw` (`ohlcv_observation` is gone); the source registry and per-symbol failure policy remain open. |
| [512](pending/512-exclude-or-replace-names-whose-data-defect-is-not-worth-fixing.md) | New 2026-10-08, owner policy relayed (confirmation pending). Names whose data defect needs per-name hand work leave the compute set with a reason code and date; raw data stays; replacement only by a pre-fixed liquidity-rank rule through the onboarding SOP. Disclose in D0's survivorship bound. |
| [513](pending/513-nightly-process-contract-completion-before-judgment-and-a-pull-digest.md) | New 2026-10-08. D7 must report an incomplete fetch run as unjudged, not as data failures; document the nightly stage contract with markers; add a pull digest of last night while alerts are off; separate lane budgets. |
| [646](pending/646-record-splits-for-the-stage-2-names-before-the-pin.md) | P0. Split rows for the stage 2 names are landed with corrections (3,026 Massive reference rows plus 140 reverse splits); the member history audit is clean. Left: the strict sweep gated by materiality (todo 629), then the pin. |
| [644](pending/644-closed-list-disclosure-at-book-freeze-and-confirmation.md) | Required at the first book freeze: member counts per month-end after the stage 2 list, plus excluded newcomers once 643 lands. Put the code in the report, not in `universe_membership.py` (inside the rebuild closure). Owner-adopted. |

## P3: Hygiene, docs, process, performance (opportunistic)

**Dated**

| Todo | Why now |
|---|---|
| [658](pending/658-mypy-baseline-typing-debt-added-by-the-ci-resync.md) | 38 mypy baseline errors (mostly `research/construction.py`). Fix with real annotations only alongside the next planned research edit; blocked while the family 10 runs and the block 2 rerun are live (battery code keys). Run `repro_frozen` after. |
| [652](pending/652-1d-first-corpus-run-stopped-at-the-pilot-feature-screen.md) | New 2026-11-22, P3. Run a4f6ad40 passed data_gate and pin_gate (23/23) and stopped at the pilot feature column screen (G1 23, G2 84, G3 221, G6 10 on 25 first-alphabetical names). Do the pilot sample rule and 5% null gate fit a 1d scope; are the structure/zone NaNs warm-up? Parked, not on the counted-test path. |
| [483](pending/483-record-2026-midterm-forward-window-result.md) | Due after 2027-05-03: record the committed midterm window (S&P 500, 2026-11-03 to 2027-05-03) as one observation. The economic series end 2026-09-30 by design (todo 480, loaded by hand, timer disabled); refresh `YAHOO_GSPC_CLOSE` before then (run the oneshot by hand or enable the timer, an owner sudo step). |
| [487](pending/487-run-spec-synthetic-defaults-cannot-express-spec-gates.md) | `run_spec --mode synthetic` defaults (30 names, 400 sessions from 2006-07-03) cannot meet a real spec's power ratio or trading start; validate loudly, name the minimal flags, print each member's refusal reason on its RESULT line. |

**Kernel and feature code (phase 186 follow-ups)**

| Todo | Why now |
|---|---|
| [550](pending/550-promote-research-kernel-rolling-percentile.md) | 186-27 gate met; the 0.5 warmup is now NaN. Vectorize `_price_percentile_series_full` under the parity test and delete `rk_price_percentile`. Edits the rebuild code key: lands after the corpus rerun. |
| [475](pending/475-macro-kernels-branch-on-symbol-and-timeframe-names.md) | `kernels/macro.py` and `residual.py` still hardcode SPY/TLT and the six-symbol basket. Move membership to ITR tags read at the builder edge, bit-identical. Edits the rebuild code key: lands after the corpus rerun. |
| [477](pending/477-pivot-detection-repeated-per-row-across-structure-kernels.md) | Pivot detection repeats per row across the structure kernels (about 10 percent of batch time). A shared derived input, bit-identical; worth it only before a second corpus rerun. Edits the rebuild code key. |
| [472](pending/472-ctf-source-builder-hard-coded-constants-not-apr.md) | Remaining non-APR numbers (the HMM part is gone): the S/R default lookback 120 and strength cap 2.0 in `vp_sr.py`, the `1e-10` guards in `cross_tf.py`. Seed equal APR values. Edits the rebuild code key: lands after the corpus rerun. |
| [479](pending/479-service-timer-logs-root-owned-break-single-module-unit-tests.md) | `indicagent-regime-coverage-auditor` runs as root and writes a root-owned log, so its unit test fails when run alone. Add `User=bg` to the unit; install with the pending sudo operator steps. |
| [465](pending/465-ring0-metrics-module-holds-domain-named-instruments.md) | Ring 0 `metrics.py` holds 55 instruments. Delete the dead `LANGGRAPH_*` ones, move the feature and bar-auditor ones to Ring 1, then add a domain-word check; rides with 309. |
| [458](pending/458-family1-slot-alpha-as-execution-timing-overlay.md) | Untested: family 1 slot alpha as entry and exit timing on a slower book's recorded trades. Blocked until a daily book with a trade list exists; drop the IBKR BRK.B note. |

**Regime and IC engine**

| Todo | Why now |
|---|---|
| [108](pending/108-hmm-multi-seed-restart-best-likelihood.md) | Walk-forward HMM fits one seed per segment. First measure seed spread (log-likelihood, label agreement) read-only on a few names; implement only if fits are brittle. Edits the rebuild code key: next rerun pin. |

**Process and tooling**

| Todo | Why now |
|---|---|
| [394](pending/394-todo-number-uniqueness-not-ci-enforced-duplicate-389.md) | Extend the PRIORITIES link-integrity test: todo numbers unique across pending, completed and deferred, and each link label equals its file's number. Cheap guard against concurrent-session collisions. |
| [383](pending/383-gsd-sdk-state-and-gap-checker-hardcoded-field-path-assumptions.md) | GSD upstream bugs (`state.planned-phase` no-op, gap-checker's bare CONTEXT.md, `phase.add` reusing a number). Send upstream feedback once, then close; no local patch. |
| [309](pending/309-vulture-baseline-cleanup-backlog.md) | The dead v2.x `schemas.py` and `state_serializer.py` are deleted (456 whitelist entries). Remaining: triage the whitelisted functions and methods (about 163) and fold in 465's dead `LANGGRAPH_*` metrics. |
| [321](pending/321-feature-factory-config-test-fixture-consolidation.md) | One shared test builder for `FeatureFactoryConfig`; 6 test files still hand-type the literal (test_feature_factory, canary, p7, backfill, volume_profile, swing_fib). Fails loud when forgotten. Do it with the next field-adding change; tests only, the pin does not move. |
| [324](pending/324-gradient-vocabulary-naming-check-unenforced.md) | The gradient-scale vocabulary (naming-system section 7) is not enforced anywhere. Add a `gradient_scale` registry namespace and a CI check on `FeatureVector` field names and APR keys. The `has_live_source` blocker is moot. |
| [331](pending/331-vocabulary-drift-auditor-windowed-query-blind-spot.md) | The vocabulary drift auditor runs by hand (last run 2026-09-10) and its 30-day window misses rare codes. Decide scheduling and all-time scope together; at minimum document the limitation in the CVR doc. |

**Registries and universe**

| Todo | Why now |
|---|---|
| [272](pending/272-instrument-tag-peer-group-coverage-auditor.md) | No audit of thin `instrument_tags` peer groups: convertible and fx_usd are N=1, fi_preferred and fx_commodity N=2. Build it with the regime rebuild, before any regime-segmented counted spec. |
| [397](pending/397-universe-dimension-views-and-instruments-boundary-test.md) | Add only the CI boundary test on raw `FROM instruments` reads, with an allow-list. Drop the dimension views: they edit `settings.py`, inside the rebuild closure, and research now reads `universe_membership`. |

**v2.x retirement**

| Todo | Why now |
|---|---|
| [509](pending/509-v2x-remainder-after-185-45-fvp-coupling-dashboard-surface-ml-chain.md) | Cleanup: remove the vacuous I7 CI step (it scans a missing `src/intelligence/trading/`) and pre-commit check 3, the trading entries in `tools/duplicate_test_allowlist.txt`; `shadow_registry` (36 rows, no code reader) needs an owner call. |
| [621](pending/621-collapse-massive-step7-evidence-after-part-f.md) | Unblocked: Part F closed (eb734e451). Collapse `logs/massive_step7` (1.2 GB) to a summary card plus sha256 files and the evidence it cites; add README stubs for the phase179, phase181 and massive_step7 run dirs (619's remainder). |
| [637](pending/637-rerun-legacy-batteries-for-true-pass-records.md) | Rebind E17 battery records for family 1, periodicity and family 2 before their next real run (457, 460, 442). `LEGACY_WAIVERS` is empty, so `static_gate` refuses them until then. Not on the path of H-C, 9 or 10. |
| [639](pending/639-recertify-fitted-book-certificate-after-e17-memory-fix.md) | New 2026-11-18, P2, owner lead. The fitted-book certificate is void on purpose after the E17 memory fix; rerun the battery and recertify. Not blocking: no first counted family uses a fitted book. |
| [642](pending/642-delete-the-fetcher-lock-guards-the-ledger-lock-replaced.md) | After 640, delete the coverage-rebuild writer-unit refusal and the audit's fetcher-lock poll, plus their APR keys (migration). Edit the audit only while its timer is quiet. |
| [643](pending/643-alpaca-asset-list-witness-for-the-closed-list.md) | B-A witness: capture Alpaca's asset list nightly into raw and measure whether the asset id is stable first. Not blocking. Keep any edit to `src/intelligence/bars/*` until after the rerun pin (inside the code key). |

**Not in this list:** `deferred/` (phase-gated or recompute-batched) and `completed/`.
| [616](pending/616-ohlcv-coverage-zero-no-raw-update-temp-spill.md) | The NOT EXISTS anti-join in `_ZERO_NO_RAW_SQL` still spills: the symbol-scoped rebuild call (`ohlcv_coverage_writer.py:412`) wrote about 19 GB of temp blocks in 2 calls since today's stats reset. Rewrite the shape with a row-equal test. Ops efficiency only. |
| [531](pending/531-schema-names-without-glossary-entries-rename-or-gloss.md) | Three of nine relations are already dropped. Verify and drop `parity_certification_state` (no code reference). Gloss `integrity_monitor`, `dlq_events`, `remediation_ledger` and `instrument_metadata` (gloss only: renaming `integrity_monitor` moves the pin). `market_data_5m` stays the D-191-H deferral. |
| [481](pending/481-rates-regime-curve-label-measures-rate-direction-not-slope.md) | The rates curve tier tracks the 10-year yield direction with the slope sign inverted; option 3, the four-quadrant label, is resolved. Builds only with a `market_regimes` rebuild and the null-arm control; no counted family reads it today. |
| [474](pending/474-kernels-fill-neutral-values-for-undefined-instead-of-nan.md) | Most fills are fixed (8df1ac702, ac32408ab). Left: the first HTF bar's zero return, `ext_ctf_*` 0.0 before the first HTF close, and the masked cold prefixes in price and volume. Kernel edits: they belong to the post-rerun code window. Materiality unclear. |
| [582](pending/582-one-htf-derivation-rule-set-before-the-feed-returns.md) | Before any feed reactivation, construct HTF bars from one rule set (`session_grid`) or document streaming as base-bars-only; a revived live path reuses `compute_kernels` and the batch alignment builders. Edits to `bar_accumulator.py` move the pin. Blocked on feed revival. |
