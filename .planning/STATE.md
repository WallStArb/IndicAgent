---
gsd_state_version: 1.0
milestone: v3.5
milestone_name: Unified Research Pipeline
status: in_progress
last_updated: "2026-10-10T15:35:00.000Z"
progress:
  total_phases: 8
  completed_phases: 2
  total_plans: 105
  completed_plans: 104
  percent: 25
---

# Project State

Current position only. History: git, `.planning/MILESTONES.md`, and the archived state at v3.4
close (`.planning/milestones/v3.4-STATE.md`). Don't stack dated narrative here; replace stale
bullets with current facts.

## Strategic plan (read this first)

- **The design:** `docs/plans/2026-09-26-unified-research-to-production-design.md`, ADOPTED
  2026-09-26 with methodology-change-ledger E18. It owns the sequence (section 16). One pipeline
  from data to a frozen book; the old ensemble chain is deleted; costs never enter a test
  statistic but promotion needs positive net expectation; every look at the vintage is counted and
  selection is by Romano-Wolf StepM; each book gets its own forward span (feature books never
  before 2026-08-08, after 7 recorded holdout looks); raw data is permanent, derived data is cache.

- **Milestone v3.5 Unified Research Pipeline, phases 183-188** (ROADMAP.md). Build first (owner,
  2026-09-27): session time goes to building, and research attempts (1a-1c, todo 442; the cost
  model 437; daily families 441, 423, 440) are paused until 185 and 186 land. This replaces
  design section 16's "attempts run in parallel with the build". The tooling for them is ready
  (E17 and its static-size precondition, 447). Build:
  186 (delete, drop, rebuild `feature_vectors`, refactor items 1-6) -> 187 (research core) -> 184
  -> feature books -> 188 (forward runner, capital tier). 185's derived 15m and 1h grid (D2b,
  todo 446) lands before 186's rebuild; 184 builds on that grid and 186's kernel registry (UD-25).

- **Evidence rules:** E15 (book as the unit), E16 and E17 (timing statistic), E18 (counting,
  selection, promotion, per-book span). Until phase 187 lands, the phase 183 runner's M = 30
  accounting stays in force for any book test.

- **Research record:** `docs/research/construction-verdict-ledger.md` until phase 187 generates it
  from UCR (fully reconciled 2026-10-08). Check it before recommending a candidate.

## Current position

Phase: 190 (Provider history plane unification) — EXECUTING
Plan: 6 of 7 done (190-06 cutover landed 2026-10-10: 465 applied with the writer
conflict-target flip at CUT_TS 11:59:48Z, the renamed `ohlcv_history_fetcher` is the
installed unit, parity PASS recorded, two clean post-cutover runs; 07 wrap-up remains)

- **HOLD 2026-10-10 (owner): no data pulls of any kind until the data-plane refactor lands.**
  The IBKR backfill stays held (timer disabled, ledger keeps state); `ops_bar_nightly` exists
  but nothing schedules it. Reopen is the owner's call.

- **Raw-capture enforcement (todo 528) landed 2026-10-10:** the load engine archives
  non-authored rows (extended + other-source-held) instead of dropping them; migration 468 put
  source in the raw-archive key; the R6 completeness check is `ops_capture_completeness`; the
  recovery pass over the dropped 81.7M rows is in flight (a first pass double-archived 88.27M
  self-authored rows — the split now holds only other-source rows; the duplicates are being
  removed from the archive under a logged trigger exception). T4 landed: `src/providers/alpaca.py`
  behind `history_leaf` and `ops_bar_nightly` (5m authors through the engine, 1d raw-only;
  APR seeds in 469, applied live). Alpaca 5m is LANDED (216.8M rows, 1,478 symbols, 2026-10-10).

- **Data layer end-state 2026-10-09 (owner rulings, governs all data work):** all 1,529 active
  names are intraday scope (the 233-name subset is overruled; registry promotion of the other
  1,296 goes through the SOP/185-41 gates after their 5m exists). Alpaca is green-lit as the 5m
  source (todo 521 build in flight: pilot passed, phase 1 pull done, and the phase 2 all-names
  canonical 5m load is RUNNING since 2026-10-10, launched by session indicagent-87 after two
  chunk-buffer fixes; 150-250M rows, hours). IBKR stays the 1d
  primary; the full-depth 5m backfill (owner-ordered 2026-10-09 as a completeness campaign, todo
  523 record) is PAUSED by design 2026-10-10: fetcher timer stopped and the in-flight run killed
  so the Alpaca load gets a clear table; the timer restarts when the load reports done. Raw capture
  is universal (both vendors nightly), authoring stays single-source per span; depth planning
  moves to per-TF provider floors (todo 526, 189-11).

- **Phase 183** (other session): all 11 plans done (plan 10 on 2026-09-26); phase UAT complete
  2026-10-02 (183-UAT.md: 12 tests, 10 pass, 2 minor issues both resolved; synthetic-smoke
  invocation gotchas in its test-10 note, todo 487). Family 1 evidence done (HAC t 13-19 gross, biased toward zero under E16; about 26x
  turnover per session, untradeable net at 1 bp); book_v1 refused (E16 bias, uncharged); E17
  built and its gating decided (option C); its per-family static-size guard is in the runner
  (todo 447, 2026-09-27) and families 1 and 2 pass it. Family 2's evidence run is unblocked.
  Family 1 exploration 2026-09-29 (iterations 1-4, in-sample; iteration 1 ran through the runner as `family1_h{2,4,8,26}` specs, 16 evidence rows, iterations 2-4 outside it): the edge sits at the
  opening and closing auction prints; no slot, keep or timing tried is net positive at measured spreads;
  next are todo 460 (auction price check, auction-to-auction hold) and todo 458 (overlay).

- **Phase 185:** original 26 plans executed 2026-10-06; verification found gaps (`185-VERIFICATION.md`), so gap closure plans 27-44 and 189-07..11 implement the approved data layer integrity design (`docs/plans/2026-10-06-data-layer-integrity-design.md`: Tradier primary 1d with IBKR fallback via `bar_source_policy`, one daily rule d2-v2, lineage as a view, one write contract, 15m/1h/4h derived from 5m, raw 5m only for the promoted names, verdict-based gates, then cleanup). Done: 185-27, 185-30, 185-44 (complexity baseline plus three CI guards). 1,502 names are promoted `compute_eligible_1d`, 27 held. The IBKR fetcher service and timer were re-enabled 2026-10-09 (full-depth 5m backfill; paused 2026-10-10 for the Alpaca load, see the data layer end-state above). Order: ROADMAP.md; handoff: `.planning/phases/185-daily-data-foundation/.continue-here.md`.
  2026-10-02 (185-12): the 15m/1h grid is derived from tradeable 5m (233 symbols rewritten,
  33.2M derived rows, original observations in `ohlcv_intraday_raw_archive`, pipeline fetches
  rerouted there, nightly grid stage chained with `--changed-only`), which satisfies 186's D-32
  precondition. D2 is the sole 1d writer and derived the whole history (185-17 rule, 185-18 apply
  2026-10-03: 931 names, 3,877,335 lineage rows at d2-v1; migration 435 gave the writer UPDATE; one
  pre-fence orphan bar, TLT 2026-10-01, heals at the next 1d fetch). Todo 490 (P1): the grid stage
  fails nightly for 7 symbols whose recent bars were observed twice; until fixed, every 189 fetcher run that lands 5m rows ends `partial`. D3 is on D1 (185-19,
  migration 404): the provider never returns venue bars, 1d empty history is derived from recorded answers (89 of
  115 rows deleted for want of recorded confirmation, re-asked at each name's next 1d fetch). D5's IBKR dividend route reads D1 (185-21: migration 403,
  26 date disputes on 18 names, verdict "not usable alone; Yahoo stays reference"; reader
  hand-off to phase 183 in the phase dir). The remaining ~700 names derive as todo 449's 5m
  backfill reaches them (7 lane symbols excluded at rewrite time; 1 no_5m). Next: 25, 26, 24.
  Price-integrity layer (D2a scrubbing, flag never delete; D7 reconciliation).
  Owns todo 433 (P0). Lease-free fetch callers still allow-listed: `185-daily-data-foundation/deferred-items.md`.
  Migration numbers 400 to 408 are reserved for 185's plans 15, 13, 17, 21, 19, 20, 22, 23, 24 (their old
  number plus 16, because phase 186 took 384 to 389); other phases keep taking the next free number below 400.
  Plans 12, 18 and 23 carry the todo 462 intraday redesign (`docs/plans/2026-09-29-intraday-bar-store-redesign.md`).
  Plan 13's venue study failed both timeframes, so venue bars stay stored and unused; plan 14 left 42 late
  names unresolved because the ISLAND route never answers (`docs/research/moved-name-inventory.md`).

- **Phase 189 (IBKR history fetch consolidation, independent of 183-188):** 9 plans; 01 to 05 done,
  06 cutover executed 2026-10-06 (wrap-up and SUMMARY remain), 07 to 09 pending (delete nightly and
  lane scripts; absorb the pipeline into `_history_fetch.py` and retire the lease APR keys; docs and
  close todos 488, 452, 387, 455, 484). Live now: oneshot `indicagent-ibkr-history-fetcher` (timer,
  15 minutes after each run, client 40, systemd watchdog 20 min, advisory lock
  `lock:ibkr_history_fetcher:*`), the `ohlcv_coverage` ledger (migration 432, written in the same
  transaction as bars and requests, rebuilt in place at cutover), the Tradier daily loader and the D7
  audit on their own timers. The nightly timer is disabled (stopped 2026-10-02), the lease and lane
  scripts are off the live path but still on disk until 189-07 and 189-08. Handoff:
  `.planning/phases/189-*/.continue-here.md`. Open: todo 490 (runs ending `partial`), todo 498
  (the OTel collector drops every `job`-labelled metric).

- **Phase 186:** 29 plans, executing since 2026-09-27 (`/gsd-execute-phase 186`, waves 1-10
  sequential, one executor at a time). 25 of 29 done (01 to 16, 18 to 25, 29; waves 1-3 complete, 15, 18, 19 and 20 in wave 4; 186-20 parity gate accepted by the owner 2026-10-01 on the legacy-replica criterion, stored feature_ic_scores holds IC 0.0 for features with missing values); 186-17 partial (Task 1 done, Task 2 Postgres restart refused while the todo 449 backfill is live; unblocks in a backfill lane gap or after 449 and before 186-26); 186-22 dropped nine old-chain tables (migration 426, 50.7 GB freed); 186-29 landed after the owner released the research lane. No executor live; remaining 17 Task 2, 26, 27, 28. 186-26 was held for 185-18's historical 1d D2 apply (landed 2026-10-03); it still needs todo 489's `check_d2_landed` gate and todo 449's 5m coverage; 186-24 made feature_vectors_v2 312 columns (Asian session pair kept), 186-25 and 186-27 plan literals updated.
  Cross-AI review closed with all HIGHs integrated (`186-REVIEWS.md`). The `feature_vectors`
  rebuild covers 15m, 1h, 1d and 5m (todo 445 decided keep_5m, 2026-09-28); the 5m name set is
  `ret_autocorr_1` and `sweep_detected` at the 233 `compute_eligible` names, and still needs
  185's derived grid (todo 446). The fresh ic_engine computes targets with `panel.forward_returns`;
  the `forward_returns` table is dropped after parity (UD-25, design 14.7). Phases 187-188: not
  planned; 187 waits on family 2's evidence run and the research lane's release.

- **Quick, independent todos:** 443 (exporter scrape cost, idle-in-transaction timeout), 439
  (write-once `oos_start`), 438 (daily borrow snapshots; standalone again since D8 was descoped).

- **Intraday backfill (todo 449):** carried by the phase 189 fetcher queue since the 2026-10-06
  cutover (the old chain and HTF lane, client 46, were stopped 12:33Z). The queue ranks by coverage
  gap and staleness: zero-coverage names first, 15m and 1h before 5m, 5m scope per
  `infra.backfill.default_scopes` (backfill 5m stays gated by todo 462). Phase 186's rebuild still gates on the 5m part.

- **Regime coverage auditor:** fails only on unregistered or expired gaps; the 5 known symbols (BIL, EMLC, ETHA, IBIT, VIXY) are registered exceptions expiring 2026-12-29 (todo 341 closed by 186-18). 1d `regime_volatility` is gated off for about 98% of segments at every refit schedule (todo 478, P1, decision needed before the 186-25/26 rebuild).
- **Universe:** 1,529 active (932 plus wave 2's 597, onboarded 2026-10-03 with the 1d fetch running); 1,502 `compute_eligible_1d` (wave 2 promoted 2026-10-06, checked 2026-10-08); 233 carry the intraday stack and
  `feature_vectors`. Lineage `config/universe/README.md`; process
  `docs/foundation/instrument-onboarding-sop.md` (tooling gaps: todos 431, 444).

- **Data freshness:** features and regimes stale since 2026-08-10 (todo 411, now replaced by the
  phase 186 rebuild); live IBKR streaming down; nightly batch backfill refreshes OHLCV only.
  Check `max(timestamp)` before citing freshness.

## Starting a new session

Read in order: this file -> `ROADMAP.md` (active milestone table) ->
`docs/plans/2026-09-26-unified-research-to-production-design.md` (sections 2, 16 and the section
for your work) -> `.planning/todos/PRIORITIES.md`. Then pick one lane; lanes run in parallel.

| Lane | Start with | Owner and boundary |
|---|---|---|
| Research (phase 183) | Attempts (todo 442) paused until 185 and 186 land (owner, 2026-09-27); phase UAT complete 2026-10-02 | Released by the owner 2026-10-01 for the one-line `HarnessConfig` import switch in the five research tests (186-29); otherwise the phase 183 session owns `src/intelligence/research/` and nobody else edits it |
| Alpha, no dependencies | Paused until 185 and 186 land (owner, 2026-09-27): todos 437 (cost model), 441 and 423 (price-only daily families), 440 (`generated_family`) | Specs and new modules only; runs go through the phase 183 runner |
| Quick data and infra | Todos 443, 439, 438 (borrow snapshots; loses a day every day it waits) | Independent; 439's IC purge lands with phase 186's fresh ic_engine |
| Phase 186 | `/gsd-execute-phase 186`: 25/29 done plus 186-17 partial, no executor live; remaining 17 Task 2, 26, 27, 28, one executor at a time | No edits to modules ic_engine imports while a corpus run is live or resumable; commit only 186's own files (185 executes concurrently in this tree); designed gate stops (186-14 waits on 185-11, 186-23 on 185 D-14, 186-26 on todo 449 coverage) are reported, never forced |
| Phase 185 | Gap closure 185-27..52 done 2026-10-09: 1d primary is IBKR from D=2026-10-07; Tradier retired (loader, units, provider, APR keys); stale heads, closures, split recognition and the hold list, d2-v3 landed. Left: phase verification, 513 (nightly contract), 189-09, 189-11 (the 5m backfill is paused 2026-10-10 for the Alpaca all-names load, timer restarts after; 189-10 Task 2 scored, fetcher live). 514 (survivorship removal) done 2026-10-10: migration 466, gate condition 6 retired, docs swept | Owns ibkr.py, fetcher, bar policy. CTVA held (516); known D7 failures: CTVA, QRVO, PSKY, WBD (freshness_1d), 13 vendor_basis_run, session_coverage |

Phases 184 and 187-188 have no directory yet; `gsd-sdk query phase.add` numbers from
`.planning/phases/`, so add or plan them by number, never through `phase.add` (CLAUDE.md).

## Decisions waiting on the owner

- None open. The midterm spec was committed 2026-10-01, before the 2026-11-03 election: its forward
  window (to 2027-05-03) is recorded in `docs/ideas/signal-political-policy-regime.md`; todo 483
  records its result after 2027-05-03.

## Open items that are not verdicts

- Economic series (todo 480, 2026-10-01): `economic_series_observation` holds 10 FRED and 39 NY Fed
  series. Backfilled FRED availability times are assumed, not measured (THREEFYTP10 about a week
  early); todo 482 (deferred, gate: phase 184 B8) reloads them from ALFRED. No reader until B8.
  Owner decided 2026-10-01: long-history index levels are stored as context-only series (migration
  427: Yahoo S&P 500 from 1927 and Nasdaq 100 from 1985, FRED Nasdaq Composite from 1971); Nasdaq 100
  sources disagree on 2003-2005 closes (recorded in todo 480).

- Todo 248 (HMM per-symbol lookahead): walk-forward deployed 2026-08-12. Stored regime columns
  carry the todo 451 gate mask until the 186-26 rebuild; 186-13 made the HMM a registry kernel.
  HMM columns stay out of every family until the rebuild.

- Todo 372 (`Panel.sync_shift_null_p`): finding 1 fixed, lacks independent review; finding 2
  (`volume_z` diurnal detrending) untouched.

- N1 nonlinear combiner: structurally inconclusive; don't cite as pass or fail.
- Survivorship: every universe reads current state; phase 185 D0 bounds past verdicts. Forward
  capture (D8) was descoped by the owner 2026-09-26: few names in this universe delist, and the
  past cannot be fixed from IBKR.

## Process pointers

- `.planning/todos/PRIORITIES.md` is the sole todo priority source.
- The research ledger is the sole construction-verdict source.
- Methodology changes go through `docs/plans/methodology-change-ledger.md`.

## Key decisions (load-bearing)

- `HMM_RANDOM_STATE = 42`: changing it invalidates every regime-derived output.
- Executable returns only, open to open: `panel.forward_returns` is the one target definition
  (UD-25); the `forward_returns` table is legacy until phase 186 drops it, and new code never reads it.

- `ON CONFLICT` for partial indexes on TimescaleDB: column list plus WHERE clause, not
  `ON CONSTRAINT`.

- Phase 190 batch history surface (190-01): `HistoryProvider` protocol + HistoryRequest /
  FetchBudget / NoDataVerdict / HistoryPage live in `src/providers/base.py`; DataProvider is
  byte-identical. `IBKRProvider.fetch_ohlcv` returns one caller-driven window plus resume
  point; `adjustment='split'` raises loudly on IBKR (ADJUSTED_LAST is now-anchored). Services/
  scripts/src cannot import a concrete provider leaf outside `src/providers/`
  (tests/unit/test_provider_leaf_boundary.py; at 190-04 the three fetcher-family entries
  stayed, now owned by the registry's ibkr entry rather than a factory seam).

- Phase 190 generalized fetcher (190-04): `_PROVIDER_REGISTRY` in the fetcher maps provider
  name to leaf factory + item-fetch hook + overlay loader; the loop dispatches strictly
  through `entry.fetch` per item's provider (an entry failure is that item's error outcome,
  never an IBKR fallback), budgets come from per-provider ProviderPlan (stall bound, retries,
  inter-item pause), and the dry-run TSV carries the provider column (190-06 parity delta 1).
  Adding a vendor is one registry entry plus a leaf module; multi-plane queueing (one run,
  several providers' candidates) is still future work.

- Phase 190 code-identity rename (190-05): the fetcher is `ohlcv_history_fetcher` /
  `OHLCVHistoryFetcher` in code and tests; every external identity stayed byte-identical
  under FROZEN (phase 190 decision) comments (FETCHER_LOCK_NAME, LOCK_HELD_MESSAGE, JOB,
  status-file path, unit filenames). A compatibility shim at the old
  ibkr_history_fetcher.py path keeps the live unit runnable until 190-06 installs the
  updated unit and deletes it. The log file does not move: BaseBatch derives it from the
  frozen JOB, so logs/ibkr_history_fetcher.log stays.

- Phase 190 two-tier ledger foundation (190-02): migration 464 applied live (ohlcv_coverage.provider,
  ohlcv_provider_head.timeframe nullable; ibkr label is the authoring fetch plane of a stored-state
  row, never a vendor provenance claim). Migration 465 (PK swaps + measured floor seeds) is committed
  UN-APPLIED: 190-06 applies it with the fetcher stopped, in the same shell breath as flipping the
  coverage writer's ON CONFLICT to (symbol, timeframe, provider); the boundary test and the
  conftest _COMMITTED_BUT_UNAPPLIED={465} entry pin that discipline until then.

- Phase 190 per-provider planner (190-03): `_fetch_queue.py` is provider-parameterized with
  ProviderPlan + load_provider_plan reading infra.<provider>.* under the split contract
  (planner inputs raise, leaf-native rate-limit window keeps its logged fallback); the queue's
  candidates, due reasons and visited checks are (provider, symbol, timeframe) triples that
  still accept the legacy pairs, so the unmodified fetcher kept draining through every commit
  boundary (back-to-back dry-run TSVs identical). The bar_source_policy gate authorizes
  primary-OR-fallback (derived rows and no-row pairs fall back to the default plane), which
  keeps the two open tradier-primary 1d rows with the ibkr fallback (MOD, QRVO) fetching via
  IBKR; 190-04 passes the plans and triples the fetcher side, and 190-06 activates
  record_head_per_tf when 465 applies.

- Corpus pipeline: `--compute-only` silently skips every symbol if `backfill_status` is empty;
  seed it first (query in `.planning/milestones/v3.4-STATE.md`, "Corpus Pipeline Gotcha").

## Accumulated Context

### Roadmap Evolution

- Phase 190 added: Provider history plane unification: one multi-provider fetcher, N leaves, two-tier ledger (design: docs/plans/2026-10-09-provider-history-plane-unification-design.md; rides with todo 526)
- Phase 189 edited: edited fields: depends_on
- Phase 189 added: IBKR history fetch consolidation: single fetcher, coverage ledger, priority queue replacing the nightly/bulk lease and lane scripts
