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
git and in each todo's own closure note, not in this file.

## Critical path (reordered by the owner 2026-10-27: testing features, factors and regimes ASAP)

Sequence: `docs/plans/2026-09-26-unified-research-to-production-design.md` section 16, reordered
2026-10-27; session lanes in `.planning/STATE.md`. The goal is to start testing families with new
features, factors and regimes as soon as the data allows. Build first (2026-09-27) is lifted at
plan 191-20's 1d re-derive: from then on, the daily families and family 2 run while the
rebuild runs. Neither the research runner (`scripts/research/run_spec.py`) nor the rebuild
(`services/backfill_feature_factory.py`) imports a module that plans 191-22, 24 or 25 edit
(import closures checked 2026-10-27). The rebuild does import modules that 191-21
(`bars/sources.py`) and 191-23 (`services/rebuild_preconditions.py`) edit.

| Lane | Order |
|---|---|
| Data (phase 191, 18/25) | 191-19 Task 2 (residue report) -> 191-20 (owner approves the Tradier deletion; 1d re-derive) -> 191-21 -> 22 -> 23 (23 depends on 22's integrity_checks changes; decided 2026-10-27) -> start 186-26; 191-24 and 25 land while the rebuild runs |
| Build (phase 186, 25/29) | 186-17 Task 2 in a fetcher gap -> 186-26 rebuild (starts once 191-21..23 are in) -> 186-27 -> 186-28 (tf set from 471) |
| Research inputs (phase 184, plan now) | `/gsd-plan-phase 184`: S0 reads `feature_vectors` across timeframes through the causal align node (todo 435 is its B1). Runs on the rebuilt table once 186-27 swaps it in; planning and the align node's code need no rebuilt data |
| Research core (phase 187) | Selection core first: plans 08-15 (horizon and combining rules, pod books, recipe book, cards, contribution accounting, `generated_family`). Governance moves after the first feature family: 187-16 (DAG manifest, auditor inventory), 187-17 (per-writer DB roles), 187-18 (package renames), FK indexes. E17 v2 (todo 549, owner 2026-10-27): fixed-b critical values, then the step B battery rule and one fresh 4,000-session battery; StepM selection and the kappa 0.5 book wait on it |
| Testing (unpauses at 191-20's re-derive) | Family 2's one evidence run; daily price-only families 441 + 423, then 440; after the rebuild and 184: feature families, then regime-segmented ones (466 and 481 fold into the rebuild) |
| Quick, independent | 544 (gateway upgrade before 2026-12-15), 443, 438; 439's IC purge rides with 186 |

## P0: Fix soon (integrity/correctness gaps already surfaced)

| Todo | Why now |
|---|---|
| [549](pending/549-e17-v2-fixed-b-critical-values.md) | New 2026-10-27, owner decision. E17's HAC timing test runs at 5.40% size against 5% (99% CI excludes 5%), so it overstates evidence, and StepM inherits it. Fixed-b critical values as E17 v2, old records kept, family 1 re-scored as new rows; StepM selection and the kappa 0.5 book wait on it. 2026-10-28 finding in the todo: step A's interval ignored that an H0 simulation's arms share a panel (design effect 1.5 to 2.1), fresh 4,000-session runs show no excess, and fixed-b moves size at most 0.14pp at E17's bandwidth; rerun step A cluster-robust before building. Owner 2026-10-28: agreed; unit `e17-step-a-rerun` runs 16 gating cells x 600 simulations at 4,000 sessions once the 187-03 apply ends, and fixed-b is built only if the pooled interval excludes 5%. |
| [533](pending/533-bar-source-column-split-vendor-and-kind.md) | OWNER P0 2026-10-12, executing as phase 191. Steps 3 to 9 are done (plans 01 to 18): one raw table (`ohlcv_raw`, vendor plus kind, last-wins with the revision log), every reader and writer cut over, `ohlcv_observation`, the intraday archive and `market_data_ohlcv_old` dropped, and the close gates green (R6 exit 0, D7 same known failures or better, selection gate exit 0, repro_frozen bit-identical; 191-17-SUMMARY.md). Todo 530 closed with plan 18. Remaining: the Tradier retirement (step 10), plans 191-19 to 191-25. `scripts/ops/bars/ops_old_store_backup.py` and `data/backups/191/` are removed on or after 2026-11-12 (tracked in the todo's status section). |
| [545](pending/545-canonical-1d-alpaca-sip-primary-from-2016-d191q.md) | New 2026-10-27, owner decision D-191-Q. Canonical 1d becomes Alpaca SIP primary from 2016 with IBKR fallback, IBKR before, so deleting Tradier does not leave 1d on a non-consolidated volume basis with 494,567 lost 2016+ sessions. Alpaca 1d history backfill is running; then a full-universe comparison against Tradier, daily rule d2-v4, policy rows. Why now: all of it must land before plan 20 re-derives 1d. |
| [535](pending/535-raw-bar-table-review-findings-191-01-to-03.md) | Review findings from phase 191 (reviews of 01-03, 04-05, 06, 07 and three rounds of 07 fixes). Owner decision D-191-N 2026-10-14: last-wins ingress, restatement detector, all holds released. Fourth review: serve-time last-wins and basis-flag gating done; items 30-35 open (integration test, zero-grid sessions, GE retro flag, batched choices, waived chain). Open: IBKR re-serve of 4,569 keys (`logs/reserve_keys_191_07.json`, 103 session asks) when the fetcher may run; truncated-bar scan calibration and universe run; GE 2021-11 two-decimal span; fetcher `waived` chain cleanup; bar_derivation answered windows; complete-bar gaps in the campaign loader and the feature factory; 06 items 6 and 10 land in plan 08; derived 15m/1h re-derive when bar-derivation resumes. Rides with 533. |
| [433](pending/433-ibkr-daily-history-truncated-at-primary-listing-venue-change.md) | Silent wrong answer, owned by phase 185: SMART history starts at the last listing-venue move. 1d done (185-24): 39 moved 1d names inventoried, venue bars stored in D1 but unused (study failed), 30 of the 39 carry full history from Tradier, 9 IBKR-sourced names stay SMART-only (D7 `late_heads`), and `listing_venue` (D6) records every move. Stays open for intraday: recovery is gated on the 186 rebuild (todo 497). Venue rows become kind venue under 533. |
| [435](pending/435-wire-feature-vectors-into-research-panel-all-timeframes.md) | Built as phase 184 B1 (plan 184 now, owner 2026-10-27). The research layer never reads `feature_vectors` (both families use raw 15m returns), against the adopted architecture. Wire features into S0 at 5m/15m/1h/1d with pinned windows, masked warmup and a coverage floor, after the 186 rebuild. |

## P1: High value, fully unblocked or on the critical path

**Before the 186-26 rebuild**

| Todo | Why now |
|---|---|
| [555](pending/555-amihud-illiq-z-is-zero-under-the-absolute-std-floor.md) | New 2026-10-27, found closing todo 390. `amihud_illiq_z` is 0 on almost every stored row (100% on SPY and AAPL; 5 of 233 names non-zero on 1d in 2026): the raw Amihud value sits below the z-score's absolute std floor. Why now: `kernels/` is in the 186-26 fingerprint, so a later fix needs a follow-up rebuild. Sequencing call: indicagent-3a. |
| [466](pending/466-regime-columns-lookahead-dependents-303-304-benchmark.md) | Stored regime columns carry the todo 451 label-mask lookahead until the 186-26 rebuild. Dependents: the DEAD 303/304 verdicts benchmarked against stored `regime_volatility`; `feature_matrix.py` does not exclude the numeric `hmm_*` columns. |
| [461](pending/461-gap-z-read-the-next-bars-open.md) | `gap_z` read bar T+1's open (fixed in code in 186-12; stored rows fixed by the rebuild). Annotate the ledger's `gap_z` intraday IC read and the n1 combiner card's fold-1 G1 breach, then re-measure after the rebuild. |
| [471](pending/471-ic-measure-intraday-full-universe-memory-and-time.md) | The fresh IC writer on 15m (40 symbols) takes 17 minutes and 6.9 GB; the full universe extrapolates past host memory at block width 32. Measure block widths 4 and 8 and decide before 186-28 names its tf set. |
| [470](pending/470-ic-measure-unit-grain-resume-and-digest-pass-cost.md) | IC measure units are (job, tf): a kill loses the unit's cells, every run pays a whole-family digest pass, and a later `--start` leaves earlier member_window rows outside the DELETE range. Measure after 469. |
| [448](pending/448-research-lane-dependencies-for-phases-186-187.md) | Research-lane dependencies phases 186 and 187 plan for: item 1 (`repro_frozen.py` promoted) done in 186-03; remaining are kernel-registry memory as the single source for E17 L, one causality probe shared by `temporal_integrity` and S3, and StepM through the E17 H0 battery. |

**Quick and independent**

| Todo | Why now |
|---|---|
| [544](pending/544-ib-gateway-version-desupported-2026-12-15.md) | New 2026-10-27. IBKR warning 2172: gateway 1045.1 is desupported on 2026-12-15 (minimum 1050.1); after that, API logins may fail and IBKR ingestion stops. Upgrade the image in a fetcher gap, re-auth, verify a run. Why now: a hard external date. |
| [443](pending/443-postgres-exporter-chunk-scrape-cost-and-idle-in-transaction-timeout.md) | The postgres exporter's per-chunk scrape is the top database consumer (305 min in 3 days) and the idle-in-transaction timeout is 1 hour. Two config changes, measured before and after. |
| [439](pending/439-forward-span-integrity-write-once-oos-start-and-ic-purge.md) | Parts 1 and 3 done 2026-10-26: `oos_start` is write-once (migration 506) and the 7 forward-span looks are disclosed in the ledger. Part 2 (purge IC targets crossing it) lands with phase 186 (186-20, 186-28). |
| [438](pending/438-daily-borrow-availability-snapshot-capture.md) | Borrow availability is live-only at IBKR; every unrecorded day is lost for the forward span and the short-leg constraint. A small standalone daily job. |

**Data and onboarding**

| Todo | Why now |
|---|---|
| [431](pending/431-stratified-sourcing-onboarding-holds-one-transaction-across-ibkr-calls.md) | Delete the second instrument writer (`--commit` in the stratified-sourcing and pilot-draw scripts) so draw scripts only draw; the manifest onboarder is the documented path. |
| [444](pending/444-onboarding-tooling-classification-mapper-pair-column-orchestrator.md) | Onboarding SOP gaps 3, 5, 6: classification mapper, a manifest pair column for `spread_leg`, then one resumable onboarding command. After 431. |
| [502](pending/502-d7-judges-only-compute-1d-so-unpromoted-names-can-never-pass-the-gate.md) | New 2026-10-07, from 185-41 finding 1. D7 writes verdicts only for the `compute_1d` and `compute` names, so the 27 unpromoted names (and any name whose 5m lands later) are held "missing" forever and the onboarding promote stage cannot succeed. Judge the `backfill` dimension for 1d and every active name with 5m rows for intraday. Gate: before the next onboarding wave's promote step. |
| [505](pending/505-nightly-update-lane-exceeds-r4-measure-5m-pacing-ceiling.md) | New 2026-10-07, from 185-46 R4. The nightly update lane (1d plus 5m, one short request per name) measures 130 minutes today and 349 once every compute_1d name holds 5m, against R4's 120; 5m is paced by the unmeasured default 58 per 10 minutes. Measure the 5m ceiling with the rate probe, then set or justify the APR value. Gate: before 189-10 Task 2's pilot criterion is judged. |
| [537](pending/537-ibkr-1d-raw-deepening-scoped-full-scan-pass.md) | Campaign done 2026-10-18 (three full-scan runs, 1,030 no_data-confirmed floors); item 2 basis scan ran 2026-10-23 (todo 535 item 51), restore decided at plan 20. Item 3 rides with the plan 19 Task 2 `--measure` report. Runs over an hour lost the fetcher lock until 543 (fixed 2026-10-26). |
| [538](pending/538-ibkr-fetcher-teardown-hang-after-disconnect.md) | New 2026-10-17, plan 191-16 deviation 7. Two fetcher runs hung after "Disconnected" (main thread idle in `select` under `run_until_complete`, an unfinished future) and were killed; later runs stay blocked until the process dies. Needs a teardown-timeout diagnosis. Why now: the 537 deepening runs on its crontab gate while the owner is away, and a hang stalls it silently. |

**Research: 441, 423 and 440 unpause at plan 191-20's 1d re-derive (owner 2026-10-27); 442 and 437 follow 187's selection core**

| Todo | Why now |
|---|---|
| [442](pending/442-attempt1-single-family-and-pod-books-e17-memory-rule.md) | Paused (build first). `spec.py` refuses a book mixing families 1 and 2: run single-family books plus a pod book; E17's L must add combiner and partial-adjustment reach, with H0 battery cells, before fitted combiners run. Phase 183 session owns the files. |
| [437](pending/437-first-cut-cost-model-commission-and-spread.md) | Paused (build first). Promotion needs positive net expectation; today only flat bps bands exist. Commission (likely zero at the execution broker) plus validated Abdi-Ranaldo spread, as distributions. |
| [441](pending/441-price-only-daily-families-931-names-prereg.md) | Residual momentum is in the daily residual family with 423: prereg `docs/plans/2026-10-27-daily-residual-momentum-reversal-prereg.md` (draft after two Codex rounds), members, B1 universe (1,269 unseen names) and B2 battery built (ee8c264df). Left: the full B2 battery, B3 power, the spec, registration, then the run after 191-20's 1d re-derive. Industry momentum (needs point-in-time industry labels) and sector lead-lag (intraday) stay open here. |
| [423](pending/423-phase181-short-term-reversal-prereg.md) | Residual reversal R1-R3 are members of the daily residual family (see 441); the screen's 231 names and the TSMOM sleeve are excluded by the B1 rule. Runs with 441's h = 5 spec. |
| [547](pending/547-e17-hac-lag-for-overlapping-targets.md) | E17's Newey-West lag under-covers overlapping daily targets (H0 t sd about 1.1 at h = 5); h = 21 momentum cannot run until a horizon-tied lag is certified and owner-approved. Intraday statistics must not move. |
| [546](pending/546-e17-battery-shared-null-generator.md) | Three E17 battery modules duplicate the same H0 stresses; one shared generator, bit-identical at fixed seeds, before 184-05 adds a fourth. |
| [440](pending/440-generated-family-grammar-daily-ohlcv-931-names.md) | Unpauses at 191-20's 1d re-derive (owner 2026-10-27). Attempt 3b (ledger family 12): a registered grammar over daily OHLCV primitives, in-fold selection plus ridge, never materialized. |

**Integrity hygiene with a deadline**

| Todo | Why now |
|---|---|

**Closed by the rebuild (no separate work)**

| Todo | Why now |
|---|---|
| [411](pending/411-feature-vectors-and-regimes-stale-since-2026-08-10-nightly-job-refreshes-ohlcv-only.md) | Closed by 186-27 (the rebuild replaces the in-place refresh; design 14.2). Features and regimes stale since 2026-08-10 until then. |
| [426](pending/426-compressed-write-session-decompresses-whole-feature-vectors-exceeds-disk.md) | Closed by 186-27. Step 1 (headroom guard, migration 362) and native-DML writes landed; the rebuilt table is written append-only and compressed per chunk, so the whole-table decompress session is not needed. |
| [421](pending/421-feature-vectors-partial-coverage-velocity-and-never-computed-rank-z.md) | Removed at the source by the rebuild: the rank_z trio was dropped in 186-24 (migration 425), and the rebuild recomputes velocity for every symbol. Close after 186-26 with the per-feature coverage check (S0 floor, todo 435). |
| [494](pending/494-unit-tests-can-spawn-live-writers-ci-guard.md) | New 2026-10-06, from 185-18. Unit tests leaked into the live database three times (a real grid derivation, permanent D1 fixture rows, a self-cleaning live write). Add a conftest guard on subprocess spawns of derivation and pipeline scripts and a boundary test on live-DSN writes; move the atomic-write test to indicagent_test. |
| [491](pending/491-universe-membership-pinned-in-the-s0-snapshot.md) | New 2026-10-03. The research spec names a universe dimension, not a snapshot, and `instruments` has only `created_at`, so promoting wave 2 changes the panel silently. Store entry date and cohort per name and hash the promoted symbol set into the S0 snapshot and `research_run`, before the first counted run. Also records that today's-cap-rank selection is outcome-conditioned. |
| [520](pending/520-future-timestamp-guard-on-ingested-bars.md) | New 2026-10-09. The writer guard landed in 191-02 (`services/ohlcv_raw_writer.py`, APR `threshold.bar_integrity.future_bar_tolerance_s`, tested). Open remainder: the D7 1d condition, explicit deferral D-191-H (owner acknowledgement pending). |
| [522](pending/522-alpaca-execution-mechanics-shadow.md) | New 2026-10-09, pilot Workstream B. Paper-only order lifecycle validation (20 single-share orders, EOD flat, idempotent reconnect) plus the fixed slippage instrumentation spec. Single session, zero risk, independent of the 189-10 lanes; fastest path to measured own-flow slippage. |
| [527](pending/527-post-backfill-simplify-backlog-185-189.md) | New 2026-10-10; findings in docs/plans/2026-10-10-simplify-findings-185-189.md. Phase 191 plan 06 consolidated the `_d1_gaps` answered-window copy; the service-side copies and the 5m shaper dedup are the explicit deferral D-191-H (owner acknowledgement pending); items 3 to 9 unchanged and open. |
| [521](pending/521-alpaca-intraday-depth-build.md) | Green-lit by the owner 2026-10-09; Phase 2 all-names canonical 5m load landed 2026-10-10 (1,502/1,502 eligible). Nightly installed 2026-10-26 (`indicagent-alpaca-nightly.timer`, 04:40 UTC): it asks SIP with its window end 20 minutes back (migration 513; the free plan 403s only a window ending near now); IEX answers carry `iex_rth`, raw only, never selected (528adc7c4). A one-time 20-day catch-up ran 2026-10-26. Left: the 33-name thin-tail no_data evidence. |
| [524](pending/524-intraday-parity-volume-basis-and-dividend-price-buckets.md) | New 2026-10-09, from the pilot's C7. WEAT parity mismatches are 100 percent volume-only (vendor volume basis); five dividend payers show handfuls of price-only buckets. The parity lane now serves into `ohlcv_raw` (191-16); the open remainder is D7's dated tolerance rule and price/volume split in its output, explicit deferral D-191-H (owner acknowledgement pending). |
| [525](pending/525-single-day-provider-gaps-need-a-recorded-span.md) | New 2026-10-09, from the pilot's C8. DBMF misses 0.995 slot coverage on 3 single-day IBKR 5m gaps that the backward walk can never confirm empty; extend ohlcv_empty_history to record mid-history single-day spans evidenced by answered-chunk neighbors. |

## P2: Real value, not urgent

| Todo | Why now |
|---|---|
| [548](pending/548-style-spread-regime-slot-and-time-series-construction.md) | New 2026-10-27. The owner's participation-state idea (RSP/SPY and style spreads) cannot run through the runner: S7 has no regime input slot (part A) and the runner is R1 only (part B's time-series book). Part B's synthetic power check comes first and needs neither. |
| [529](pending/529-test-suite-cleanup-remnants-and-redundancy.md) | Moved from P0 2026-10-27 (hygiene, not on the testing path). New 2026-10-10, owner directive: many tests are remnants of deleted systems (v2.x, I8, Tradier) and many are redundant; the suite burns too much time and tokens. Evidence-first cleanup per the audit report; CI green per batch. |
| [554](pending/554-remove-legacy-feature-vectors-research-readers.md) | New 2026-10-27, from plan 184-04 (184-REVIEWS row 18). The feature_vectors read boundary allow-lists two pre-184 `scripts/research/` readers and `ops_oos_holdout_eval.py`; each can still produce an uncounted look. Delete each, or re-express it as a runner spec reading through S0, and drop its allow-list entry. |
| [536](pending/536-forward-span-read-guard-for-ad-hoc-queries.md) | New 2026-10-14, from the evidence framework section 7 amendment. Runner paths refuse reads past `alpha.validation.oos_start`, but an ad hoc SQL read of the forward span is unrestricted and unlogged, which can silently void the one-spend confirmation. Pick a mechanism (capped role or view, or audited reads) and a sink for recorded looks. |
| [531](pending/531-schema-names-without-glossary-entries-rename-or-gloss.md) | Nine relations have live readers and no glossary entry (survey 2026-10-10): market_data_5m is a real naming violation, instrument_metadata overlaps instruments, the v2.x-era stack was never glossed, parity_certification_state looks dead. Gloss, rename, or drop each; nothing here blocks the rebuild. Phase 191 glossed the new raw-layer names only (191-01); market_data_5m's naming pass is the explicit deferral D-191-H (owner acknowledgement pending); the other relations unchanged. |
| [532](pending/532-session-coverage-verdict-denominator-anchors-at-first-bar-not-proven-span.md) | The session_coverage verdict anchors its denominator at the first 1d bar, so early-history holes cap old names' ratio forever (the 263-name set behind 186-26's d2_landed gate). If still red after the 06:00 UTC 2026-10-11 audit: methodology-ledger entry, then anchor at the proven span (526's concept) with an explicit hole policy. |

**With phase 186 and the streaming revival**

| Todo | Why now |
|---|---|
| [495](pending/495-integration-baseline-regen-after-phase-185.md) | New 2026-10-06, from 185-18/22. Phase 185 migrations 404-408 sit below the integration cutoff 433, so indicagent_test lacks their effects (408 is `listing_venue`, applied 185-24). 185-24 has landed: regenerate baseline and seeds now (todo 486's method). |
| [496](pending/496-two-live-db-integration-tests-red-since-185-12-and-186-23.md) | New 2026-10-06, from 185-18. test_ic_parity_replay (dropped forward_returns) and test_bar_quality_flag_quarantine (a migration 381 snapshot that 185-12 moved) read the live DB and stay red. Retire the first, rewrite the second as a live invariant. |
| [481](pending/481-rates-regime-curve-label-measures-rate-direction-not-slope.md) | The `rates` regime curve tier (TLT minus SHY) tracks the 10-year yield change (R2 0.76 daily) and its "steep" end has the opposite sign to the 10s2s slope change. Take the tier from the measured slope in `economic_series_observation`; every label changes, so fold into the 186 regime rebuild after the null-arm control. |
| [463](pending/463-live-macro-features-fabricate-zero-when-no-cross-asset-record.md) | New 2026-09-29, 186 debt pass B5b. The live path returns an all-0.0 `CrossAssetRecord` when no record exists and `compute()`'s `_guard` fills non-finite macro values with 0.0, while the rebuild emits NaN and stores NULL (`no_fill`). The NaN reaches storage only on the registry-kernel path: the legacy `_build_feature_vector` re-fabricates 0.0 (also for `compute_batch` backfills) until 186-25 removes those guards and proves NULL in the rebuilt table. The live fix needs nullable macro fields in `FeatureVector`; options and a recommendation (nullable fields, with the streaming revival and a live-versus-rebuild parity test) are in the todo. |
| [474](pending/474-kernels-fill-neutral-values-for-undefined-instead-of-nan.md) | New 2026-09-30, plan 186-15 review. Kernels store neutral fills for undefined (`poc_dist_atr` 0.0, `va_position` 0.5, S/R and sweep fallbacks, `htf_last_log_ret[0]`, VWAP filled with closes), breaking `no_fill`. Recommendation: NaN by default, a declared `neutral_reason` escape hatch enforced in the registry, done with todo 463 and a golden regeneration in its own commit. |
| [464](pending/464-cross-asset-builder-does-not-track-previous-closes-before-first-record.md) | New 2026-09-29, 186 debt pass B5a. `build_cross_asset_series` advances previous closes for SPY, TLT and SHY only while skipping early dates, so TIP, HYG and LQD start the first record date with no previous close and the two spread z-scores start one observation late. The one-line fix moves the golden fixture (`tip_tlt_ret_z`), so it needs its own regeneration commit before the 186-26 rebuild. |
| [473](pending/473-live-ctf-path-differs-from-batch-and-runs-92-kernels-per-bar.md) | New 2026-09-30, plan 186-15 review. The dormant live path sets only `ctf_momentum` from the newest buffered HTF bar (task-order dependent), leaves `ctf_vwap_align`/`ctf_regime_align` at 0.0 and the HTF return NaN, and recomputes 92 kernels over the window per bar (~73 ms at 600 bars). Recommendation: run `compute_kernels` over the buffered tail with the batch alignment builders and delete the FeatureCache replay, with the streaming revival and 186-25. |

**Research follow-ups (paused with the attempts)**

| Todo | Why now |
|---|---|
| [460](pending/460-family1-auction-price-check-and-auction-to-auction-hold.md) | New 2026-09-29, family 1 iteration 4. About two thirds of the open-plus-close book's gross depends on the stored 09:30 open being a tradable auction price (unchecked); then test an open-auction-to-close-auction hold, which crosses no spread. Decides whether a standalone slot book can be net positive. |
| [456](pending/456-todo445-rerun-zero-commission-and-longer-horizons.md) | New 2026-09-29, owner review of todo 445. The 5m name set (`ret_autocorr_1`, `sweep_detected`) was pruned by a hurdle that charges $0.0035/share commission, but the live book will likely use a zero-commission broker; horizons also stop at half a session. Part A rederives the name set at zero commission from recorded p-values (no new look); Part B tests multi-day horizons against 1h/1d counterparts (counted look, after the 185/186 pause). |
| [457](pending/457-family1-slot-subsets-through-the-runner.md) | New 2026-09-29, family 1 iterations 2-3 (iteration 1, the horizon specs, already ran through the runner). The opening and closing slot subsets, the 30-cell conviction grid and the 32-cell liquid-close grid ran outside the runner, so they are not in the E18 selection universe. After phase 187 adds a slot-subset mask and the keep gate, rerun them in exploration mode on the 233 and the 201-name sets. |

**Data and ingestion**

| Todo | Why now |
|---|---|
| [534](pending/534-ibkr-5m-backfill-throughput-serial-fetch-and-refetch-waste.md) | Moved from P0 2026-10-27: Alpaca is the 5m source from 2016-01-04 (D-191-P), so IBKR 5m throughput matters only before 2016. New 2026-10-12: the 5m backfill measures about 2 symbols an hour (35 days for 1,529 names). Cause: one request in flight at 28 s latency (limiter allows 348 an hour) plus mixed own/Alpaca chunks refused at the 2% guard and refetched (91 requests a symbol vs 49). Fix: same-vendor ratio, bounded concurrency as an APR key; target about 7 symbols an hour. Rides with 505 and 533. |
| [395](pending/395-nightly-backfill-fails-3-nights-weekly-ibkr-weekly-2fa-unattended.md) | Moved from P0 2026-10-27: the remainder is the alert receiver, and alerting is deliberately deferred. NARROWED 2026-10-10 late (7a): the nightly unit it targeted was deleted by the 189-06 cutover (the continuous fetcher timer supersedes the retry design). Landed: 15-min gateway auth-state probe (real handshake, client 44, no FetcherLock) + the IBKRGatewayAuthDown alert, verified live. Remaining is owner-only: a real alert receiver (bot_token + chat_id or alternative) -- alerts still reach the no-op receiver until then. |
| [516](pending/516-spin-off-action-type-as-a-research-layer-distribution.md) | New 2026-10-08, from 185-51 (todo 515 option 1). CTVA is held and frozen at its raw 2026-09-30 bar: a `spin_off` action type that d2-v2 never applies as a split, a d2-v2 rule that keeps the pre-restatement observations, and the distribution as a research-layer total-return event like dividends (428); then release the hold. Also ELE, IESC, MSM, TIGO (write names without a 1d symbol row, still true) and d2-v2's one-session effective_date offset. Gate: before CTVA's hold is released and before 186-26 reads CTVA. |
| [518](pending/518-1d-volume-basis-change-at-d-for-research.md) | New 2026-10-08, from 185-48. Canonical 1d volume steps at D = 2026-10-07 for every name (IBKR/Tradier p10 0.41, p50 0.53, p90 0.81): the S0 labels mark D as a basis change read from the policy row as of `policy_as_of`, and a volume read across D is labelled or refused. Research lane (501 closed 2026-10-26: snapshots now pin `policy_as_of`); gate before any attempt reads volume across D and before 186-26's volume features are relied on. Input to 533's selection rule. |
| [519](pending/519-1d-names-frozen-at-their-last-tradier-bar.md) | Updated 2026-10-26 with the corporate record: WBD, QRVO and CCO ended (merger or buyout; CCO delisted 2026-10-26), PSKY trades as SKYD on NYSE (IBKR re-served its history on a 0.979 scale, measured). Recommendation in the todo: listing end as its own small table (it replaces `--frozen-names` and lets `freshness_1d` judge against a known end); PSKY repoint via `provider_meta.ibkr.symbol` once the owner accepts the rescale hold (as CTVA, 516). Parked: non-critical, the rebuild gate already skips stale names. |
| [453](pending/453-ibkr-backfill-concurrency-probe-then-pipelined-persistence.md) | New 2026-09-27, filed from 449 lane monitoring. Big IBKR backfills are bound by the serial walk loop, not our config: rate cap measured at 3.4x headroom (never engages for heavy TFs), chunk days already at probed ceilings. The "one heavy history stream" finding was a confounded test (4 processes, 4 connections, 4 limiters). Controlled single-connection concurrency probe in a quiet window, then pipelined persistence (or bounded concurrency, if it survives). Speeds every future big backfill; the probe itself is blocked while 449's chain fetches. |
| [498](pending/498-otel-collector-drops-every-job-labelled-metric.md) | New 2026-10-06, found at the 189-06 cutover. The OTel collector drops every metric carrying a `job` label (`duplicate label names`, since 2026-06-22), so `job_completed_total` and the fetcher's staleness gauge never reach Prometheus and the D-06 oneshot contract is dark. Rename the label or stop the constant `job` label; sweep dashboards and alert rules. |
| [497](pending/497-186-27-sets-the-intraday-recovery-unlock-keys.md) | New 2026-10-06, from 185-20. 186-27 sets infra.bar_derivation.intraday_recovery_unlocked and rebuild_state_table at rebuild completion; the recovery tool also needs the venue study's 5m verdict. Venue fallback is 1d-only (437). |
| [454](pending/454-ultra-thin-traded-series-treatment.md) | New 2026-09-28, filed from the 185-10 historical scrub pass (todo 052 defect-class sweep; docs/research/scrub-historical-pass.md). Ultra-thin traded series: RCAT clears volume>0 for years at volume <= 30 shares; 6 of the top 20 largest 1d moves are this one name; no scrub rule fires (too sparse for the 61-bar window). Measure the class distribution, then decide with the owner: universe eligibility dimension vs informational rule. Raw bars untouched either way (D-09). |

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

## P3: Hygiene, docs, process, performance (opportunistic)

**Dated**

| Todo | Why now |
|---|---|
| [483](pending/483-record-2026-midterm-forward-window-result.md) | New 2026-10-01. Due after 2027-05-03: record the pre-registered 2026 midterm forward window (S&P 500, election day to +6 months) in the idea doc and ledger, as one unsearched observation. Nothing else forces this step. |
| [485](pending/485-rate-limiter-wait-logging-in-ibkr-py.md) | New 2026-10-01, from reboot-day ops. `_hist_limiter_for().acquire()` logs nothing while a request waits for pacing budget, so normal throttle during rescan reads as a hang (caused one premature kill today). One `hist_pacing_wait` log line per blocked request. |
| [487](pending/487-run-spec-synthetic-defaults-cannot-express-spec-gates.md) | New 2026-10-02, from the 183 UAT. `run_spec --mode synthetic` defaults (30 names, 400 sessions, start 2006-07-03) cannot pass a real spec's gates: PR 60 is unattainable at 30 names (generator crash) and 400 sessions end 2008-01-11 so the `trading_start` filter empties the E17 measurement, refusing every member with an unprinted reason. Validate loudly and name the minimal flags instead. |

**Kernel and feature code (phase 186 follow-ups)**

| Todo | Why now |
|---|---|
| [550](pending/550-promote-research-kernel-rolling-percentile.md) | New 2026-10-27, from plan 184-02 (184-REVIEWS row 10). Gated on 186-27. Move the vectorized rolling percentile research kernel into the 186 registry (or replace the slow stored `_price_percentile_series_full` under the parity test) and delete the research copy, so one concept has one implementation. |
| [551](pending/551-promote-research-kernel-rolling-max-distance.md) | New 2026-10-27, from plan 184-02. Gated on 186-27. Same for the rolling max distance research kernel (stored equivalent `high_52w_dist`, an O(n x window) loop). |
| [552](pending/552-promote-research-kernel-rolling-vwap-deviation.md) | New 2026-10-27, from plan 184-02. Gated on 186-27. Same for the trailing-window VWAP deviation research kernel; the stored `vwap_dev_sigma` is cumulative (path dependent), so this one becomes a new stored column. |
| [506](pending/506-backfill-feature-factory-fetch-only-fetcher-lock.md) | New 2026-10-07, from plan 189-08. `backfill_feature_factory.py --fetch-only` fetches IBKR history without FetcherLock; the lock guard allow-lists it TEMPORARY. Wire the lock in after 186-26's rebuild (editing the rebuild writer mid-run discards its cells). Not scheduled today, so nothing collides. |
| [475](pending/475-macro-kernels-branch-on-symbol-and-timeframe-names.md) | New 2026-09-30, plan 186-15 review. `kernels/macro.py` names SPY/TLT and the six-symbol basket, `cross_tf.py` branches on `tf == "5m"`/`"1h"`; `asset_agnostic` and the ITR rule say data, not code. Recommendation: membership and the self-regression exclusion from `instrument_tags`, TF pairs from config; bit-identical. |
| [477](pending/477-pivot-detection-repeated-per-row-across-structure-kernels.md) | New 2026-09-30, plan 186-15 review. Pivot detection runs about five times per row across swing/sweep/pool/BOS (~10% of batch time). Optional: a shared derived input in `contract/derived_inputs.py`, bit-identical. |
| [472](pending/472-ctf-source-builder-hard-coded-constants-not-apr.md) | New 2026-09-30, plan 186-15. `_build_ctf_series` (moved byte-identical into `kernels/cross_tf.py`) keeps an HMM observation window of 20, a cold-start volatility of 0.005 and numeric guards inline; they move stored `ctf_regime_align`, so the APR mandate applies. Seed equal values so the golden stays identical. |
| [479](pending/479-service-timer-logs-root-owned-break-single-module-unit-tests.md) | New 2026-09-30, 186-18 follow-up. Timer-written service logs are root-owned in the checkout, so a unit test module that configures service logging first fails alone with PermissionError (seen on the regime coverage auditor); the full suite masks it. |
| [465](pending/465-ring0-metrics-module-holds-domain-named-instruments.md) | New 2026-09-29, 186 debt pass B10a. `src/observability/metrics.py` (Ring 0) holds about 190 domain-named instruments (`FEATURE_QUALITY_FAILURES`, `FEATURE_LIFECYCLE_TRANSITIONS`, `SIGNAL_*`, `REGIME_*`); the `ring0-boundary` check only greps imports. Recommendation: extend the check with a domain-word list and a generated legacy allow-list now, move instruments to Ring 1 per area later. |
| [459](pending/459-ucr-feature-composition-replaces-stale-tier-and-register-hmm-columns.md) | New 2026-09-29. The UCR feature `tier` key (atomic/interaction/theory) is a stale taxonomy (the 106 theory features are direct measurements too); replace with base versus interaction, and register the 11 HMM regime columns that have no `concept_registry` row. In phase 187 scope (ROADMAP goal, owner 2026-09-29). |
| [458](pending/458-family1-slot-alpha-as-execution-timing-overlay.md) | New 2026-09-29, family 1 iteration 3. Untested hypothesis: use the same-slot alpha only to time entries and exits for trades a slower book already makes, so no incremental spread is paid. Needs a slower book with a recorded trade list first. |

**Regime and IC engine**

| Todo | Why now |
|---|---|
| [108](pending/108-hmm-multi-seed-restart-best-likelihood.md) | Each walk-forward HMM segment fits one seed with a same-seed doubled-`n_iter` retry (`_walk_forward_hmm_full`; the single-fit `n_restarts` path was deleted in 186-13). Multi-seed best-likelihood is a robustness gap, not a proven bug. |
| [226](pending/226-regime-writer-n-iter-convergence-headroom-check.md) | Check whether the HMM `n_iter=200` cap is oversized; step 1 instrumentation is in, a small sample showed the retry at 400 firing on 2 of 15 cells. Analyze the distribution on the 186-26 rebuild run. |
| [009](pending/009-service-utils-ic-engine-cleanup.md) | Parts B and C remain: promote 4 scripts to `BaseBatch` plus systemd, and the naming-vocab doc update. Parts A, D and E closed; the ensemble items went with 186-19. |

**Process and tooling**

| Todo | Why now |
|---|---|
| [394](pending/394-todo-number-uniqueness-not-ci-enforced-duplicate-389.md) | New 2026-09-23, found closing todo 388. Two files shared todo number 389 for a day (concurrent sessions picking "next free" independently) and one PRIORITIES.md row displayed `[391]` while linking `pending/389-...` -- `test_todo_priorities_link_integrity.py` passed both times because it checks link-target existence only, not number uniqueness or label-file agreement. Fix: extend the guard with (1) no duplicate leading numbers across pending/+completed/+deferred/ (numbers must never be reused after closure either) and (2) display number == target filename number. Same drift-class extension pattern as the guard's own todo-305 origin. |
| [383](pending/383-gsd-sdk-state-and-gap-checker-hardcoded-field-path-assumptions.md) | GSD tooling, not project code: `gsd-sdk query state.planned-phase` string-matches field labels this STATE.md never uses (a silent no-op every run), and `gap-checker.cjs` hardcodes bare `CONTEXT.md`. |
| [284](pending/284-gsd-review-agy-stdin-invocation-broken.md) | GSD tooling: `review.md` documents `agy -p -` (stdin), which the installed `agy` does not read, and the empty-output check does not catch the greeting it returns. Pass the prompt as an argument. |
| [309](pending/309-vulture-baseline-cleanup-backlog.md) | 1136 pre-existing vulture findings are frozen in `tools/vulture_whitelist.py`; CI blocks new dead code. Triage the whitelist (real dead code mixed with dataclass and Pydantic false positives). |
| [321](pending/321-feature-factory-config-test-fixture-consolidation.md) | No shared `FeatureFactoryConfig` test builder: 15+ files hand-type the ~95-kwarg literal. Fails loud when forgotten; worth doing before the next field-adding plan. |
| [324](pending/324-gradient-vocabulary-naming-check-unenforced.md) | naming-system.md section 7's gradient-scale vocabulary has no enforcement. Settled on a CVR `gradient_scale` namespace (D-07); needs `VocabularyDriftAuditor`'s `has_live_source` distinction designed first. Unblocked (`vocabulary_access.py` exists). |
| [331](pending/331-vocabulary-drift-auditor-windowed-query-blind-spot.md) | `VocabularyDriftAuditor`'s source queries are window-bounded (30 days), so a rare code outside the window is invisible (why migration 233's missing `4h` sat undetected). Needs design. |
| [373](pending/373-docs-tree-152-broken-internal-links-not-file-count-clutter.md) | 152 broken internal markdown links in three clusters (old `intel-NN` numbering, pre-v3.0 docs of archived subsystems, untriaged). Its own pass. |

**Registries and universe**

| Todo | Why now |
|---|---|
| [272](pending/272-instrument-tag-peer-group-coverage-auditor.md) | No automated audit for thin or missing `instrument_tags` peer-group cardinality; every gap so far was found by a person asking. |
| [397](pending/397-universe-dimension-views-and-instruments-boundary-test.md) | New 2026-09-23, from the /simplify review of the 174 fix branch. Universe dimensions as DB views plus a CI boundary test on raw `FROM instruments` reads, so a new reader cannot silently mean the wrong universe (the WR-01 failure class). `dimension_where_clause()` already removed the existing duplication. |

**v2.x retirement**

| Todo | Why now |
|---|---|
| [509](pending/509-v2x-remainder-after-185-45-fvp-coupling-dashboard-surface-ml-chain.md) | New 2026-10-07, from plan 185-45. Item 1 done 2026-10-26 (23056ccca: pipeline trimmed to three primitives, 194 modules and the plugin tier deleted, migrations 503-505). Section 4 Kafka and alert leftovers done 2026-10-26 (abea446d8 plus the alerts commit landing now: dead DLQ and I8 topics, dead alert rules, panels and dashboards, and a guard test that every queried metric is declared in code). Item 2 (dashboard signal surface, migration 521) and item 3 (ML batch chain) done 2026-10-26; the dashboard follow-ups closed with cockpit slice 1. Left: the vacuous I7 CI/pre-commit/tools checks on the deleted `src/intelligence/trading/`, `ANALYZE setup_performance` in `weekly_db_maintenance`, the `shadow_registry` owner call, the `alert.lag.*` APR keys (185-43), `roll_events`, and the streaming warm-up asymmetry. Supersedes the remaining scope of 056 and 223. No lane since the dashboard lane closed 2026-10-27; cleanup only, below the build lanes. |
| [510](pending/510-delete-185-38-185-43-185-45-backups-after-2026-11-06.md) | New 2026-10-08, from 185-43. Delete `data/backups/185-38`, `185-43` and `185-45` (about 5.8 GB, rollback material of the cutover and cleanup) on or after 2026-11-06 (185-43's on 11-07), once nothing has needed a restore. |
| [275](pending/275-v3-north-star-precedentengine-mechanics-predate-d4-rescope.md) | New 2026-08-06, found while doing the AnalogEngine→PrecedentEngine naming correction during a Phase 145 discuss-phase session. `docs/foundation/v3-north-star.md`'s PrecedentEngine mechanics (Score Object, independent-annotator framing, `signal_events` target) predate the D4 rescope that corrected exactly this framing elsewhere (glossary, `intel-precedent-engine.md`). Naming fixed inline + flagged; the mechanics reconciliation itself is real design work, not done here. No live consumer reads this doc's mechanics section today. |

**Not in this list:** `deferred/` (phase-gated or recompute-batched) and `completed/`.
