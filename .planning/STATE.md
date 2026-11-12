---
gsd_state_version: 1.0
milestone: v3.5
milestone_name: Unified Research Pipeline
status: in_progress
last_updated: "2026-11-04T11:42:49.735Z"
progress:
  total_phases: 9
  completed_phases: 3
  total_plans: 162
  completed_plans: 150
  percent: 33
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

- **Milestone v3.5 Unified Research Pipeline, phases 183-188** (ROADMAP.md). Goal (owner
  2026-10-27): start testing families with new features, factors and regimes as soon as the data
  allows. Build first (2026-09-27) is lifted at plan 191-20's 1d re-derive. From then on, family
  2's one evidence run and the daily price-only families (441 + 423, then 440) run while the
  rebuild runs. Order: 191 (data settled) -> 186 rebuild; 184 planned now and run on the rebuilt
  table; 187 selection core (08-15) now, governance (16-18) after the first feature family;
  then feature and regime families; 188 waits on a candidate book.

- **Evidence rules:** E15 (book as the unit), E16 and E17 (timing statistic), E18 (counting,
  selection, promotion, per-book span). Until phase 187 lands, the phase 183 runner's M = 30
  accounting stays in force for any book test.

- **Research record:** `docs/research/construction-verdict-ledger.md` until phase 187 generates it
  from UCR (fully reconciled 2026-10-08). Check it before recommending a candidate.

## Session handoff (2026-11-12, lead indicagent-32; read this first)

**Position: Massive is acquired and verified, all raw loads are done, and admission is EXECUTING on the lead's call (the owner delegated sequencing and go/no-go on 2026-11-11; no admission GO is pending).** The archive holds all 11,658
files (both aggregates, 2003-09-10 to 2026-11-09, 82 GB; full `--verify` 11,658 records 0
defects, 2026-11-10). Serve times + ETags captured for every key with zero drift on re-stat.
Reference captures landed (splits complete - the AAPL/NVDA calendar gap is fixed in the
material; dividends, ticker events for all 36,869 tickers, reference sets) with a local 530 MB
tar (`data/backups/massive-reference-2026-11-10/`). The admission design
(`docs/plans/2026-11-10-massive-admission-db-design.md`) is ruled, Opus-refined
(`2026-11-10-massive-admission-refinement-review.md`, folded as 65e287edd) and execution-ready.
Offsite backup is DEFERRED by the owner (f55ff8ceb).

**Update 2026-11-12:** every Massive raw load is DONE: 2026 back to 2003 (RAW-ONLY, selection deferred
while Massive is unranked; sweep DONE 2026-11-11 23:44Z, bulk path 02f14f247; `ohlcv_raw` holds 403.3M
Massive rows). Each year passed its gate: windowed `ops_selection_gate --compare` 0 real differences
before and after, canonical counts unchanged, unselected delta equal to the loader's expected Massive-only
count; 5m 2.8M (2003 partial) to 24.8M rows a year at 30-37k new rows/s, 1d 43k (2003) to 339k. Disk 617 GB
free. Step 7 tooling landed (1561842d7, prepared, not executed). Driver and per-year statuses:
`logs/massive_sweep/` (uncommitted scratch). Also landed 2026-11-10/11: migrations 586, 587, 588; the reader, vendor and
kind maps; reference_raw loaded (332,294 Massive rows, 1,529 IBKR ISIN answers, 1,519 OpenFIGI);
identity map applied (4,555 security identifiers, 1,515 spans, 1,395 instruments mapped, the rest on a
gap list); 501 massive_reference split rows applied (GSAT retired, SNX spin-off excluded), daily rule d2-v6;
design section 8b (Massive primary over the whole archive span in two policy stages). Next gate: the
section 8a load checks, then step 7 stage 1 per `docs/operations/massive-step7-runbook.md` (16 to 22 h,
Alpaca nightly stopped for the window), both on the lead's call.

The IBKR fetcher timer was disabled 2026-11-10; glossary entries landed.

**Owner rulings in force (2026-11-10):** Massive is used regardless - no admit/refuse verdict;
the pilot became the design's section 8a LOAD CHECKS (a name outside a check keeps its
incumbent; systemic failure stops the switch). Massive is the YARDSTICK: disagreements are
prima facie incumbent defects, but an incumbent-defect call needs a third witness (pre-2016
IBKR is the independent arm; Alpaca post-2016 is the same Polygon feed, non-independent).
Survivorship is measured and disclosed, never a gate. Pre-2016 5m: Massive primary, NO IBKR
fallback. Mapping option A: files are the as-served record, raw is a retractable mapped
projection (the law 528 amendment rides the admission ruling). Step 7: canonical's derived rows
drop and ALL timeframes rebuild from raw in one pass (post-2016 must reproduce byte-exact, plus
the 2016 seam witness and the NVDA 2024 rescale canary). IBKR 5m raw is KEPT (lead ruling 2026-11-12: the only
independent witness to Massive, near-zero cost; the fetch lane and ask-ledger machinery are what get deleted; revisit after step 7 and the 592 adjudications, export-first if ever). Stop polishing IBKR/Alpaca-era data. No corpus compute until the data gate passes
(the 584 pin now waits on admission execution, not IBKR coverage).

**Earlier rulings still in force:** E15-E18 evidence rules; E21 + the section 11 amendment
drafted 2026-11-09, awaiting owner adoption (interim rule holds; gates the discovery sweep, not
admission); extended hours raw only; blind model proposer allowed; no versioned table names.

**Running now (leave them):** the IBKR fetcher timer is DISABLED (2026-11-10; todo 607's watcher is parked as expected-superseded); the
nightly timers (Alpaca 04:40Z, derivation 05:20/05:45Z, audit 06:00Z). No fleet agents in
flight; the lead (indicagent-d8) dispatches as needed with verify-every-landing.

**Done this stretch (2026-11-09/10, one line each):** 186-31 CONVERGED (5 review rounds; suite
8,153). 592 complete then parked (10 named cases fixed and junction-verified; sweep: 1,389
breaks classified, 134 fixed, rulings issued; follow-ups parked pending Massive as witness -
GSAT/NEXN/OKE D7 red rows are KNOWN-ACCEPTED). 587 closed (clean D7). 603 register + migration
584 (`external` composition code). 602 doc-number guard, closed. 601 classification (306
columns, all proposer-swept). 606 filed. 595 closed (no same-tape witness; keep the 2.5 floor).
574 Tradier removal and 510 backup deletion DONE 2026-11-12 (migration 589, code at tag archive/tradier-2026-11). Massive acquisition: purchase,
both keys regenerated, downloader built and fixed (07c70a806, 15719adb0), full archive verified,
serves captured, references captured, design refined.

**Todo triage 2026-11-12 (lead):** pending 105 -> 86. Closed as superseded by Massive: 453, 505, 521, 534, 537, 581, 585, 519, 607. Deferred behind step 7 (gate: step 7 proves the rebuild, then todo 600's deletion-list review): 433, 497, 525, 527, 535, 557, 565, 566, 567, 596. P0 is now only 584, 588, 600. Unblocked now: 608, 592, 595 (the split and wick sweeps with Massive as witness).

**Universe (lead 2026-11-12):** the archive holds 30,000+ tickers against 1,529 on IBKR; todo 609 builds the stage 2 point-in-time liquidity-rule universe (survivorship-free, 1d for all, 5m for the top tier) after step 7 and the 8a checks. It is the biggest lever on breadth after the data gate.

**In flight at the 2026-11-12 handoff (lead):** the 8a load-check runner is on origin branch `worktree-agent-a982cb955333e9a38` (stage A to C at 9153cf54a, a45bf01b0, f338f2817; rounds at b8e7c94fd and 0b11b4128: owned-row sanity, volume step rule, day-file 1d verdict arm, close-convention table, residual concentration, unresolved bucket for 2003-2007, flagged register, IBKR coverage; round 4 in progress 2026-11-12: era stop only on the unexplained 'other' class, not last_print/convention classes, with a dominant-exchange explanation). Results so far: record sanity, session, volume bands ok; 2014-2026 ok on both timeframes; 2003-2007 1d close convention unresolved (third witness needed); residual stops 2007-2013 were an artifact of stopping on total rather than 'other' residual. Not yet independently reviewed, not on main; the worker's final report and full-archive rerun may not have completed. Resume: re-run `ops_massive_load_checks` from that branch, read `logs/massive_load_checks/summary.json`, get an independent Opus review, land it, then step 7 (todo 610 is reversed: 1d stays the served day file; the 2003 to 2007 close convention is an open witness question). Worktree branch `worktree-agent-ab7c70218b95aaf58` is also pushed (older, unmerged).

**Next, in order:**
1. Execute the rest of the design's step sequence on the lead's call (section 8: the 8a load checks,
   policy, one-pass rebuild with the seam witness and canary; migration, code, reference load, split
   reconciliation and all per-year raw loads are done).
2. On the day: stop the IBKR fetcher timer; the deletion list lands AFTER the rebuild proves
   itself (Opus-reviewed, IBKR 5m reversible-first).
3. After loads: rerun `ops_split_calendar_audit --sweep` with Massive as witness (592 parked
   cases + the 393 Yahoo holes + OKE/NEXN/INSM/TMUS adjudications).
4. Then the pre-rerun window (todos 551/552/558/516) and the corpus rerun per
   `docs/operations/corpus-rerun-runbook.md` (the G6 hole-density named decision is recorded
   there).
5. Owner's other item: E21 adoption (one word; unblocks the discovery lane's real-data sweep).
6. Dated: 2026-12-01 IBKR gateway lapse decision (544;
   resolves to lapse unless a retained role is measured).

**If /tmp was wiped (reboot):** nothing load-bearing lives in /tmp now (all lanes landed); the
worktree list is `git worktree list`, prune clears stale entries.

**Working rules learned 2026-11-04..07 (binding):** a worker editing anything a timer or service
runs (providers, the nightly, bar_derivation, D7, the fetcher, any shared writer, the dashboard)
works in its own detached worktree off origin/main, never in the shared checkout; nothing
unpushed stays on the shared main; every landing gets an independent review before it counts
(self-review missed real defects every time); measure a defect class and its base rate before
naming a rule; judge tests by the summary line or exit code, never a tail; after a dashboard
package change, `npm ci` in the shared checkout before restarting the service.

## Earlier positions (condensed 2026-11-09)

The 2026-11-01 and 2026-11-04 position write-ups are superseded by the handoff above; the full text is in git at 7d2fcb405 (`git show 7d2fcb405:.planning/STATE.md`). What still holds from them:

- The operative plan is `docs/plans/2026-11-03-path-to-first-counted-test.md`. Todo 584 (corpus rerun fix manifest) has landed every code item; its pin waits on the data gate (186-32), which waits on the data being complete (IBKR 534 or Massive 600).
- Todo 587 (380 unadjusted splits over 268 names): the safe set landed (migration 567, audit tool, D7 `split_continuity`); the atomic landing waits at tag `wip/587-atomic` and closes on a full nightly D7.
- One-name tables landed: `feature_vectors` (migration 570), `feature_ic_scores` (575), the v1 in-place writers deleted (576), 13 retired columns dropped (577). The 186-26 rows were discarded (migration 569).
- Owner decisions still open are listed under "Decisions waiting on the owner" below (todo 566 policy classes, the clean-data lift for price-derived 1d families, the 27 compute_eligible_1d=false names, the entity classes, the 185-49 reversal for the 587 rescale).

## Starting a new session

Read in order: this file -> `.planning/todos/PRIORITIES.md` (584 first) -> `ROADMAP.md` -> the
unified design (sections 2, 16 and the one for your work). Message the lead (ListAgents) before
starting a lane. Work in a detached worktree off origin/main when the shared checkout is dirty;
never two backfills at once; kill by PID only; never edit a module a live fingerprinted run
imports.

## Decisions waiting on the owner

- RESET DONE 2026-10-30 (migration 544): the research ledger is empty (54 `research_run` and 22 `research_run_series`
  rows deleted, backup in `data/backups/reset-2026-10-30/`; real-data result files moved to `files/` there; panel
  snapshot caches deleted). Not reset, owner call with the data lane: the concept layer (306 `active` concept
  statuses and 590 `concept_evaluation` rows from the old feature corpus; `feature_factory` reads the statuses, so
  reset approved by the owner 2026-10-30 to run after the 186-26 rebuild, through `ConceptRegistryService`: todo 571), and the frozen sections of
  `docs/research/construction-verdict-ledger.md` (todo 568). `.planning/gate_look_log.jsonl` stays: it records looks
  at the forward span, and deleting rows does not un-see data.  the research-lane items below): no hypothesis tests on real data until
  the data and features are clean and complete; earlier family results (family 2's run of 2026-10-29,
  family 1) were made on incomplete data and an unsettled universe and are not evidence; start the testing
  program from scratch later. Statistics infrastructure (E17 daily statistic, StepM attestation) stays,
  since it is certified on synthetic data. Restart conditions: (1) 186-26 complete on all timeframes,
  including the 229 D7-hold names and the 16 recent listings, with todo 564's kernel batch (hma_slope_z,
  dead columns, calendar start 2000, config field rename, delete list for the NULL-volume code) applied
  once before the intraday stage; (2) phase 191 plans 22 and 23 and the 71 held-name 1d gaps (todo 566);
  (3) a fixed, written universe; (4) the vintage question: whether a fresh vintage starts so earlier looks
  do not count against the new StepM universe (owner call, E18).

- Research lane (2026-10-30): the E17 daily statistic landed (`d2f3ff0b1`, flat-top kernel plus influence
  series; todo 547) and cut the daily battery from 40+ size failures to 3 marginal ones (gaussian
  `reversal_5_skip1` 71 of 1,000 against 67; the two momentum members in s1_hostile, S1 drift). Decide: certify
  the reversal members and book now and hold the rest, or hold the family until S1's drift is decided. The
  StepM attestation is complete (Step B v2 passed), so `select_books.py` is unblocked. Todo 562 (multi-family
  power plant) also waits on the owner.

- Research lane: (1) approve the E17 amendment for todo 547 (a horizon-tied lag, L + c (h - 1) for
  daily targets with h > 5, c = 3 to certify); (2) decide the multi-family power plant (todo 562)
  before the `generated_family` grammar; (3) enable the research-ledger render timer (`sudo systemctl
  enable --now indicagent-research-ledger-render.timer`) once local main is reconciled, or let the
  job commit from a scratch worktree off origin/main and push that one file; (4) todo 561: after the
  3,000-simulation diagnostic, a new pre-registered step B or a written call on the `s1_hostile` cell.

- Plan 20: confirm the Tradier deletion once the residue report exists (it also settles the todo
  537 item 2 basis restore). This is the only open owner call (the research restart was decided 2026-10-27; for E17 v2 the owner chose on 2026-10-28 to rerun step A cluster-robust before building fixed-b). The tooling is
  built ahead of the approval and reviewed twice (Task 2: `scripts/ops/bars/ops_tradier_delete.py`,
  migration 524, scratch-schema integration test; record `191-20-TASK2-BUILD.md`); nothing has
  run live. D-191-Q (owner 2026-10-27, todo 545): canonical 1d becomes Alpaca
  SIP primary from 2016 with IBKR fallback, IBKR before; the Alpaca 1d backfill, a full Alpaca vs
  Tradier comparison, daily rule d2-v4 and the policy rows land before Task 3's re-derive.
  Simplify pass 2026-10-27: every ohlcv_load row stays (lineage,
  like ohlcv_request), so only value rows go and the IBKR revision rows under Tradier loads stay
  by construction; the design doc carries the amendment. Task 3 must stop every
  1d consumer, not only the fetcher and bar_derivation, from the first batch to the 1d re-derive.

D-191-P done 2026-10-27 (migration 520 retirement, ba03e9ff7; plan file
`data/policy_plans/2026-10-26-d191p-5m-alpaca-primary.json`): live 5m policy is two defaults, IBKR
before 2016-01-04 and Alpaca then IBKR from it; 1,641 symbol rows retired. 267 names reselected
(44.5M bars changed) and their grid re-derived in full; the other 1,261 names had their stale
session-choice records rewritten by record-only shards (0 bar changes). Every name's 15m/1h grid
is current through 2026-10-26 (`indicagent-bar-derivation-grid`, 05:45 UTC, --changed-only, now
follows the Alpaca nightly; writing derivation runs serialize on a stage lock, e48ddbfb6). Final
5m selection gate exit 0: 1,529/1,529 series clean, n_canonical == n_selected == 311,503,335,
session_choices_unrecorded 0 (`logs/selection_gate_20261027T072705Z.json`). The research lane
(5b) was told 2026-10-27 about 08:28Z; the 5m snapshot and 186-26 are no longer held on D-191-P. 5b fires the family 2 run on a one-line notice from the data lane when plan 20's 1d re-derive lands; the notice lists, among family 2's 187-name US-session universe, every name with a pending span, a frozen hold or a D-191-Q arbitration hold.

Decided 2026-10-26 and queued for the data lane: D-191-A..L acknowledged (A: refuse a non-split
Alpaca raw write; L: count never-selected-kind slots apart from policy gaps); D-191-P canonical 5m
is Alpaca SIP primary from 2016-01-04, IBKR fallback, IBKR alone before (policy rows plus a
reselect after the Alpaca catch-up, before 186-26); todo 519 listing_end table and PSKY to SKYD;
family 2 gets one evidence run after 191-25 (moved to plan 20's re-derive 2026-10-27); todo 509 deletes the v2.x dashboard signal surface and
the ML batch chain (nothing worth keeping; regime HMM kernel stays). Migrations: this lane takes
518 and up (515-517 reserved by the research lane).

## Open items that are not verdicts

- Dashboard v3.5 cockpit closed 2026-10-27 (owner: a dashboard does not find edge). Six pages
  are served on :3000; Books stays an empty state until phase 188. Unscheduled refinements were
  listed in the closed cockpit design, deleted 2026-10-31 with no stub (git history:
  docs/plans/2026-10-26-dashboard-v35-cockpit-design.md as of 708f3fe09).

- The midterm spec was committed 2026-10-01, before the 2026-11-03 election: its forward window
  (to 2027-05-03) is recorded in `docs/ideas/signal-political-policy-regime.md`; todo 483 records
  its result after 2027-05-03.

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

## Delete-after list (disk housekeeping)

Disk is not tight (28% used, 2026-10-29), so none of this is urgent; it is here so safety copies
are removed on schedule and nothing protected is removed by accident. Everything under `data/` and
`logs/` is git-ignored.

| Path | Size | Delete when | Why it is kept until then |
|---|---|---|---|
| `data/backups/191` | 3.2 GB | when the owner closes the Tradier work (plan 191-20 done 2026-10-29; D7 holds, todo 545, still open) | backup taken before the irreversible Tradier bar delete |
| `data/backups/185-38` | 142 MB | unknown: find its phase's retention rule first | an earlier phase's drop backup |
| `data/backups/worktree-salvage-20261029` | 1 MB | about 2026-11-12 | patches and a bundle from the removed 5b-t3, prev3 and shared-checkout work; the shared checkout was stale, its commits are on origin under other hashes |

Never delete: `logs/phase181` and `logs/phase179` (`repro_frozen` replays the frozen verdicts from
them), `logs/research/snapshots` and the step A and B evidence under `logs/research/` (`compare-all`
and the E17 records), `.venv`. Worktrees (`git worktree list`) are extra working folders of this one
repository: sessions create a detached one off `origin/main` to commit without touching other
sessions' uncommitted files, then remove it; `git worktree prune` clears entries whose folder is gone.

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

- Phase 190 added: Provider history plane unification: one multi-provider fetcher, N leaves, two-tier ledger (design: docs/plans/archive/2026-10-09-provider-history-plane-unification-design.md; rides with todo 526)
- Phase 189 edited: edited fields: depends_on
- Phase 189 added: IBKR history fetch consolidation: single fetcher, coverage ledger, priority queue replacing the nightly/bulk lease and lane scripts

- Research lane (2026-10-31): the systemd battery units (`e17-battery-daily-flat`, `e17-battery-daily-residual-4736`,
  `e17-battery-daily-residual`, `e17-battery-daily-v2`) show `failed` because the drivers exit non-zero on a
  pre-registered verdict fail; the runs completed and their verdicts are the record. Canonical: `e17-battery-daily-v2`
  (todo 547's pre-registered run; only `daily_s1_hostile/residual_momentum_12_1_z` exceeds, the cause-3 S1-drift
  pattern, owner decision A/B). The other three are superseded iterations. Do not rerun: pre-registration forbids
  rerunning seeds for a pass. Todo 549 closed 2026-10-29 (E17 v1 stands, no fixed-b); the 4,000-session StepM
  attestation is Step B v2 (todo 561), passed, `select_books.py` accepts it.
