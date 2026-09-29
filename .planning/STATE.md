---
gsd_state_version: 1.0
milestone: v3.5
milestone_name: Unified Research Pipeline
status: in_progress
last_updated: "2026-09-28T11:15:14.371Z"
progress:
  total_phases: 6
  completed_phases: 1
  total_plans: 63
  completed_plans: 25
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

## Current position

- **Phase 183** (other session): all 11 plans done (plan 10 on 2026-09-26), phase verification
  pending. Family 1 evidence done (HAC t 13-19 gross, biased toward zero under E16; about 26x
  turnover per session, untradeable net at 1 bp); book_v1 refused (E16 bias, uncharged); E17
  built and its gating decided (option C); its per-family static-size guard is in the runner
  (todo 447, 2026-09-27) and families 1 and 2 pass it. Family 2's evidence run is unblocked.
  Family 1 exploration 2026-09-29 (iterations 1-4, in-sample, outside the runner): the edge sits at the
  opening and closing auction prints; no slot, keep or timing tried is net positive at measured spreads;
  next are todo 460 (auction price check, auction-to-auction hold) and todo 458 (overlay).

- **Phase 185:** 24 plans in 10 waves; 11 done (01-11), wave 2 complete with 185-09 (the
  `ibkr_history_stream` lease, D1 capture in the backfill, the nightly waiting instead of skipping).
  Next: 13 and 14 (need the gateway), then 12, then 15-24. Plans 10, 14, 15 and 16 clear the
  minimum data bar for daily attempts 3, 3b and 4 by wave 5; D2b (plans 11-12) is in place by
  wave 4 for 186. Price-integrity layer (D2a scrubbing, flag never delete; D7 reconciliation).
  Owns todo 433 (P0). Lease-free fetch callers still allow-listed: `185-daily-data-foundation/deferred-items.md`.

- **Phase 186:** 29 plans, executing since 2026-09-27 (`/gsd-execute-phase 186`, waves 1-10
  sequential, one executor at a time). 10 done (01 to 10; 02 landed in wave 2); resume with wave 2 (11, 12, 17).
  Cross-AI review closed with all HIGHs integrated (`186-REVIEWS.md`). The `feature_vectors`
  rebuild covers 15m, 1h, 1d and 5m (todo 445 decided keep_5m, 2026-09-28); the 5m name set is
  `ret_autocorr_1` and `sweep_detected` at the 233 `compute_eligible` names, and still needs
  185's derived grid (todo 446). The fresh ic_engine computes targets with `panel.forward_returns`;
  the `forward_returns` table is dropped after parity (UD-25, design 14.7). Phases 187-188: not
  planned; 187 waits on family 2's evidence run and the research lane's release.

- **Quick, independent todos:** 443 (exporter scrape cost, idle-in-transaction timeout), 439
  (write-once `oos_start`), 438 (daily borrow snapshots; standalone again since D8 was descoped).

- **Intraday backfill (todo 449, running since 2026-09-27):** one IBKR stream via
  `logs/backfill_ops/intraday_chain.sh`: 15m+1h for the 698 names first (client 46), then 5m
  (client 40, about two weeks). Parallel lanes do not add throughput. The chain yields to the
  nightly 1d backfill and to phase 185 campaigns through the `ibkr_history_stream` lease (plan
  185-09, D-29; its pipeline process has held the lease since 2026-09-28 08:10 EDT).
  Phase 186's rebuild gates on the 5m part.

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
| Phase 186 | `/gsd-execute-phase 186` (coordinator indicagent-f3): 5/29 done; next 186-07, then wave 1 continues 07-10 and waves 2-10, one executor at a time | No edits to modules ic_engine imports while a corpus run is live or resumable; commit only 186's own files (185 executes concurrently in this tree); designed gate stops (186-14 waits on 185-11, 186-23 on 185 D-14, 186-26 on todo 449 coverage) are reported, never forced |
| Phase 185 | `/gsd-execute-phase 185`: 11/24 done (01-11); next 13 and 14 (need the gateway), then 12 | Owns `src/providers/ibkr.py` changes and todo 433 |

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
