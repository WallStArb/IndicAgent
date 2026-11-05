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

## Current position (2026-11-04, paused by the owner)

Operative plan: `docs/plans/2026-11-03-path-to-first-counted-test.md` (lead: indicagent-16).
All work is paused; nothing is in flight except the IBKR history fetcher timer.

- Todo 584: every code item has landed (1-12, 6a-6d, 8b, 3 at K=3 uniform with ledger E20, G4-a
  exact window sums). The pin waits on todo 587 and the owner's data rulings.
- Todo 587 (P0): 380 confirmed unadjusted splits over 268 names in canonical 1d. The safe set has
  landed (migration 567, audit tool, CSV, D7 `split_continuity`). The atomic landing (d2-v5
  rescale + migration 568 lineage view) is unpushed at tag `wip/587-atomic` (5e3845df2) and waits
  for the lead's go after the owner's 185-49 ruling.
- Phase 184: plans 05-10 landed; a feature member runs S0 -> S8 on a synthetic panel. Todo 588
  closed the admission holes (parts A and B): admitted are feature 1h->1d, feature 15m->1d,
  rk_high_dist 126 and the 1h+15m book. Part C is 184-12's real-data dry build after 186-27.
  compare-all was vacuous (empty `research_run`).
- Next, in order: the owner's decisions below -> 587 atomic landing -> official pilot G1-G5 on a
  fresh executor -> pin -> 1d rerun -> 186-27 -> 184-12.

Owner decisions added 2026-11-04 (lead recommendation in each source): todo 566 policy classes
(3a keep and excuse, 3b close 7 rows, 3d keep, 3e keep refused); the clean-data lift for
price-derived 1d families; admitting the 27 compute_eligible_1d=false names; the entity classes
(63 early starts plus MTCH, RCAT, GEN); the 185-49 reversal for todo 587's rescale.

## Previous position (2026-11-01 23:20Z)

Owner sequence (2026-11-01): (1) data squared away, (2) every fix that changes a stored value
landed, then one full feature recompute of the corpus, (3) ensemble research on the result. Lead
orchestrator: indicagent-4f; devs indicagent-82 and indicagent-dc (93 and b0 are out until
2026-11-05 23:16Z).

- **Critical path: todo 584 (corpus rerun fix manifest).** Decision 2026-11-04 (owner): no
  corpus compute until the data is complete (the 5m coverage target, todo 534; definition in the
  584 decision). The 186-26 rows on pin `92e588385` were discarded (migration 569, 298 GB freed;
  provenance `superseded`), so nothing resumes. The swap landed 2026-11-04 (migration 570): one
  table name, `feature_vectors` (empty, kernel schema; the 89 GB v1 table dropped), the rebuild
  compresses at every full-universe stage end, the streaming feature writer unit is disabled. Migration 575
  (2026-11-04) did the same for IC: one table, `feature_ic_scores` (413 schema, empty until
  186-28's fresh run); the ic_engine-era table and its two views are dropped. Todo 590 (migration 576) deleted the v1 in-place
  writers: the rebuild is the only writer of `feature_vectors` (CI test plus a `BulkLoadSpec`
  sole-writer check). Migration 577 dropped the 13 retired columns from the
  empty table (311 columns, equal to the registry); the integration baseline is 2026-11-05
  (todo 591). The rerun runner is planned (todo 593: 186-30 run identity,
  186-31 span-major step runner, plan check round 4 pending); it executes only after the 584 data
  gate. Todo 587 landed 2026-11-05 (f5ebae068): 378 calendar_audit split rows on 266
  names, rule d2-v5 rescales them, 13 bars quarantined (7 unconfirmed_split, 6 operator_bad_bar),
  233,512 1d bars re-derived, all digests rewritten; the D7 after-count is being read against the
  2026-11-05 01:13 baseline. The rerun is planned as 186-30 (run identity) and 186-31 (span-major
  step runner, todo 593); a fourth plan check is running, with the lead's disk rule (peak at or
  below 70% of free disk, span count derived, APR headroom guard). Next: the fix
  batch keeps landing on main; when 534 meets the target, the pin moves once, the pilot passes G1-G5, then the rerun, 186-28, 184. Owner 2026-11-04: IBKR only for pre-2016 5m (no vendor purchase); pre-2016 results carry a survivorship caveat (todo 534).

- **Data (step 1):** phase 191 complete (canonical = selection over `ohlcv_raw`; the selection
  gate is the standing proof). Pre-2016 IBKR 5m backfill (owner P0, todo 534) is owned by the
  fetcher timer (never hand-launch). A run now ends on a failed history probe (`1ebcfc9e4`) or on
  no data taken in for 1800 s, status `stalled` (`857b163e0`); failure modes and procedure in
  `docs/reference/gotchas.md`. Todo 534 concurrency test concluded 2026-11-02: the owner kept
  `fetch_concurrency` 4 (about 715,000 rows/h; 3 and 4 lanes equal, 8 stalled) and stopped
  testing concurrency - numbers and failure modes in the 534 Status section. Coverage target
  and counts: memory `project_raw_coverage_target`, todo 534.

- **Landed 2026-11-02 (82):** 584 item 10 calendar start 2000 (`ff368fcd4`), item 11 proven start
  per name closing 532 (`d601a6fd5`, ledger E19; the 1d verdict audit must run once to write
  `proven_start_1d` before the rebuild reads it), item 5 macro.py half (`aee2404d9`), item 12
  (`d003eb028`). Open for the 584 implementer: the `_cache_state.py` and `feature_factory.py`/
  `schemas.py` half of 463 (references in the 82 handoff to 4f).

- **Lanes now (2026-11-02 evening):** lead = indicagent-91 (e1 ended). ea = 584 items 2, 4
  and 6: item 2 fully landed (kernel_source Panel.tf follow-up `5015cc8e2`), 4a landed, 4b/4c
  in progress. d6 = 583 deep-data K study (the `--bic` tool change sits in its working tree;
  gates before any run), then 584 item 9 G4/G5. Tracks B (584 item 8 add-list) and D (todo 522
  run implementation) briefed, not opened.

- **Todo 522:** the Monday 2026-11-02 open passed without the measured run. `run` is a stub
  (raises SystemExit at dispatch); the measured protocol must be implemented from the file
  docstring and the pre-registered instrumentation spec
  (`docs/plans/2026-11-01-own-flow-slippage-instrumentation.md`), then `check` +
  `.venv/bin/python scripts/ops/alpaca_paper_lifecycle.py run` after an open (next window
  Tuesday 2026-11-03 14:30Z). Track D when opened.

- **Research:** no real-data hypothesis tests until the restart conditions below are met. E17
  battery verdict recorded (todo 547; S1-drift A/B is the owner's); StepM unblocked (561).

- **Universe:** 1,529 active, all intraday scope; 1,502 `compute_eligible_1d`. Features and
  regimes in the canonical `feature_vectors` are stale since 2026-08-10 until 186-27.

- **Services:** Alpaca nightly timer 04:40 UTC; streaming is dormant (feed down); todo 582 must
  land before the feed returns.

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
| `data/backups/185-45` | 5.6 GB | after 2026-11-06 | dumps of the removed v2.x AI stack; `CLAUDE.md` keeps them until about that date (the git tag `archive/v2x-ai-stack-2026-10` stays) |
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
