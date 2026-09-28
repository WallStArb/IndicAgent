---
gsd_state_version: 1.0
milestone: v3.5
milestone_name: Unified Research Pipeline
status: in_progress
last_updated: "2026-09-28T01:05:57.902Z"
progress:
  total_phases: 6
  completed_phases: 1
  total_plans: 63
  completed_plans: 15
  percent: 17
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
  from UCR. Check it before recommending a candidate.

## Current position (2026-09-27)

- **Phase 183** (other session): all 11 plans done (plan 10 on 2026-09-26), phase verification
  pending. Family 1 evidence done (HAC t 13-19 gross, biased toward zero under E16; about 26x
  turnover per session, untradeable net at 1 bp); book_v1 refused (E16 bias, uncharged); E17
  built and its gating decided (option C); its per-family static-size guard is in the runner
  (todo 447, 2026-09-27) and families 1 and 2 pass it. Family 2's evidence run is unblocked.

- **Phase 185:** planned 2026-09-27: 24 plans in 10 waves, aligned the same day with todo
  449's single-stream finding (`d2c02b387`: one IBKR history-stream lease, CONTEXT D-29 to D-31).
  Plan-checker pass passed 2026-09-27 after one revision (`959ec85ea`: plan 13 rebased to wave 3,
  running concurrent with the campaigns under the priority lease). Grok 4.7 external review folded
  2026-09-27 (`c2cc7c811`, `185-REVIEW-GROK.md`: 185-12 cut-over discipline, 185-16 D-04 hand-off
  scope, 185-10 scrub-input reader fence). Executing since 2026-09-27: plans 185-01 (measurements `757e4f04b`) and 185-02 (D1 store,
  migration 380, COPY writers `f3d584789`/`1e3477de6`) complete; the tests/integration/ rebuild
  was repaired along the way (`c19bcb545`, baseline bump 2026-09-27; it had been broken since
  migration 322). Wave 1 executed inline in the orchestrator session (owner-directed
  2026-09-27; hardening `5a576dc0a` on top of 02: sinks refuse naive bar timestamps):
  185-03 (RequestRecord + callbacks `05516a18c`/`567badfad`) and 185-04 (migration 381
  applied live, quarantine anti-join, bar_derivation_batch helper `52a697f73`..`fab80260c`)
  complete; wave gate pending.
  Plan 09 builds the lease and cuts the running todo 449 chain over to it, so the chain yields to
  the nightly and to 185's fetch campaigns (clients 47-49) at every (symbol, tf) unit. Plans 10,
  14, 15 and 16 clear the minimum data bar for daily attempts 3, 3b and 4 by wave 5; D2b (plans
  11-12) is in place by wave 4 for 186. Price-integrity layer (D2a scrubbing, flag never delete;
  D7 reconciliation). Owns todo 433 (P0).

- **Phase 186:** planned 2026-09-27: all 29 plans written (`09776c12c`); the 185↔186
  cross-review (`c35fa9dd3`) amended 186-14/25/27 and 186-CONTEXT (digest composition from
  185-11, 185-20's unlock keys, the fetch-stage allow-list, the D-19 disambiguation), so the
  plan-checker pass validates the amended set. The six-reviewer cross-AI review (R1-R6 plus the
  owner-run Grok council) closed 2026-09-27 with all HIGHs integrated (`186-REVIEWS.md`,
  through `91a6cf7c4`). Executing since 2026-09-27 (`/gsd-execute-phase 186`, waves 1-10
  sequential): 186-01 and 186-03 done (2/29; 186-03's determinism tool merged `c3ce3a9d7`,
bit-identical on the frozen phase 179/181 books with the shim module blocked); the
`feature_vectors` rebuild needs the 5m
  timeframe decision first (todo 445, design section 14.2) and 185's derived grid (todo 446).
  The fresh ic_engine computes targets with `panel.forward_returns`; the `forward_returns`
  table is dropped after parity (UD-25, design 14.7). Phases 187-188: not planned; 187 waits
  on family 2's evidence run and the research lane's release.

- **Quick, independent todos:** 443 (exporter scrape cost, idle-in-transaction timeout), 439
  (write-once `oos_start`), 438 (daily borrow snapshots; standalone again since D8 was descoped).

- **Intraday backfill (todo 449, running since 2026-09-27):** one IBKR stream via
  `logs/backfill_ops/intraday_chain.sh`: 15m+1h for the 698 names first (client 46), then 5m
  (client 40, about two weeks). Parallel lanes do not add throughput. The nightly 1d backfill
  skips while it runs. Phase 186's rebuild gates on the 5m part.
  Until plan 185-09 lands, the nightly skips every night the chain runs (1d bars go stale);
  185-09's lease replaces that skip and restarts the chain's pipeline process onto it.

- **Alarm fatigue:** `regime_coverage_auditor` fails every night on 5 known symbols (todo 341).
- **Universe:** 932 active; 931 `compute_eligible_1d`; 233 carry the intraday stack and
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
| Research (phase 183) | Phase 183 verification; attempts (todo 442) paused until 185 and 186 land (owner, 2026-09-27) | The phase 183 session owns `src/intelligence/research/` until plan 10 and family 2 finish; nobody else edits it |
| Alpha, no dependencies | Paused until 185 and 186 land (owner, 2026-09-27): todos 437 (cost model), 441 and 423 (price-only daily families), 440 (`generated_family`) | Specs and new modules only; runs go through the phase 183 runner |
| Quick data and infra | Todos 443, 439, 438 (borrow snapshots; loses a day every day it waits) | Independent; 439's IC purge lands with phase 186's fresh ic_engine |
| Phase 186 | `/gsd-execute-phase 186` running (coordinator indicagent-f3 since 2026-09-28, relayed from e7): 186-01 and 186-03 done (2/29); 186-04 executing (worktree `/home/bg/dev/indicagent-186-04`, branch `phase186-04-helper-promotion`); then 05-10 and waves 2-10, one executor at a time | No edits to modules ic_engine imports while a corpus run is live or resumable; commit only 186's own files (185 executes concurrently in this tree); designed gate stops (186-14 waits on 185-11, 186-23 on 185 D-14, 186-26 on todo 449 coverage) are reported, never forced |
| Phase 185 | `/gsd-execute-phase 185` (24 plans checker-passed 2026-09-27) | Owns `src/providers/ibkr.py` changes and todo 433 |

Phases 184 and 187-188 have no directory yet; `gsd-sdk query phase.add` numbers from
`.planning/phases/`, so add or plan them by number, never through `phase.add` (CLAUDE.md).

## Decisions waiting on the owner

- None open. E17's gating criterion was decided 2026-09-26 (option C: measured-size gate plus a
  per-family static-size guard, built under todo 447; methodology-change-ledger E17).

## Open items that are not verdicts

- Todo 248 (HMM per-symbol lookahead): walk-forward fix built, not deployed; deploy with the
  phase 186 rebuild. HMM columns stay out of every family until then.

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

- Corpus pipeline: `--compute-only` silently skips every symbol if `backfill_status` is empty;
  seed it first (query in `.planning/milestones/v3.4-STATE.md`, "Corpus Pipeline Gotcha").
