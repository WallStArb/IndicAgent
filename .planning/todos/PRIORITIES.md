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
(cross-links 135/167/224/225/111). Todos 223 and 056 are governed by the dual intelligence-path
plan (v2.x I1-I7 may run again; archive, don't delete). History of past triage passes lives in
git and in each todo's own closure note, not in this file.

## Critical path (unified design, adopted 2026-09-26)

Sequence: `docs/plans/2026-09-26-unified-research-to-production-design.md` section 16; session
lanes and ownership: `.planning/STATE.md` "Starting a new session". Build first (owner,
2026-09-27, superseding section 16's parallel-attempts rule): research attempts are paused
until 185 and 186 land; session time goes to the build.

| Lane | Order |
|---|---|
| Build (phase 186, 25/29 done plus 186-17 partial) | 186-17 Task 2 (tuned compose apply plus after measurement, in a 449 lane gap, before the rebuild) -> 186-26 rebuild (gated on 449's 5m coverage; 478 decided 2026-10-02 (60/60/K2 seeds, migration 433), 467 measured (trigger unreachable, optional hardening), owns the 420 cleanup) -> 186-27 (closes 411, 426) -> 186-28 (471 decides its tf set). 186-23 landed and fully gated 2026-10-02 (`6915ffba4`, review fixes `aa843503c`: ic_measure manifest emission, canary gate repointed to feature_ic_scores_v2). Then 435 S0 wiring and the first feature family; 390 before `illiq` enters any family |
| Data (phase 185 gap closure; 185-44 done) | Tradier is the primary 1d source since 2026-10-03 (migration 438; raw in D1 for all 1,529 names, 1,266 canonical); IBKR 1d fallback fetch for the refused names and the HTF lane (449) are running -> 185-23 (D7 audit with the vendor-agreement check) -> 185-25 (rebuild `market_data_ohlcv` from real rows, carries 462's delete; needs the HTF lane stopped) and 185-26 (nightly Tradier 1d leg) -> 185-24 (close-out); 492 decides the vendor question; 493 waits on 185-25 and 492; 395, 387 keep the nightly honest; 431 -> 444 |
| Build (phase 187, not planned) | After 183 verification and family 2's evidence run: UCR recipe book, StepM (E18), construction rules, DAG manifest; 448's remaining items, 430 step 4, 459, 429 |
| Research and alpha (paused until 185 and 186 land) | 442 -> 437 -> attempt 2; 441 + 423 + 440 once 185 clears the daily data bar; 460, 456, 457 after |
| Quick, independent | 443, 439, 438 |

## P0: Fix soon (integrity/correctness gaps already surfaced)

| Todo | Why now |
|---|---|
| [433](pending/433-ibkr-daily-history-truncated-at-primary-listing-venue-change.md) | Silent wrong answer, owned by phase 185: SMART history starts at the last listing-venue move. 1d done (185-24): 39 moved 1d names inventoried, venue bars stored in D1 but unused (study failed), 30 of the 39 carry full history from Tradier, 9 IBKR-sourced names stay SMART-only (D7 `late_heads`), and `listing_venue` (D6) records every move. Stays open for intraday: recovery is gated on the 186 rebuild (todo 497). |
| [395](pending/395-nightly-backfill-fails-3-nights-weekly-ibkr-weekly-2fa-unattended.md) | A silent weekly data gap plus an alert route that reaches nobody. `OneshotJobFailed` routes to a no-op Alertmanager receiver (since 2026-08-15), so the weekly IBKR 2FA logout cost about three days of nightly backfill each week unseen. Since 185-09 the nightly waits on the lease instead of skipping; the receiver fix stands on its own and is small. Then a gateway-auth probe and backfill retry. |
| [501](pending/501-apply-185-s0-data-quality-handoff-in-snapshot-and-runner.md) | Blocker for the paused research lane, owned by the phase 183 session: apply `185-S0-HANDOFF.md` in `snapshot.py` and `runner.py` (D0 labels, rule versions, policy and verdict as-of pinned in the manifest). D-04 stays unmet until it lands. Gate: before daily attempts 3, 3b and 4 run (todo 442's resumption). |
| [435](pending/435-wire-feature-vectors-into-research-panel-all-timeframes.md) | The research layer never reads `feature_vectors` (both families use raw 15m returns), against the adopted architecture. Wire features into S0 at 5m/15m/1h/1d with pinned windows, masked warmup and a coverage floor, after the 186 rebuild. |

## P1: High value, fully unblocked or on the critical path

**Before the 186-26 rebuild**

| Todo | Why now |
|---|---|
| [478](completed/478-regime-volatility-1d-three-state-fit-collapses-on-250-day-windows.md) | Decided 2026-10-02: volatility HMM seeds 60/60/K2 (stage-1 arm E, stage-2 intraday PASS, migration 433, golden regenerated). Stored columns relabel at the 186-26 rebuild, its first consumer. |
| [486](completed/486-integration-conftest-replay-fails-on-migration-426.md) | Closed 2026-10-03 by 185-18: baseline regenerated at cutoff 433 with a config seed and a compressed-stub drop; the integration suite replays and runs end to end. Two live-DB tests stay red for unrelated reasons (see the todo). |
| [467](pending/467-regime-kernel-raises-on-a-constant-training-slice.md) | The regime kernels raise (hmmlearn `ValueError`) on a constant training slice instead of reporting a degenerate segment. Matters for the 186-26 rebuild run (the 186-25 writer is landed). |
| [466](pending/466-regime-columns-lookahead-dependents-303-304-benchmark.md) | Stored regime columns carry the todo 451 label-mask lookahead until the 186-26 rebuild. Dependents: the DEAD 303/304 verdicts benchmarked against stored `regime_volatility`; `feature_matrix.py` does not exclude the numeric `hmm_*` columns. |
| [461](pending/461-gap-z-read-the-next-bars-open.md) | `gap_z` read bar T+1's open (fixed in code in 186-12; stored rows fixed by the rebuild). Annotate the ledger's `gap_z` intraday IC read and the n1 combiner card's fold-1 G1 breach, then re-measure after the rebuild. |
| [471](pending/471-ic-measure-intraday-full-universe-memory-and-time.md) | The fresh IC writer on 15m (40 symbols) takes 17 minutes and 6.9 GB; the full universe extrapolates past host memory at block width 32. Measure block widths 4 and 8 and decide before 186-28 names its tf set. |
| [470](pending/470-ic-measure-unit-grain-resume-and-digest-pass-cost.md) | IC measure units are (job, tf): a kill loses the unit's cells, every run pays a whole-family digest pass, and a later `--start` leaves earlier member_window rows outside the DELETE range. Measure after 469. |
| [462](pending/462-stop-storing-synthetic-fill-bars-record-coverage-instead.md) | The backfill stored flat synthetic-fill bars for every calendar slot (81% to 83% of intraday rows), breaking `no_fill`. Carried by 185 plans 12, 18, 23 and 25 (`docs/plans/2026-09-29-intraday-bar-store-redesign.md`); 185-25 deletes the existing placeholders by rebuilding the table from real rows (copy and swap, owner 2026-10-03), after the HTF lane stops. The 449 HTF lane already runs with `--real-bars-only` and the 5m lane waits on this. |
| [446](completed/446-stored-1h-bars-drop-first-half-hour-on-39-symbols.md) | Closed 2026-10-06 by 185-24: the derived grid (185-11/12/25) gives every name a 09:30 1h bar (SPY 5,086 since 2006) and D7 reports zero masked 15m/1h slots. |
| [449](pending/449-intraday-5m-backfill-for-the-698-names-without-it.md) | Raw 5m only for the 931 `compute_eligible_1d` names (owner 2026-10-06; 15m and 1h derive from 5m, vendor 15m/1h already fetched for 296 names stays as the parity archive). Phase 189 fetcher queue is stopped until it is 5m only and `PAUSE_5M` is gone; measure a pilot first. Gates the 186-26 rebuild. Wrapper cleanup is 189-07. |
| [448](pending/448-research-lane-dependencies-for-phases-186-187.md) | Research-lane dependencies phases 186 and 187 plan for: item 1 (`repro_frozen.py` promoted) done in 186-03; remaining are kernel-registry memory as the single source for E17 L, one causality probe shared by `temporal_integrity` and S3, and StepM through the E17 H0 battery. |

**Quick and independent**

| Todo | Why now |
|---|---|
| [443](pending/443-postgres-exporter-chunk-scrape-cost-and-idle-in-transaction-timeout.md) | The postgres exporter's per-chunk scrape is the top database consumer (305 min in 3 days) and the idle-in-transaction timeout is 1 hour. Two config changes, measured before and after. |
| [439](pending/439-forward-span-integrity-write-once-oos-start-and-ic-purge.md) | `oos_start` is a mutable APR key guarding the forward span: make it write-once, purge IC targets crossing it (lands with 186's fresh ic_engine), disclose the 7 recorded looks (E18). |
| [438](pending/438-daily-borrow-availability-snapshot-capture.md) | Borrow availability is live-only at IBKR; every unrecorded day is lost for the forward span and the short-leg constraint. A small standalone daily job. |

**Data and onboarding**

| Todo | Why now |
|---|---|
| [387](pending/387-nightly-backfill-detect-gaps-cost-scaling-and-staleness-observability.md) | OHLCV freshness is the input to every book. Measure `detect_gaps()`'s nightly cost at 233+ symbols before fixing; add the staleness gauge and APR alert threshold left over from todo 382. Fix shipped by phase 189 (the `ohlcv_coverage` ledger replaces the full-window scan; staleness gauge `ohlcv_coverage_sla_breached_series`, though todo 498 keeps it off Prometheus); closes at 189-09. |
| [431](pending/431-stratified-sourcing-onboarding-holds-one-transaction-across-ibkr-calls.md) | Delete the second instrument writer (`--commit` in the stratified-sourcing and pilot-draw scripts) so draw scripts only draw; the manifest onboarder is the documented path. |
| [444](pending/444-onboarding-tooling-classification-mapper-pair-column-orchestrator.md) | Onboarding SOP gaps 3, 5, 6: classification mapper, a manifest pair column for `spread_leg`, then one resumable onboarding command. After 431. |
| [376](pending/376-survivorship-bias-active-only-universe-no-owner.md) | Close when phase 185 D0's survivorship label is on every attempt (D8 descoped by the owner 2026-09-26); the retroactive fix stays with the gated vendor stage. |
| [502](pending/502-d7-judges-only-compute-1d-so-unpromoted-names-can-never-pass-the-gate.md) | New 2026-10-07, from 185-41 finding 1. D7 writes verdicts only for the `compute_1d` and `compute` names, so the 27 unpromoted names (and any name whose 5m lands later) are held "missing" forever and the onboarding promote stage cannot succeed. Judge the `backfill` dimension for 1d and every active name with 5m rows for intraday. Gate: before the next onboarding wave's promote step. |
| [503](pending/503-amend-swap-plans-to-two-generic-nightly-lanes.md) | New 2026-10-07, owner answers on the swap plans. Amend 185-46/47/48 and 189-10 to two generic nightly lanes (shallow update since last fill for 1d and 5m, deep gap-fill lane) and Tradier history as a valid frozen source. Gate: before executing 185-46. |

**Research, paused until 185 and 186 land**

| Todo | Why now |
|---|---|
| [442](pending/442-attempt1-single-family-and-pod-books-e17-memory-rule.md) | Paused (build first). `spec.py` refuses a book mixing families 1 and 2: run single-family books plus a pod book; E17's L must add combiner and partial-adjustment reach, with H0 battery cells, before fitted combiners run. Phase 183 session owns the files. |
| [437](pending/437-first-cut-cost-model-commission-and-spread.md) | Paused (build first). Promotion needs positive net expectation; today only flat bps bands exist. Commission (likely zero at the execution broker) plus validated Abdi-Ranaldo spread, as distributions. |
| [441](pending/441-price-only-daily-families-931-names-prereg.md) | Paused (build first). Shortest path to a tradeable verdict: residual and industry momentum and sector lead-lag on the 931 names, no feature pipeline needed; with 423, once 185 clears the minimum data bar. |
| [423](pending/423-phase181-short-term-reversal-prereg.md) | Paused (build first). Short-term reversal on single names, market-neutral (family 4, attempt 3 with 441). Disclose the in-sample hint (IC about -0.026) and exclude its symbols and window; needs V2 at low persistence first. |
| [440](pending/440-generated-family-grammar-daily-ohlcv-931-names.md) | Paused (build first). Attempt 3b: a registered grammar over daily OHLCV primitives, in-fold selection plus ridge, never materialized. |

**Integrity hygiene with a deadline**

| Todo | Why now |
|---|---|
| [390](pending/390-illiq-series-unguarded-division-by-zero-dollar-volume.md) | `_amihud_illiq_z_series_full` (`src/intelligence/features/kernels/volume.py:291`) floors volume but not close, so a `close=0` bar divides by zero into `illiq`. Fix before `illiq` enters any family; add a floor matching `log_rets_abs` and check NaN conventions. |
| [429](pending/429-integration-conftest-replay-broken-since-322.md) | `tests/integration/conftest.py` cannot rebuild `indicagent_test` (replay fails at migrations 322 and 328), so every integration test errors at setup, including the research ledger's DB tests. Regenerate the baseline and bump the cutoff. |
| [430](pending/430-terminology-enforcement-curate-then-ratchet.md) | The glossary check enforces about a third of its bans (quoted Banned lines never parse), skips multi-word identifiers, and never scans dashboard, YAML or SQL. Curate, fail loud on unparseable rules, extend coverage, hold a ratchet; research renames in phase 187 (step 4). |

**Closed by the rebuild (no separate work)**

| Todo | Why now |
|---|---|
| [411](pending/411-feature-vectors-and-regimes-stale-since-2026-08-10-nightly-job-refreshes-ohlcv-only.md) | Closed by 186-27 (the rebuild replaces the in-place refresh; design 14.2). Features and regimes stale since 2026-08-10 until then. |
| [426](pending/426-compressed-write-session-decompresses-whole-feature-vectors-exceeds-disk.md) | Closed by 186-27. Step 1 (headroom guard, migration 362) and native-DML writes landed; the rebuilt table is written append-only and compressed per chunk, so the whole-table decompress session is not needed. |
| [421](pending/421-feature-vectors-partial-coverage-velocity-and-never-computed-rank-z.md) | Removed at the source by the rebuild: the rank_z trio was dropped in 186-24 (migration 425), and the rebuild recomputes velocity for every symbol. Close after 186-26 with the per-feature coverage check (S0 floor, todo 435). |
| [494](pending/494-unit-tests-can-spawn-live-writers-ci-guard.md) | New 2026-10-06, from 185-18. Unit tests leaked into the live database three times (a real grid derivation, permanent D1 fixture rows, a self-cleaning live write). Add a conftest guard on subprocess spawns of derivation and pipeline scripts and a boundary test on live-DSN writes; move the atomic-write test to indicagent_test. |
| [491](pending/491-universe-membership-pinned-in-the-s0-snapshot.md) | New 2026-10-03. The research spec names a universe dimension, not a snapshot, and `instruments` has only `created_at`, so promoting wave 2 changes the panel silently. Store entry date and cohort per name and hash the promoted symbol set into the S0 snapshot and `research_run`, before the first counted run. Also records that today's-cap-rank selection is outcome-conditioned. |

## P2: Real value, not urgent

**With phase 186 and the streaming revival**

| Todo | Why now |
|---|---|
| [495](pending/495-integration-baseline-regen-after-phase-185.md) | New 2026-10-06, from 185-18/22. Phase 185 migrations 404-408 sit below the integration cutoff 433, so indicagent_test lacks their effects (408 is `listing_venue`, applied 185-24). 185-24 has landed: regenerate baseline and seeds now (todo 486's method). |
| [496](pending/496-two-live-db-integration-tests-red-since-185-12-and-186-23.md) | New 2026-10-06, from 185-18. test_ic_parity_replay (dropped forward_returns) and test_bar_quality_flag_quarantine (a migration 381 snapshot that 185-12 moved) read the live DB and stay red. Retire the first, rewrite the second as a live invariant. |
| [493](pending/493-tradier-nightly-intraday-capture-5m-15m.md) | The nightly's intraday half for Tradier (5m and 15m, about 8 weeks deep, no 1h): where raw lands, the consolidated-volume seam and session edges are undecided. Plan after 185-25 and todo 492. |
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
| [457](pending/457-family1-slot-subsets-through-the-runner.md) | New 2026-09-29, family 1 iterations 1-3. The opening and closing slot subsets, the 30-cell conviction grid and the 32-cell liquid-close grid ran outside the runner, so they are not in the E18 selection universe. After phase 187 adds a slot-subset mask and the keep gate, rerun them in exploration mode on the 233 and the 201-name sets. |

**Data and ingestion**

| Todo | Why now |
|---|---|
| [453](pending/453-ibkr-backfill-concurrency-probe-then-pipelined-persistence.md) | New 2026-09-27, filed from 449 lane monitoring. Big IBKR backfills are bound by the serial walk loop, not our config: rate cap measured at 3.4x headroom (never engages for heavy TFs), chunk days already at probed ceilings. The "one heavy history stream" finding was a confounded test (4 processes, 4 connections, 4 limiters). Controlled single-connection concurrency probe in a quiet window, then pipelined persistence (or bounded concurrency, if it survives). Speeds every future big backfill; the probe itself is blocked while 449's chain fetches. |
| [455](pending/455-drop-1m-from-nightly-backfill-defaults.md) | New 2026-09-29. The nightly and the pipeline default still fetch 1m (90d x 233 symbols per night) though the compute stack is 5m/15m/1h/1d; only reader is `ret_div_1m_5m` (about 1% coverage, no measurable sessions). Drop 1m from the defaults; settle that feature with 186-15. Wait for a gap in todo 449's lanes before editing the pipeline. Phase 189's fetcher already omits 1m from its default scopes; the `ret_div_1m_5m` decision stays with 186-15; closes at 189-09. |
| [488](pending/488-nightly-backfill-hang-holds-priority-lease.md) | New 2026-10-02, from the nightly wedge. The nightly pipeline issues history requests with no per-request timeout and no watchdog, so a silent ib_async socket death wedges it in `select` while it holds the priority lease - today for 4h40m at 25/233 symbols, starving every HTF lane attempt behind it (second silent-hang-class incident in two days). Bound each request with `asyncio.wait_for` + an `infra.ibkr.*` APR timeout, retry/reconnect, fail the symbol and move on. Fix shipped by phase 189 (progress-aware stall bound with reconnect plus systemd watchdog on the new fetcher); closes at 189-09. |
| [498](pending/498-otel-collector-drops-every-job-labelled-metric.md) | New 2026-10-06, found at the 189-06 cutover. The OTel collector drops every metric carrying a `job` label (`duplicate label names`, since 2026-06-22), so `job_completed_total` and the fetcher's staleness gauge never reach Prometheus and the D-06 oneshot contract is dark. Rename the label or stop the constant `job` label; sweep dashboards and alert rules. |
| [499](pending/499-drop-normalize-bars-and-move-gap-readers-to-coverage-ledger.md) | New 2026-10-07, from plan 185-32 (phase 189 session). The store refuses synthetic_fill (migration 444) and CI fences new fill paths; `normalize_bars`' last caller in `_history_fetch_item.py` is unreachable. Drop it, delete the fill path and its two TEMPORARY allow-list entries, and move the 5m/1m placeholder-coverage gap readers onto `ohlcv_coverage`. |
| [492](pending/492-tradier-vs-ibkr-vendor-reconciliation-and-production-token.md) | Tradier is the primary 1d source (2026-10-03) but 6.5% of closes and the volume basis (0.96 of Tradier's in 2006, 0.55 in 2026) differ from IBKR's and neither is known right; HON sits a constant 0.33% off; the token is a sandbox one. Arbitrate against corporate actions, known-corrupt prints and 5m-implied ranges; decide the volume basis; get a production token. |
| [500](pending/500-tradier-replaced-bars-hidden-by-stale-price-sanity-status.md) | New 2026-10-07, from 185-34. Ten clean Tradier bars (SPY, GLD, IWM and others) are hidden by a stale legacy price_sanity_status; fix through the one daily writer in 185-36, then retire the filter in 185-43. Also records the pending owner decision on the ISLAND head rule (switch is off). |
| [497](pending/497-186-27-sets-the-intraday-recovery-unlock-keys.md) | New 2026-10-06, from 185-20. 186-27 sets infra.bar_derivation.intraday_recovery_unlocked and rebuild_state_table at rebuild completion; the recovery tool also needs the venue study's 5m verdict. Venue fallback is 1d-only (437). |
| [490](completed/490-grid-stage-archive-verify-fails-on-revised-bars.md) | Closed 2026-10-07 by 185-31: the grid stage writes by the write contract and verifies vendor removals by value; the 7 symbols are derived and the stage exits 0. |
| [454](pending/454-ultra-thin-traded-series-treatment.md) | New 2026-09-28, filed from the 185-10 historical scrub pass (todo 052 defect-class sweep; docs/research/scrub-historical-pass.md). Ultra-thin traded series: RCAT clears volume>0 for years at volume <= 30 shares; 6 of the top 20 largest 1d moves are this one name; no scrub rule fires (too sparse for the 61-bar window). Measure the class distribution, then decide with the owner: universe eligibility dimension vs informational rule. Raw bars untouched either way (D-09). |
| [363](pending/363-ib-gateway-libgtk3-fix-not-durable-across-recreation.md) | `libgtk-3-0` was missing from the `ib-gateway:stable` image (root cause of the 16-day outage), installed live in the container; it survives restart but not recreation. Bake it into a small wrapper Dockerfile. |
| [052](completed/052-adversarial-data-error-hunt.md) | Closed 2026-10-06 by 185-24: known answers pinned (185-01), D2a rules proven on them (185-05), historical pass run (185-10); the new error class found is todo 454. |
| [155](completed/155-price-sanity-status-historical-backfill.md) | Closed 2026-10-06 by 185-24: replaced by 185-10's historical scrub pass into `bar_quality_flag` (minutes, not years) and the nightly rerun in the daily derivation. |
| [347](completed/347-price-sanity-index-column-order-mismatch-bar-auditor-query.md) | Closed 2026-10-06 by 185-24: migration 381 (185-04) dropped the index once the batch pass replaced its scan. |
| [317](pending/317-backfill-status-migrate-to-anti-join-checkpoint-pattern.md) | New 2026-08-14, split out of todo 316's `/simplify` altitude review. `backfill_status.status='complete'` is the only side-table checkpoint of its kind left in `services/*.py` — every other batch writer (`alpha_frame_writer.py`'s documented "Pattern 4", `regime_writer.py`, and `ic_engine.py` which deleted a decoupled `.pkl` checkpoint outright for this same root cause) queries the target table directly instead. Todo 316's fix reconciles the desync after the fact; this is the deeper fix — eliminate the second source of truth. Not urgent: 316 already makes the current design self-detecting/self-healing. |

**Held under the IC proposal and in-fold selection methods**

| Todo | Why now |
|---|---|
| [191](pending/191-feature-scoring-beyond-ic.md) | Held under the `ic_proposal`/`in_fold_selection` methods of the unified design: feature scoring beyond IC. |
| [038](pending/038-cross-sectional-collinearity-diagnostic.md) | Held under the `ic_proposal`/`in_fold_selection` methods: cross-sectional feature collinearity diagnostic against IC. |
| [099](pending/099-bootstrap-ci-staged-validation-gate-not-cleared-5m-residual.md) | Held under the `ic_proposal`/`in_fold_selection` methods: why 5m autocorrelation and momentum features resist both Fisher-z and block-bootstrap CIs (non-blocking). |
| [039](pending/039-tag-stratified-ic-population-check.md) | Held under the `ic_proposal`/`in_fold_selection` methods: population-count check before tag-stratified cross-sectional IC. |

**Regime and IC engine**

| Todo | Why now |
|---|---|
| [420](pending/420-market-regimes-orphan-rows-from-pre-tradeable-writer.md) | Triage 2026-09-26: regime refit bundle anchored on 248. New 2026-09-24 (179 V4). 186-18 landed the atomic per-(group, tf) replace with a shrink guard and measured it: 3.51M orphans (1.22M weekend, 2.29M weekday), J = 510,835 join feature_vectors, so the cleanup run (`--accept-orphan-delete=N --accept-changed=M --reason`, then VACUUM) waits for 186-20's parity report and is owned by the 186-26 executor. |
| [406](pending/406-ic-math-1087-invalid-divide-warning-unexamined.md) | **Re-tiered P3->P2 2026-09-26 (triage): see the todo triage note.** New 2026-09-24, carried out of closed todo 386. Unexamined `invalid value encountered in divide` warning in ic_math's downside-deviation line; check the next corpus run log and whether a NaN reaches `ic_sortino`. |
| [504](pending/504-dividend-event-writer-source-registry-and-per-symbol-failure-policy.md) | New 2026-10-07. The dividend writer hard-codes Yahoo and IBKR in its reconciliation and metrics, and one bad symbol (PSKY) fails the unit nightly. Make sources a registry, reconcile pairwise, and fail the run only past an APR threshold with an alert. |

## P3: Hygiene, docs, process, performance (opportunistic)

**Dated**

| Todo | Why now |
|---|---|
| [483](pending/483-record-2026-midterm-forward-window-result.md) | New 2026-10-01. Due after 2027-05-03: record the pre-registered 2026 midterm forward window (S&P 500, election day to +6 months) in the idea doc and ledger, as one unsearched observation. Nothing else forces this step. |
| [484](pending/484-htf-lane-honor-quarantined-symbols-file.md) | New 2026-10-01, from the reboot-day HOOD quarantine. A poisoned name costs ~18 min/attempt for up to 50 attempts; today's fix was sed-editing the tracked `all.symbols`. Lane scripts should subtract `quarantined.symbols` instead; lands at todo 452's cutover stop, never mid-loop. Superseded by the `consecutive_failures` column on `ohlcv_coverage` (phase 189); closes at 189-09. |
| [485](pending/485-rate-limiter-wait-logging-in-ibkr-py.md) | New 2026-10-01, from reboot-day ops. `_hist_limiter_for().acquire()` logs nothing while a request waits for pacing budget, so normal throttle during rescan reads as a hang (caused one premature kill today). One `hist_pacing_wait` log line per blocked request. |
| [487](pending/487-run-spec-synthetic-defaults-cannot-express-spec-gates.md) | New 2026-10-02, from the 183 UAT. `run_spec --mode synthetic` defaults (30 names, 400 sessions, start 2006-07-03) cannot pass a real spec's gates: PR 60 is unattainable at 30 names (generator crash) and 400 sessions end 2008-01-11 so the `trading_start` filter empties the E17 measurement, refusing every member with an unprinted reason. Validate loudly and name the minimal flags instead. |

**Kernel and feature code (phase 186 follow-ups)**

| Todo | Why now |
|---|---|
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
| [398](pending/398-ic-engine-scratch-dir-shares-db-filesystem.md) | ic_engine memmap scratch (`/var/tmp`) shares a filesystem with the TimescaleDB volume; a free-space reserve guards it (migration 352). The structural fix is scratch on separate storage. |
| [360](pending/360-broadcast-day-constant-empirical-classifier.md) | `_TEMPORAL_BROADCAST_FEATURE_NAMES` is a hand-verified 3-name allowlist; replace it with an empirical within-day-variance classifier mirroring `ops_broadcast_feature_audit.py`. Current scope is correct, only narrow. |
| [009](pending/009-service-utils-ic-engine-cleanup.md) | Parts B and C remain: promote 4 scripts to `BaseBatch` plus systemd, and the naming-vocab doc update. Parts A, D and E closed; the ensemble items went with 186-19. |
| [228](pending/228-corpus-pipeline-unmeasured-steps-io-vs-cpu-triage.md) | Classify the remaining corpus pipeline steps as I/O- or CPU-bound before applying the thread-tuning lessons of 215/216; needs one full timed run (steps 7-8 left the pipeline in 186-21). |

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
| [056](pending/056-phase146-147-v2x-retirement-stale.md) | v2.x decommission in fact (archive, not delete, per the dual intelligence-path plan): git mv the code to archive/, disable dead units, rename-not-drop the frozen tables. Needs a clean git state. |
| [223](pending/223-src-intelligence-i1-i7-dead-code-153-files-30k-lines.md) | `src/intelligence/`'s I1-I7 tree (~153 files, ~30k lines) has no live entry point. Needs the archive-versus-delete call (dual intelligence-path plan: archive) and a matching call on the dead-pipeline and SLA/I7 tests. With 056. |
| [275](pending/275-v3-north-star-precedentengine-mechanics-predate-d4-rescope.md) | New 2026-08-06, found while doing the AnalogEngine→PrecedentEngine naming correction during a Phase 145 discuss-phase session. `docs/foundation/v3-north-star.md`'s PrecedentEngine mechanics (Score Object, independent-annotator framing, `signal_events` target) predate the D4 rescope that corrected exactly this framing elsewhere (glossary, `intel-precedent-engine.md`). Naming fixed inline + flagged; the mechanics reconciliation itself is real design work, not done here. No live consumer reads this doc's mechanics section today. |

**Not in this list:** `deferred/` (phase-gated or recompute-batched) and `completed/`.
