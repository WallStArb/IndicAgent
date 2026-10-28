---
gsd_state_version: 1.0
milestone: v3.5
milestone_name: Unified Research Pipeline
status: in_progress
last_updated: "2026-10-27T12:30:00.000Z"
progress:
  total_phases: 9
  completed_phases: 2
  total_plans: 148
  completed_plans: 128
  percent: 22
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

## Current position (2026-10-26)

**Critical path (reordered 2026-10-27):** phase 191 plan 19 Task 2 -> plan 20 (owner confirms
the Tradier deletion; 1d re-derive; testing unpauses here) -> 191-21 -> 22 -> 23 (decided
2026-10-27: 23 depends on 22, whose integrity_checks changes bar_reconciliation_audit consumes;
21 and 23 are the plans that edit modules the rebuild imports) -> 186-26 feature rebuild (todo 553 spread kernels and the todo 390 illiq fix land first,
before 191-23's summary, decided 2026-10-27), with 191-24 and 25 landing alongside -> 186-27 -> 184 feature families.
Research lane in parallel: 184 planned 2026-10-27 (14 plans, 8 waves; wave 1 01-04 new files only, runs on indicagent-5b's go; wiring 06-11 after 187-08/09/10 and 187-15 Task 2, before 187-18), 187 plans 08-15.

- **Phase 191 (unified raw bar table, todo 533): 18 of 25 plans done.** Plans 01 to 18 landed and
  were reviewed (summaries and reviews in the phase dir; the swap landed 2026-10-17, the old stores
  were dropped, todo 530 closed). Canonical is `market_data_ohlcv` keyed by (vendor, kind), a pure
  function of `ohlcv_raw` plus `bar_source_policy`; the selection gate (`ops_selection_gate.py
  --compare`) is the standing proof. Raw is last-wins with a revision log (D-191-N).

- **Plan 19 (Tradier residue readiness):** Task 1 harness landed; readiness is evidence-based
  (amended 2026-10-23). 2026-10-28 01:30Z: readiness GREEN, 1,522 settled, 0 unsettled, 7 frozen
  (MOD, PSKY, CLBK, BZH by flag; CCO, QRVO, WBD by listing_end). Pass 3 (270530ec) settled 45
  names; the last 8 (EIS, H, IOT, KNSL, PNFP, REMX, RPRX, SHEN) sat outside the compute_1d scope
  every pass used and settled in pass 4 under `--dimension backfill` (de88a62f). The hourly gate
  writes `191-TRADIER-RESIDUE.md` at its next run, then plan 20 waits on the owner. The fetcher
  timer restarts. Hard-tail rule (no change to the readiness basis): a name still unsettled
  after an ask bounded at its listing goes on the `--frozen-names` hold with its residue class.
  CLBK: IBKR error 162 "No historical market data" for conId 902968711 before 2026-08-28, so its
  2,100 Tradier-only sessions 2018-04-20..2026-08-27 are residue. BZH: listing ended about
  2026-10-19 (Alpaca inactive, IBKR "No security definition"), held until its listing_end row
  lands (todo 519, with ACA and MSGS). The crontab gate `scripts/ops/bars/ops_tradier_residue_gate.sh`
  (hourly at :47, FROZEN=MOD,PSKY,CLBK,BZH) writes `191-TRADIER-RESIDUE.md` once readiness exits
  0, then stops for plan 20. completed_plans stays 120 until plan 19 closes.

- **IBKR:** the gateway was wedged 2026-10-18 23:59Z to 2026-10-26 09:00Z (2FA never approved), so
  no IBKR bars landed 2026-10-17 to 2026-10-25; the backlog is catching up. Fixed today: explicit-UTC
  request end (540), an out-of-range client id no longer restarts the gateway (542), and the
  fetcher lock survives `idle_session_timeout` (543; before it, any run over an hour lost its lock).

- **Alpaca nightly (todo 521):** `indicagent-alpaca-nightly.timer` installed 2026-10-26 (04:40
  UTC). It asks SIP with its window end held 20 minutes back (migration 513; the free plan 403s
  only a window ending within about 15 minutes of now). IEX answers are kind `iex_rth`, raw only,
  never selected. A one-time 20-day SIP catch-up is running
  (`logs/alpaca_nightly_catchup_20261026.log`) and fills canonical 5m where IBKR has no session.

- **186-26 rebuild preconditions:** the selection gate exits 0, canonical 1d is current, plans
  191-21 to 191-23 have landed (21 and 23 edit the rebuild's import closure, 23 depends on 22), and canonical 5m is caught up past the 2026-10-17..25 gap (the
  Alpaca catch-up finished, gate exits 0 on 5m). D-32 gates as in `186-26-PLAN.md`; the run tree
  `/home/bg/dev/indicagent-186-26` is kept for it (plan 186-27 removes it).

- **Research, 2026-10-27 (indicagent-5b):** 187 plans 01-07 landed; 08 Tasks 1-2 landed
  (horizon rule, book_memory, ridge and kappa battery cells, 59c6c44fb and 44409aafb), Task 3 waits
  on the 187-08 battery run. Cross-AI review of 187 (Codex and AGY, 187-REVIEWS.md): code fixes
  1e2d26419 and 7d8a14de2, amendments in plans 08-18. StepM: the 1,500-session battery failed two
  cells; at 4,000 sessions both hold; owner decision 2026-10-27: the attestation is a complete
  13-cell run at 4,000 sessions (next run). Plan 09 in-fold signs: trailing (owner 2026-10-27).
  E17 amended: L adds a daily target's reach (`timing.e17_memory`; intraday unchanged). Daily
  residual family (441 + 423) built to its battery (ee8c264df); prereg draft; h = 21 waits on
  todo 547. The 187-03 backfill (8 of 20 replays, then `--apply`) is approved (owner 2026-10-27).
  E17 v2 (owner 2026-10-27, todo 549): fixed-b critical values; the 4,000-session StepM run on v1
  is a pre-v2 baseline only.
- **Research (phase 183 done; 187 next):** todo 501 closed 2026-10-26 (317d61b69): S0 snapshots
  pin d2_rule_version, policy and verdict as-of, bar_integrity verdicts, per-symbol content
  digests and the D0 label inputs; evidence carries data_quality from the snapshot. The 501
  blocker for daily attempts 3/3b/4 is cleared; the build-first pause (owner 2026-09-27) still
  holds. Family 2's evidence run (187's gate) is approved for one run once plan 191-20's 1d re-derive lands (moved up from 191-25 by the owner 2026-10-27; the runner's import closure touches no file in plans 21-25). `build_panel` refuses any end past `alpha.validation.oos_start` (2025-12-24, write-once).

- **Frozen and ended names (todo 519):** WBD, QRVO, CCO ended (merger or buyout); PSKY trades as
  SKYD on NYSE and IBKR re-served its history on a 0.979 scale. Parked as non-critical; the
  rebuild gate already skips stale names.

- **Other phases:** 185 done (53 plans); 186 at 25/29 (17 Task 2, 26, 27, 28 left; 186-14 open);
  189 and 190 are functionally done with stale ROADMAP boxes (189-09, 189-10, 189-11 verification
  items; 190-06/07 landed per their summaries).

- **Universe:** 1,529 active, all intraday scope (owner 2026-10-09); 1,502 `compute_eligible_1d`.
  Never deactivate a name (onboarding SOP rule 6).

- **Data freshness:** features and regimes stale since 2026-08-10 until the 186-26 rebuild; check
  `max(timestamp)` before citing freshness.

## Starting a new session

Read in order: this file -> `ROADMAP.md` (active milestone table) ->
`docs/plans/2026-09-26-unified-research-to-production-design.md` (sections 2, 16 and the section
for your work) -> `.planning/todos/PRIORITIES.md`. Then pick one lane; lanes run in parallel and
coordinate through cross-session messages before touching shared files.

## Lanes (2026-10-26)

| Lane | Session | Boundary |
|---|---|---|
| Data: IBKR fetch, phase 191, Alpaca nightly | indicagent-3a | `src/providers/`, fetcher, `src/intelligence/bars/`, `services/bar_*`, phase 191 files |
| Research: phase 187 (08-15), E17 v2, family 2 run, daily residual family | indicagent-b1 (from 5b 2026-10-27) | `src/intelligence/research/`, `tests/unit/research/`, `.planning/phases/187-*`, `research/specs/` |
| Research: phase 184 | indicagent-24 | `.planning/phases/184-*`; research code on 5b's go |

Phases 184 and 188 have no directory yet; `gsd-sdk query phase.add` numbers from
`.planning/phases/`, so add or plan them by number, never through `phase.add` (CLAUDE.md).

## Decisions waiting on the owner

- Plan 20: confirm the Tradier deletion once the residue report exists (it also settles the todo
  537 item 2 basis restore). This is the only open owner call (the research restart and E17 v2 were decided 2026-10-27). The tooling is
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
  are served on :3000; Books stays an empty state until phase 188. Unscheduled refinements are
  listed in `docs/plans/2026-10-26-dashboard-v35-cockpit-design.md`.

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
