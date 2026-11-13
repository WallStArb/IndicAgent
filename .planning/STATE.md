---
gsd_state_version: 1.0
milestone: v3.5
milestone_name: Unified Research Pipeline
status: in_progress
last_updated: "2026-11-13T21:10:00.000Z"
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

## Session handoff (standing; lead indicagent-2c; read this first)

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

**Earlier rulings still in force:** E15-E18 evidence rules; E21 ADOPTED 2026-11-13 (8fc33b744), the
section 11 amendment stays drafted; extended hours raw only; blind model proposer allowed; no
versioned table names.

**Running now (leave them):** the IBKR fetcher timer is DISABLED (2026-11-10; todo 607's watcher is parked as expected-superseded); the
nightly timers (Alpaca 04:40Z, derivation 05:20/05:45Z, audit 06:00Z). No fleet agents in
flight; the lead dispatches workers as needed with verify-every-landing.

**Todo triage 2026-11-12 (lead):** pending 105 -> 86. Closed as superseded by Massive: 453, 505, 521, 534, 537, 581, 585, 519, 607. Deferred behind step 7 (gate: step 7 proves the rebuild, then todo 600's deletion-list review): 433, 497, 525, 527, 535, 557, 565, 566, 567, 596. P0 is now only 584, 588, 600. Unblocked now: 608. 592 and 595 closed 2026-11-13 as superseded by the IBKR removal; the split sweep lives on as step 7 precondition A3.

**Universe (lead 2026-11-12):** the archive holds 30,000+ tickers against 1,529 on IBKR; todo 609 builds the stage 2 point-in-time liquidity-rule universe (survivorship-free, 1d for all, 5m for the top tier) after step 7 and the 8a checks. It is the biggest lever on breadth after the data gate.

**Owner ruling 2026-11-13 (then-lead indicagent-d0):** IBKR is removed entirely (todo 600, b1dc82321). Canonical becomes Massive [1990-01-01, 2026-11-10 archive end; Massive holds nothing before 2003-09-10, so earlier slots leave) then Alpaca, no fallback, no IBKR anywhere; 1m and 4h leave canonical; gap-list spans after 2016 keep Alpaca symbol rows; IBKR raw is exported, restore-verified, then deleted only after step 7 proves itself (runbook Part F). Branch `step7-no-ibkr` holds the plan, `ops_massive_switch_delta` (expected delta, lost-slot classifier, `--verify` for D1) and the one-stage runbook. Losses are classified: predecessor_history (SPAC shells, merged-away predecessors under today's ticker) and vendor_has_no_bar accepted and listed; the identity witness (design 8c, rule 8d10bd030; the stopping-rule override is recorded there) placed 183 gap spans, applied to the map 2026-11-13 (`--amend`, code bbe134dd6; map dir data/ticker_entity_map/20261113_595bb68f6772; ticker_event_current 1,698). In flight: the Massive raw load for the placed spans (raw only, bracketed by an all-time `ops_selection_gate --compare`, about 10 h from 15:14 UTC), then the 1d and 5m delta rerun, then step 7. The 8a runner and the per-era plan builder are NOT landed (tags archive/massive-8a-load-checks, archive/step7-plan-8a-input); their r5j/r5k outputs are the admission record. E21 ADOPTED (8fc33b744). Pre-registered gate constants are exempt from APR (1c0c66889). ubuntu2 is the streaming standby and backup.

**Update 2026-11-13 evening (lead indicagent-2c, owner mandate; worker indicagent-6e):** the 15:14Z placed-span chain was killed with its session 1h45m in, still inside the read-only compare_pre (950/1551 instruments, real=0 throughout; the driver had no setsid, so background tasks die with the session). Nothing was written: loads are strictly sequential behind the compare, and the 1d 2010 dry run was `apply: false` (scratch dir kept as the record). The map amendment DID land (183 ticker_event rows, map dir data/ticker_entity_map/20261113_595bb68f6772). Now: the identical chain relaunched detached (setsid, on-disk status, evidence mirrored to logs/massive_step7_placed_load/), then the A11 close-out witness re-run on the new gap list (gate: zero placed spans left). In parallel 6e builds A8's d2-v6 switch-plan unit test (the runbook's named hard blocker); a d2-v6 defect stops for the lead's ruling. Then the 1d/5m delta rerun (B4, read-only, after the nightlies), then step 7 on the runbook's gates.

**Next, in order:**
1. Tonight 2026-11-13: the placed-span load chain detached + A11 witness re-run; A8's test lands for review. Tomorrow: the 1d and 5m delta rerun (B4) after the nightlies. Then step 7 per the one-stage runbook on `step7-no-ibkr` (land the branch first; run after a nightly; D1 = `ops_massive_switch_delta --verify`), then Part F (IBKR export, restore check, delete, code and gateway retirement), then todo 609 (point-in-time universe from Massive's securities).
2. On the day: the quiet list stops per runbook A10; the IBKR deletion (Part F: export,
   restore-verify, then delete, code and gateway retirement) lands only after the rebuild proves itself.
3. After loads: run step 7 precondition A3, `ops_split_calendar_audit --sweep` with Massive as
   witness (the parked split classes, the 393 Yahoo holes, OKE/NEXN/INSM/TMUS).
4. Then the pre-rerun window (todos 551/552/558/516) and the corpus rerun per
   `docs/operations/corpus-rerun-runbook.md` (the G6 hole-density named decision is recorded
   there).
5. E21 ADOPTED 2026-11-13. The discovery sweep waits on the data gate (186-32) and the E21 volume pilot.

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

- The operative plan is `docs/plans/2026-11-03-path-to-first-counted-test.md`. Todo 584 (corpus rerun fix manifest) has landed every code item; its pin waits on the data gate (186-32), which waits on Massive admission (todo 600).
- Owner decisions still open are listed under "Decisions waiting on the owner" below (the clean-data lift for price-derived 1d families, the 27 compute_eligible_1d=false names, the entity classes, the 185-49 reversal for the 587 rescale).

## Starting a new session

Read in order: this file -> `.planning/todos/PRIORITIES.md` (584 first) -> `ROADMAP.md` -> the
unified design (sections 2, 16 and the one for your work). Message the lead (ListAgents) before
starting a lane. Work in a detached worktree off origin/main when the shared checkout is dirty;
never two backfills at once; kill by PID only; never edit a module a live fingerprinted run
imports.

## Decisions waiting on the owner

- Todo 547: certify the reversal members and book now, hold `reversal_5_skip1` and the two momentum members (S1 drift), or hold the family. E17 landed (`d2f3ff0b1`, flat-top kernel plus influence series); the daily battery went from 40+ size failures to 3 marginal ones; the StepM attestation passed and `select_books.py` is unblocked; B3 power still open.
- Todo 558: the pre-rebuild feature-additions pass; the lane owners' candidate list is the owner's to change.
- Todo 558: the pre-rebuild feature-additions pass; the lane owners' candidate list is the owner's to change.
- Still open owner calls: the clean-data lift for price-derived 1d families, the 27 compute_eligible_1d=false names, the entity classes, the 185-49 reversal for the 587 rescale.
- Concept-layer reset (todo 571, owner-approved) runs after the 186-26 rebuild and 564's batch. The 2026-10-30 research reset is done (migration 544; `.planning/gate_look_log.jsonl` kept: deleting rows does not un-see looks at the forward span); its restart conditions are superseded by the Massive admission path. Statistics infrastructure (E17, StepM) stays, certified on synthetic data.

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
| `data/backups/191` | 3.2 GB | now (Tradier work closed 2026-11-12, todo 574); delete on the next housekeeping pass | backup taken before the irreversible Tradier bar delete |
| `data/backups/185-38` | 142 MB | unknown: find its phase's retention rule first | an earlier phase's drop backup |
| `data/backups/worktree-salvage-20261029` | 1 MB | past due (2026-11-12); delete on the next housekeeping pass | patches and a bundle from the removed 5b-t3, prev3 and shared-checkout work; the commits are on origin under other hashes |

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

- Phase 190 provider planes (190-01..06): the `HistoryProvider` protocol and HistoryRequest /
  FetchBudget / NoDataVerdict / HistoryPage live in `src/providers/base.py`; the fetcher is
  `ohlcv_history_fetcher` / `OHLCVHistoryFetcher` with a `_PROVIDER_REGISTRY` (provider name ->
  leaf factory + item-fetch hook; adding a vendor is one registry entry plus a leaf module);
  two-tier coverage ledger (`ohlcv_coverage.provider`, `ohlcv_provider_head`, migrations 464
  and 465 applied); per-provider ProviderPlan budgets from `infra.<provider>.*`; scripts, src
  and services cannot import a concrete provider leaf outside `src/providers/`
  (test_provider_leaf_boundary). The IBKR registry entry and fetch lane go in the step 7 Part F
  deletion list.

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
