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
git and in each todo's own closure note, not in this file. Durable reasoning behind this file (process rules,
active sequencing decisions): `docs/research/priorities-decision-log.md`.

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
| Data (phase 191, 18/25) | 191-19 done 2026-10-28 (residue report) -> 191-20 (done 2026-10-29: policy applied, Tradier deleted, 1d re-derived, D7 passes for 1,273 of 1,502 names, 229 named holds; todo 545) -> 191-21 -> 22 -> 23 (23 depends on 22's integrity_checks changes; decided 2026-10-27) -> 186-26 rebuild (rows discarded 2026-11-04, migration 569; one rerun at the new pin once the data is complete, todo 584); 191-24 and 25 land while the rebuild runs |
| Build (phase 186, 25/29) | 186-17 Task 2 in a fetcher gap -> 186-26 rebuild (starts once 191-21..23 are in) -> 186-27 -> 186-28 (tf set from 471) |
| Research inputs (phase 184, plan now) | `/gsd-plan-phase 184`: S0 reads `feature_vectors` across timeframes through the causal align node (todo 435 is its B1). Runs on the rebuilt table once 186-27 swaps it in; planning and the align node's code need no rebuilt data |
| Research core (phase 187) | Selection core first: plans 08-15 (horizon and combining rules, pod books, recipe book, cards, contribution accounting, `generated_family`). Governance moves after the first feature family: 187-16 (DAG manifest, auditor inventory), 187-17 (per-writer DB roles), 187-18 (package renames), FK indexes. E17 v2 (todo 549, owner 2026-10-27): fixed-b critical values, then the step B battery rule and one fresh 4,000-session battery; StepM selection and the kappa 0.5 book wait on it |
| Testing (unpauses at 191-20's re-derive) | Family 2's one evidence run; daily price-only families 441 + 423, then 440; after the rebuild and 184: feature families, then regime-segmented ones (466 and 481 fold into the rebuild) |
| Quick, independent | 544 (gateway upgrade before 2026-12-15), 443, 438; 439's IC purge rides with 186 |

## P0: Fix soon (integrity/correctness gaps already surfaced)

| Todo | Why now |
|---|---|
| [584](pending/584-corpus-rerun-fix-manifest.md) | New 2026-11-01, P0, the critical path. One list of stored-value fixes that land before the pin moves, then one corpus rerun. Every code item has landed as of 2026-11-04 (1-12, 6a-6d, 8b, 3 at K=3, G4-a). The pin waits on todo 587 (splits) and complete data (owner 2026-11-04: the 534 5m coverage target is met before any corpus compute), then the official pilot G1-G5. 186-26 rows discarded (migration 569); decision items 3 and 4 landed 2026-11-04 (migration 570): one table name `feature_vectors`, old v1 table dropped, stage-end compression from the planner's pending units, streaming writer unit disabled. |
| [587](pending/587-canonical-1d-carries-404-unadjusted-splits.md) | New 2026-11-04, P0, gates the 584 pin. Canonical 1d steps by the split ratio on 404 Yahoo-dated splits over 283 names (396 in pre-2016 IBKR named), breaking the split-adjusted invariant; every 1d kernel reads a fabricated -41% to -67% day. Design set by the lead: confirmed splits become `corporate_action` rows (`calendar_audit`), the daily rule rescales proven-unadjusted spans (owner veto window: reverses 185-49's never-served for this case), lineage carries the factor, and D7 gains `split_continuity`. IBKR 5m before 2016 is clean. Status 2026-11-04: safe set landed (d891857d2, bf5abd1d8: 380 confirmed on 268 names, no row written); the atomic part (d2-v5 rescale, lineage view 568) is unpushed at 5e3845df2 and waits for the lead's go (paused by the owner); recipe in the todo. |
| [588](pending/588-184-admission-holes-from-wave-review.md) | New 2026-11-04, P0, gates the first counted test with an input member. The independent 184 wave review found the runner admits runs no passing battery cell tested: the static gate is derived from failed cells, any signal can claim the feature certificate, smoothing 5 bypasses the persistence failure. Part A refuses (code), part B earns admission back (battery cells), part C is 184-12's real-data dry build. |
| [589](pending/589-bulk-load-unit-scoped-recompress-for-renamed-units.md) | New 2026-11-04, P2, from the 584 item 4 review. A completed unit renamed after its `feature_vectors` chunk compressed (restated bar, APR change, onboarding) is refused loudly by `bulk_load`; add a unit-scoped decompress-load-recompress path under the headroom guard. Matters from the first restatement after the rerun's chunks compress. |
| [590](pending/590-retire-the-v1-feature-vectors-in-place-writers.md) | New 2026-11-04, P2, from the 584 item 3 review. `regime_writer` and three corpus repair scripts still UPDATE `feature_vectors` in place; since migration 570 they refuse loudly (the table left the write-session allow-list). Retire them as one block with their allow-list entries. |
| [591](pending/591-regenerate-integration-baseline-after-570.md) | New 2026-11-04, P2. The integration replay (baseline 433) never has the kernel table: 462 drops `feature_vectors_v2`, 569's unguarded TRUNCATE stops the replay, and 570 is a guarded no-op there. Regenerate the baseline after 570 and move v1-column fixtures to the kernel contract. |
| [534](pending/534-ibkr-5m-backfill-throughput-serial-fetch-and-refetch-waste.md) | Moved from P0 2026-10-27; owner 2026-10-28 put it back at P0 and 2026-10-31 made it THE data-acquisition goal: 5m 2006-2026 for every symbol, deepest history first (memory: project_raw_coverage_target). Measured 2026-10-31: of 1,160 pre-2016 names (1d start before 2016), 81 have IBKR 5m reaching their daily start, 280 partial, 799 none; median first-5m year for names IBKR serves is 2006, so the 2006 target is reachable. By 2026-11-03, 455 of the 1,160 have pre-2016 5m (about 25 names/day; about 4 weeks to done). Alpaca 5m is at its vendor ceiling for all 1,529 names (nothing un-asked). Throughput: `infra.backfill.fetch_concurrency` 4 (owner decision 2026-11-02; the test, decision rule and the measured about 95 requests/h are in the todo); the fetcher-run wedge is fixed (todo 538, landed 2026-11-02: runs end on a failed probe or 1800 s without intake, outer timeout 240 s), leaving the compression-policy DB stalls (todo 443 incident, compression paused for the rebuild) as the remaining known constraint. Pacing-wait logging landed 2026-10-31 (a23af3551) so throttle vs wedge is distinguishable from the next run. Since 2026-11-03 23:19Z the `defer_after` horizon (fabb62e5a) puts every IBKR 5m ask pre-2016 (0% in the 3 h before); about 1.1M rows/h at 4 lanes. Vendor memo: `docs/ideas/vendor-pre2016-intraday-history.md`, owner's call. |
| [564](pending/564-rebuilt-1d-feature-columns-that-are-constant-or-all-null.md) | New 2026-10-29, P1. After the 186-26 1d rebuild, `hma_slope_z` is 0 on every row and about 40 other 1d columns are constant or all NULL; declare applicability so the research read excludes dead columns. |
| [583](pending/583-hmm-regime-null-on-whole-names-in-the-1d-rebuild.md) | New 2026-11-01, P1. The 564 per-name screen shows the seven `hmm_*` columns and `regime` NULL on every 1d row of AAPL, HON and SCCO (MSFT from 2018 only); likely the walk-forward gate refusing every segment. Measure refusal reasons across the 1d universe and fix or declare before any regime-segmented 1d spec. The K sweep is running 2026-11-03: four detached lanes in `data/scratch/583-k-sweep-2`, refusal rule decides (BIC reference only), the lead owns the summarize; owner sees the per-tf output before anything reaches this todo. |
| [571](pending/571-reset-the-concept-layer-after-the-186-26-rebuild.md) | New 2026-10-30, P1, owner-approved, runs after the 186-26 rebuild and todo 564's batch. Demote the 306 `active` features to `candidate` through `ConceptRegistryService` and clear the 590 old evaluations; back up first. |
| [568](pending/568-docs-cleanup-outdated-thresholds-gates-and-v2x-content.md) | New 2026-10-30, P2. Candidates and the 547/560/564 todo sweep done 2026-10-31 (see the todo's status section); open: the reset follow-ups, which need the owner's one-line freeze lift on ledger sections 2 and 4, then reduce the voided-results docs to status + pointer. |
| [565](pending/565-slot-coverage-counts-no-trade-slots-as-missing-for-sip-years.md) | New 2026-10-29, P0. Audit-side fix landed with the intraday launch (2026-10-31, commit b998e86f4): the planner and the audit now share one answered-evidence definition (`gap_plan.COVERAGE_EVIDENCE`: applied Alpaca load ranges + Alpaca SIP 5Min windows, refused-load guard on both). Remaining: the recount rides the nightly 06:00 UTC audit; names still below 0.995 become named holds. |
| [566](pending/566-1d-canonical-lacks-bars-the-raw-table-holds-for-71-held-names.md) | New 2026-10-29, P1. Classified 2026-10-31 (full section in the todo): pre-2016 resolved; 108,230 residual sessions over 147 names in five classes. 61% is 27 names never derived (`compute_eligible_1d=false`, owner decision before promoting, todo 491's silent-panel point); 26% is by-design D-191-Q IBKR gaps recorded nowhere (the `unserved_primary` fix is assigned to a session lane); the rest are recorded refusals in the owner-arbitration lane and CTVA's own hold (516). Status 2026-11-04: QRVO retired (6433a469a); group 2 (the 27 names: IBKR 1d fetch then re-derive) open; group 3 waits on the owner. |
| [567](pending/567-answered-evidence-is-not-recorded-when-a-vendor-answers-with-nothing-new.md) | New 2026-10-30, P1. Fix 1 landed 2026-10-31 (b998e86f4: one answered-evidence definition in the planner and the audit) and fix 3 landed (migration 546: BZH and ACVA listing_end rows). Remaining: bar_derivation's D7 flag rule is the third consumer still on SMART-only windows (status section in the todo); the recount rides the nightly audit. |
| [535](pending/535-raw-bar-table-review-findings-191-01-to-03.md) | Review findings from phase 191 (reviews of 01-03, 04-05, 06, 07 and three rounds of 07 fixes). Owner decision D-191-N 2026-10-14: last-wins ingress, restatement detector, all holds released. Fourth review: serve-time last-wins and basis-flag gating done; items 30-35 open (integration test, zero-grid sessions, GE retro flag, batched choices, waived chain). Open: IBKR re-serve of 4,569 keys (`logs/reserve_keys_191_07.json`, 103 session asks) when the fetcher may run; truncated-bar scan calibration and universe run; GE 2021-11 two-decimal span; fetcher `waived` chain cleanup; bar_derivation answered windows; complete-bar gaps in the campaign loader and the feature factory; 06 items 6 and 10 land in plan 08; derived 15m/1h re-derive when bar-derivation resumes. Rides with 533. |
| [433](pending/433-ibkr-daily-history-truncated-at-primary-listing-venue-change.md) | Silent wrong answer, owned by phase 185: SMART history starts at the last listing-venue move. 1d done (185-24): 39 moved 1d names inventoried, venue bars stored in D1 but unused (study failed), 30 of the 39 carry full history from Tradier, 9 IBKR-sourced names stay SMART-only (D7 `late_heads`), and `listing_venue` (D6) records every move. Stays open for intraday: recovery is gated on the 186 rebuild (todo 497). Venue rows become kind venue under 533. |
| [435](pending/435-wire-feature-vectors-into-research-panel-all-timeframes.md) | Built as phase 184 B1 (plan 184 now, owner 2026-10-27). The research layer never reads `feature_vectors` (both families use raw 15m returns), against the adopted architecture. Wire features into S0 at 5m/15m/1h/1d with pinned windows, masked warmup and a coverage floor, after the 186 rebuild. |

## P1: High value, fully unblocked or on the critical path

**Before the 186-26 rebuild**

| Todo | Why now |
|---|---|
| [558](pending/558-pre-rebuild-feature-pass-decisions-and-registry-cleanup.md) | New 2026-10-28, owner question. Same window as 555: a stored column added after 186-26 starts needs a follow-up rebuild. Lane owners decide which candidate columns a first-batch family names (draft pass in `docs/plans/2026-10-28-pre-rebuild-feature-additions-draft.md`), retire the three never-computed rank_z registry rows with the rebuild, then fill `redundancy_group` from measured correlations. Placement and the candidate list are the assistant's proposals (Sonnet draft, needs an Opus or Fable pass); the owner's to change. |
| [466](pending/466-regime-columns-lookahead-dependents-303-304-benchmark.md) | Stored regime columns carry the todo 451 label-mask lookahead until the 186-26 rebuild. Dependents: the DEAD 303/304 verdicts benchmarked against stored `regime_volatility`; `feature_matrix.py` does not exclude the numeric `hmm_*` columns. |
| [461](pending/461-gap-z-read-the-next-bars-open.md) | `gap_z` read bar T+1's open (fixed in code in 186-12; stored rows fixed by the rebuild). Annotate the ledger's `gap_z` intraday IC read and the n1 combiner card's fold-1 G1 breach, then re-measure after the rebuild. |
| [471](pending/471-ic-measure-intraday-full-universe-memory-and-time.md) | The fresh IC writer on 15m (40 symbols) takes 17 minutes and 6.9 GB; the full universe extrapolates past host memory at block width 32. Measure block widths 4 and 8 and decide before 186-28 names its tf set. |
| [470](pending/470-ic-measure-unit-grain-resume-and-digest-pass-cost.md) | IC measure units are (job, tf): a kill loses the unit's cells, every run pays a whole-family digest pass, and a later `--start` leaves earlier member_window rows outside the DELETE range. Measure after 469. |
| [448](pending/448-research-lane-dependencies-for-phases-186-187.md) | Research-lane dependencies phases 186 and 187 plan for: item 1 (`repro_frozen.py` promoted) done in 186-03; remaining are kernel-registry memory as the single source for E17 L, one causality probe shared by `temporal_integrity` and S3, and StepM through the E17 H0 battery. |

**Quick and independent**

| Todo | Why now |
|---|---|
| [544](pending/544-ib-gateway-version-desupported-2026-12-15.md) | New 2026-10-27. IBKR warning 2172: gateway 1045.1 is desupported on 2026-12-15 (minimum 1050.1); after that, API logins may fail and IBKR ingestion stops. Upgrade the image in a fetcher gap, re-auth, verify a run. Why now: a hard external date. |
| [443](pending/443-postgres-exporter-chunk-scrape-cost-and-idle-in-transaction-timeout.md) | The postgres exporter's per-chunk scrape is the top database consumer (305 min in 3 days) and the idle-in-transaction timeout is 1 hour. Two config changes, measured before and after. Item 1 (exporter scrape) applied 2026-11-01 and verified: exporter cost now about 1.6 min/day, out of the top 5. Remaining: the idle-in-transaction timeout cut, sequenced after the 186-26 rebuild ends and compression 1078/1076 re-enable (the rebuild's compute workers legitimately idle in transaction; the timeout is reloadable, no restart). |
| [582](pending/582-one-htf-derivation-rule-set-before-the-feed-returns.md) | New 2026-11-01, P1. Owner decision 579: the feed returns, so the streaming block stays. The fork it exposed: `src/core/bar_accumulator.py` derives 1m->HTF bars with its own session logic while the batch grid derives the same 15m/1h through bar_derivation's session_grid rules; two rule sets for one derived bar diverges real-time HTF from canonical on reactivation. Converge to one rule set (or base-bars-only streaming) before the 497 unlock keys enable the feed. |
| [585](pending/585-liveness-probe-false-negative-after-an-unknown-contract-ends-the-run.md) | New 2026-11-04, P1 (lead: ahead of the vendor memo). IBKR Error 200 "No security definition" on LXP 1d was followed by a failed liveness probe, so five 2026-11-03 runs ended as gateway_lost after 4-7 good items each. Core fix landed 2026-11-04 (Error 200 charged to the name, never probed; probe timeout to APR, migration 565). Open: why the probe missed on a live session, and LXP's instrument check. |
| [581](pending/581-post-534-campaign-doors-audit.md) | New 2026-11-01, P3, gated on 534 closing: re-measure the five fetch-side campaign doors (head_rerun, venue_recovery, deepening gate, _campaign, truncated_bar_scan) so the fetch family does not accumulate retired doors the way the Tradier family did. |
| [439](pending/439-forward-span-integrity-write-once-oos-start-and-ic-purge.md) | Parts 1 and 3 done 2026-10-26: `oos_start` is write-once (migration 506) and the 7 forward-span looks are disclosed in the ledger. Part 2 (purge IC targets crossing it) lands with phase 186 (186-20, 186-28). |
| [438](pending/438-daily-borrow-availability-snapshot-capture.md) | Borrow availability is live-only at IBKR; every unrecorded day is lost for the forward span and the short-leg constraint. A small standalone daily job. |

**Data and onboarding**

| Todo | Why now |
|---|---|
| [444](pending/444-onboarding-tooling-classification-mapper-pair-column-orchestrator.md) | Onboarding SOP gaps 3, 5, 6: classification mapper, a manifest pair column for `spread_leg`, then one resumable onboarding command. After 431. |
| [505](pending/505-nightly-update-lane-exceeds-r4-measure-5m-pacing-ceiling.md) | New 2026-10-07, from 185-46 R4. The nightly update lane (1d plus 5m, one short request per name) measures 130 minutes today and 349 once every compute_1d name holds 5m, against R4's 120; 5m is paced by the unmeasured default 58 per 10 minutes. Measure the 5m ceiling with the rate probe, then set or justify the APR value. Gate: before 189-10 Task 2's pilot criterion is judged. |
| [537](pending/537-ibkr-1d-raw-deepening-scoped-full-scan-pass.md) | Campaign done 2026-10-18 (three full-scan runs, 1,030 no_data-confirmed floors); item 2 basis scan ran 2026-10-23 (todo 535 item 51), restore decided at plan 20. Item 3 rides with the plan 19 Task 2 `--measure` report. Runs over an hour lost the fetcher lock until 543 (fixed 2026-10-26). |

**Research: 441, 423 and 440 unpause at plan 191-20's 1d re-derive (owner 2026-10-27); 442 and 437 follow 187's selection core**

| Todo | Why now |
|---|---|
| [442](pending/442-attempt1-single-family-and-pod-books-e17-memory-rule.md) | Paused (build first). `spec.py` refuses a book mixing families 1 and 2: run single-family books plus a pod book; E17's L must add combiner and partial-adjustment reach, with H0 battery cells, before fitted combiners run. Phase 183 session owns the files. |
| [437](pending/437-first-cut-cost-model-commission-and-spread.md) | Paused (build first). Promotion needs positive net expectation; today only flat bps bands exist. Commission (likely zero at the execution broker) plus validated Abdi-Ranaldo spread, as distributions. |
| [441](pending/441-price-only-daily-families-931-names-prereg.md) | Residual momentum is in the daily residual family with 423: prereg `docs/plans/2026-10-27-daily-residual-momentum-reversal-prereg.md` (draft after two Codex rounds), members, B1 universe (1,269 unseen names) and B2 battery built (ee8c264df). Left: the full B2 battery, B3 power, the spec, registration, then the run after 191-20's 1d re-derive. Industry momentum (needs point-in-time industry labels) and sector lead-lag (intraday) stay open here. |
| [423](pending/423-phase181-short-term-reversal-prereg.md) | Residual reversal R1-R3 are members of the daily residual family (see 441); the screen's 231 names and the TSMOM sleeve are excluded by the B1 rule. Runs with 441's h = 5 spec. |
| [547](pending/547-e17-hac-lag-for-overlapping-targets.md) | E17 daily statistic landed 2026-10-30 (flat-top kernel plus influence series); daily battery down from 40+ size failures to 3 marginal ones. Owner decision: certify reversal members and book, hold `reversal_5_skip1` and momentum (S1 drift), or hold the family. B3 power still open. |
| [586](pending/586-persistent-battery-gating-cell-failure.md) | New 2026-11-04, plan 184-05. Ten gating cells of the persistent-predictor E17 battery exceed size (long tau, 1d and 5m sources, 21 and 63 smoothing, the hourly book, rk_price_percentile 126); oversize grows with persistence, consistent with an HAC lag that does not scale with weight persistence (cf. 547). Members on those routes stay refused. |
| [440](pending/440-generated-family-grammar-daily-ohlcv-931-names.md) | Unpauses at 191-20's 1d re-derive (owner 2026-10-27). Attempt 3b (ledger family 12): a registered grammar over daily OHLCV primitives, in-fold selection plus ridge, never materialized. |

**Integrity hygiene with a deadline**

| Todo | Why now |
|---|---|
| [520](pending/520-future-timestamp-guard-on-ingested-bars.md) | New 2026-10-09. The writer guard landed in 191-02 (`services/ohlcv_raw_writer.py`, APR `threshold.bar_integrity.future_bar_tolerance_s`, tested). Open remainder: the D7 1d condition, explicit deferral D-191-H (owner acknowledgement pending). |
| [522](pending/522-alpaca-execution-mechanics-shadow.md) | New 2026-10-09, pilot Workstream B. Paper-only order lifecycle validation (20 single-share orders, EOD flat, idempotent reconnect) plus the fixed slippage instrumentation spec. Single session, zero risk, independent of the 189-10 lanes; fastest path to measured own-flow slippage. |
| [527](pending/527-post-backfill-simplify-backlog-185-189.md) | New 2026-10-10; findings in docs/plans/archive/2026-10-10-simplify-findings-185-189.md. Phase 191 plan 06 consolidated the `_d1_gaps` answered-window copy; the service-side copies and the 5m shaper dedup are the explicit deferral D-191-H (owner acknowledgement pending); items 3 to 9 unchanged and open. |
| [521](pending/521-alpaca-intraday-depth-build.md) | Green-lit by the owner 2026-10-09; Phase 2 all-names canonical 5m load landed 2026-10-10 (1,502/1,502 eligible). Nightly installed 2026-10-26 (`indicagent-alpaca-nightly.timer`, 04:40 UTC): it asks SIP with its window end 20 minutes back (migration 513; the free plan 403s only a window ending near now); IEX answers carry `iex_rth`, raw only, never selected (528adc7c4). A one-time 20-day catch-up ran 2026-10-26. Left: the 33-name thin-tail no_data evidence. |
| [525](pending/525-single-day-provider-gaps-need-a-recorded-span.md) | New 2026-10-09, from the pilot's C8. DBMF misses 0.995 slot coverage on 3 single-day IBKR 5m gaps that the backward walk can never confirm empty; extend ohlcv_empty_history to record mid-history single-day spans evidenced by answered-chunk neighbors. |

**Closed by the rebuild (no separate work)**

| Todo | Why now |
|---|---|
| [411](pending/411-feature-vectors-and-regimes-stale-since-2026-08-10-nightly-job-refreshes-ohlcv-only.md) | Closed by 186-27 (the rebuild replaces the in-place refresh; design 14.2). The stale v1 `feature_vectors` was dropped 2026-11-04 (migration 570); the name now holds the empty kernel table, filled by the 584 rerun once data is complete. Closes when that rerun lands (`market_regimes`, stale since 2026-08-14, is a separate writer). |
| [426](pending/426-compressed-write-session-decompresses-whole-feature-vectors-exceeds-disk.md) | Step 1 (headroom guard, migration 362) and native-DML writes landed; the rebuild removes the need for decompress-all, and since migration 570 (2026-11-04) the old table is gone; `regime_writer` (no unit installed) still targets the v1 column contract. Step 2's scope question is now whether any in-place UPDATE writer survives the rerun; see todo 589 for the unit-scoped rewrite path. |
| [421](pending/421-feature-vectors-partial-coverage-velocity-and-never-computed-rank-z.md) | Removed at the source by the rebuild: the rank_z trio was dropped in 186-24 (migration 425), and the rebuild recomputes velocity for every symbol. Close after 186-26 with the per-feature coverage check (S0 floor, todo 435). Verified 2026-10-31: rebuild mid-flight (stage 2), and the three rank_z concept_registry rows are still `active` (todo 558 step 2). |

## P2: Real value, not urgent

| Todo | Why now |
|---|---|
| [574](pending/574-tradier-retention-date-removal-2026-11-12.md) | New 2026-10-31, from plan 191-25. The Tradier restore toolchain (ops_tradier_delete, ops_tradier_residue, its gate script, source_admission) stays whole until the backup retention date; delete it with data/backups/191/ and ops_old_store_backup.py on or after 2026-11-12, and drop the allow-list and key-reader entries naming it. Migration 550 already retired the infra.tradier_delete.* APR keys, so the gated scripts run on defaults if ever invoked. |
| [557](pending/557-resolve-the-30-d191q-1d-holds-with-an-alpaca-split-re-ask.md) | New 2026-10-28, owner deferred it past 545. 30 daily spans stay held (no bar) after the Tradier delete: 12 split-type offsets resolved by an Alpaca `adjustment=split` re-ask against IBKR, spin-off offsets and 9 pre-IBKR spans by recorded corporate actions. Both vendors' raw bars are kept, so nothing is lost by waiting. |
| [559](pending/559-cointegration-spread-family-preregistration.md) | New 2026-10-28, owner reopened the cointegration concept (ledger section 2). Pre-register a spread family tested on its trading statistic (static and Kalman hedge ratios, OU half-life), disclosing the 2026-08-07 pilot and the 471-pair screen as seen data; no look before the pre-registration. Placement and the draft are the assistant's (needs an Opus or Fable pass). |
| [560](pending/560-volume-kernels-span-the-volume-basis-seam.md) | New 2026-10-28, P1. The volume guard is transitive (downstream kernels masked over their memory), path-dependent kernels run through a seam, a dropped bar masks to the kernel's reset anchor or past a 5% dropped share, and the ctf series no longer collapses to neutral; four independent reviews (two Opus). The launch-gate framing is stale (stage 2 launched 2026-10-31); the review question is closed (four independent reviews, family final at 107f9a395); open: research panel provenance (184). |
| [548](pending/548-style-spread-regime-slot-and-time-series-construction.md) | New 2026-10-27. The owner's participation-state idea (RSP/SPY and style spreads) cannot run through the runner: S7 has no regime input slot (part A) and the runner is R1 only (part B's time-series book). Part B's synthetic power check comes first and needs neither. |
| [529](pending/529-test-suite-cleanup-remnants-and-redundancy.md) | Moved from P0 2026-10-27 (hygiene, not on the testing path). New 2026-10-10, owner directive: many tests are remnants of deleted systems (v2.x, I8, Tradier) and many are redundant; the suite burns too much time and tokens. Evidence-first cleanup per the audit report; CI green per batch. |
| [554](pending/554-remove-legacy-feature-vectors-research-readers.md) | New 2026-10-27, from plan 184-04 (184-REVIEWS row 18). The feature_vectors read boundary allow-lists two pre-184 `scripts/research/` readers and `ops_oos_holdout_eval.py`; each can still produce an uncounted look. Delete each, or re-express it as a runner spec reading through S0, and drop its allow-list entry. |
| [536](pending/536-forward-span-read-guard-for-ad-hoc-queries.md) | New 2026-10-14, from the evidence framework section 7 amendment. Runner paths refuse reads past `alpha.validation.oos_start`, but an ad hoc SQL read of the forward span is unrestricted and unlogged, which can silently void the one-spend confirmation. Pick a mechanism (capped role or view, or audited reads) and a sink for recorded looks. |
| [531](pending/531-schema-names-without-glossary-entries-rename-or-gloss.md) | Nine relations have live readers and no glossary entry (survey 2026-10-10): market_data_5m is a real naming violation, instrument_metadata overlaps instruments, the v2.x-era stack was never glossed, parity_certification_state looks dead. Gloss, rename, or drop each; nothing here blocks the rebuild. Phase 191 glossed the new raw-layer names only (191-01); market_data_5m's naming pass is the explicit deferral D-191-H (owner acknowledgement pending); the other relations unchanged. |

**With phase 186 and the streaming revival**

| Todo | Why now |
|---|---|
| [495](pending/495-integration-baseline-regen-after-phase-185.md) | New 2026-10-06, from 185-18/22. Phase 185 migrations 404-408 sit below the integration cutoff 433, so indicagent_test lacks their effects (408 is `listing_venue`, applied 185-24). 185-24 has landed: regenerate baseline and seeds now (todo 486's method). |
| [496](pending/496-two-live-db-integration-tests-red-since-185-12-and-186-23.md) | New 2026-10-06, from 185-18. test_ic_parity_replay (dropped forward_returns) and test_bar_quality_flag_quarantine (a migration 381 snapshot that 185-12 moved) read the live DB and stay red. Retire the first, rewrite the second as a live invariant. |
| [481](pending/481-rates-regime-curve-label-measures-rate-direction-not-slope.md) | The `rates` regime curve tier (TLT minus SHY) tracks the 10-year yield change (R2 0.76 daily) and its "steep" end has the opposite sign to the 10s2s slope change. Resolved 2026-11-03 to option 3: level and slope margins from the measured series, crossed into the four-quadrant label (macro layer doc). Every label changes, so fold into the 186 regime rebuild after the null-arm control. |
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
| [458](pending/458-family1-slot-alpha-as-execution-timing-overlay.md) | New 2026-09-29, family 1 iteration 3. Untested hypothesis: use the same-slot alpha only to time entries and exits for trades a slower book already makes, so no incremental spread is paid. Needs a slower book with a recorded trade list first. |

**Regime and IC engine**

| Todo | Why now |
|---|---|
| [108](pending/108-hmm-multi-seed-restart-best-likelihood.md) | Each walk-forward HMM segment fits one seed with a same-seed doubled-`n_iter` retry (`_walk_forward_hmm_full`; the single-fit `n_restarts` path was deleted in 186-13). Multi-seed best-likelihood is a robustness gap, not a proven bug. |
| [226](pending/226-regime-writer-n-iter-convergence-headroom-check.md) | Check whether the HMM `n_iter=200` cap is oversized; step 1 instrumentation is in, a small sample showed the retry at 400 firing on 2 of 15 cells. Analyze the distribution on the 186-26 rebuild run. |

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

**Registries and universe**

| Todo | Why now |
|---|---|
| [272](pending/272-instrument-tag-peer-group-coverage-auditor.md) | No automated audit for thin or missing `instrument_tags` peer-group cardinality; every gap so far was found by a person asking. |
| [397](pending/397-universe-dimension-views-and-instruments-boundary-test.md) | New 2026-09-23, from the /simplify review of the 174 fix branch. Universe dimensions as DB views plus a CI boundary test on raw `FROM instruments` reads, so a new reader cannot silently mean the wrong universe (the WR-01 failure class). `dimension_where_clause()` already removed the existing duplication. |

**v2.x retirement**

| Todo | Why now |
|---|---|
| [509](pending/509-v2x-remainder-after-185-45-fvp-coupling-dashboard-surface-ml-chain.md) | New 2026-10-07, from plan 185-45. Item 1 done 2026-10-26 (23056ccca: pipeline trimmed to three primitives, 194 modules and the plugin tier deleted, migrations 503-505). Section 4 Kafka and alert leftovers done 2026-10-26 (abea446d8 plus the alerts commit landing now: dead DLQ and I8 topics, dead alert rules, panels and dashboards, and a guard test that every queried metric is declared in code). Item 2 (dashboard signal surface, migration 521) and item 3 (ML batch chain) done 2026-10-26; the dashboard follow-ups closed with cockpit slice 1; the removed-unit `alert.lag.*` keys retired 2026-10-08 (78d4e90d7, migration 459). Left, re-verified live 2026-10-31: the vacuous I7 CI/pre-commit/tools checks on the deleted `src/intelligence/trading/` (ci.yml 114-116, pre-commit.hook check 3, check_plugin_invariants.sh, scan_binary_patterns.py, the duplicate_test_allowlist trading lines), `ANALYZE setup_performance` still in the `weekly_db_maintenance` procedure, the `shadow_registry` owner call (36 rows live), `roll_events` (57 rows, kept), and the streaming warm-up asymmetry. Supersedes the remaining scope of 056 and 223. No lane since the dashboard lane closed 2026-10-27; cleanup only, below the build lanes. |
| [510](pending/510-delete-185-38-185-43-185-45-backups-after-2026-11-06.md) | New 2026-10-08, from 185-43. Delete `data/backups/185-38`, `185-43` and `185-45` (about 5.8 GB, rollback material of the cutover and cleanup) on or after 2026-11-06 (185-43's on 11-07), once nothing has needed a restore. |

**Not in this list:** `deferred/` (phase-gated or recompute-batched) and `completed/`.
