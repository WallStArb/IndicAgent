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
close (`.planning/milestones/v3.4-STATE.md`). Earlier handoff text is in git (`git log -p .planning/STATE.md`).
Replace stale bullets with current facts; no dated narrative.

## Strategic plan (read first)

- Design: `docs/plans/2026-09-26-unified-research-to-production-design.md` (ADOPTED, E18; section 16 owns the
  sequence). One pipeline from data to a frozen book; costs never enter a test statistic but promotion needs
  positive net expectation; every look is counted and selection is Romano-Wolf StepM; each book gets its own
  forward span; raw data is permanent, derived data is cache. Evidence rules E15-E18 (E21 adopted 2026-11-13).
- Milestone v3.5 Unified Research Pipeline, phases 183-188 (ROADMAP.md). Goal: test families on features,
  factors and regimes as soon as the data is complete. Order: data gate (Massive admission, step 7) -> 186
  rebuild and the 584 pin -> 184 on the rebuilt table -> 187 selection core -> feature and regime families ->
  188 on a candidate book. Operative path: `docs/plans/2026-11-03-path-to-first-counted-test.md`.
- Research record: `docs/research/construction-verdict-ledger.md`; check it before recommending a candidate.
- Owner rule (2026-10-30, 2026-11-04): no real-data hypothesis test and no corpus compute until the data gate passes.

## Handoff (standing lead; the loop is in CLAUDE.md)

Position 2026-11-14: Massive is acquired and verified (11,658 files, 2003-09-10 to 2026-11-09, 82 GB), every raw
load is done and gated (403.3M Massive rows in `ohlcv_raw`), the placed-span load and A11 witness gate are met
(zero placed spans left; map `data/ticker_entity_map/20261113_595bb68f6772`), and IBKR code, gateway, units and
83 APR keys are deleted (migrations 590-592). IBKR raw rows stay until Part F (no export, owner 2026-11-13).
The 8a load-check runner is archived (tags `archive/massive-8a-load-checks`, `archive/step7-plan-8a-input`); its
outputs are the admission record and gate nothing.

Canonical after step 7: Massive from 2003-09-10 to the archive end, then Alpaca, no fallback, no IBKR; 1m and 4h
leave canonical. Rulings in force: Massive is the yardstick (an incumbent-defect call needs a third witness);
survivorship is measured and disclosed, never a gate; pre-2016 5m has no IBKR fallback; extended hours raw only.

In flight: a worker runs step 7 Part B, read-only (A5 drift check, A6 canary tests, B1 card, B3 selection-gate
compare, B4 expected delta) with evidence under `logs/massive_step7/`. Peer sessions lead 2c and worker 6e are
out of quota; no other session is running.

Next, in order:
1. Lead rules on the B4 summary (gates in runbook B4), reviews the B5 deletion list, lands branch `step7-no-ibkr`.
2. A10 quiesce, Part C drop and one-pass rebuild after a nightly (`docs/operations/massive-step7-runbook.md`,
   14 to 20 h), D1 `ops_massive_switch_delta --verify`, D5 restart the quiet list, then Part F (IBKR raw delete).
3. Todo 609 stage 2 point-in-time universe (preregistration `docs/plans/2026-11-13-stage2-universe-preregistration.md`).
4. A3 split sweep against the rebuilt canonical, the pre-rerun window (todos 551/552/558/516), the 584 pin and the
   corpus rerun (`docs/operations/corpus-rerun-runbook.md`), then 186-28 and the first counted tests.

Running timers (leave them): Alpaca nightly 04:40Z, derivation 05:20 and 05:45Z, audits 06:00Z, Yahoo dividends
06:30Z, standby probe every 5 min. The IBKR fetcher is gone. Dated: the Massive plan lapses about 2026-12-10;
the archive is the single copy until it is backed up elsewhere (owner deferred offsite backup).

Working rules (binding): a worker editing anything a timer or service runs (providers, the nightly,
bar_derivation, D7, shared writers, the dashboard) works in a detached worktree off origin/main; nothing unpushed
stays on shared main; every landing gets an independent review; measure a defect class and its base rate before
naming a rule; judge tests by the summary line or exit code, never a tail; one heavy job at a time, detached;
after a dashboard package change, `npm ci` before restarting `indicagent-dashboard`.

## Starting a new session

Read this file, then `.planning/todos/PRIORITIES.md`, `ROADMAP.md`, and the design sections for your work. Message
the lead (ListAgents) before starting a lane. Use a detached worktree off origin/main when the shared checkout is
dirty. Never two backfills at once; kill by PID only; never edit a module a live fingerprinted run imports.

## Decisions waiting on the owner

- Todo 547: certify the reversal members and book now, hold `reversal_5_skip1` and the two momentum members
  (S1 drift), or hold the family. E17 landed; the StepM attestation passed; `select_books.py` is unblocked.
- Todo 558: the pre-rebuild feature-additions pass; the lane owners' candidate list is the owner's to change.
- The clean-data lift for price-derived 1d families, the 27 compute_eligible_1d=false names, the entity classes,
  the 185-49 reversal for the 587 rescale.
- Concept-layer reset (todo 571) runs after the 186-26 rebuild and 584's batch.

## Open items that are not verdicts

- Dashboard v3.5 cockpit closed 2026-10-27; six pages served on :3000, Books is empty until phase 188.
- Midterm spec (committed 2026-10-01): forward window to 2027-05-03, result recorded by todo 483.
- Economic series (todo 480): backfilled FRED availability is assumed, not measured; todo 482 (ALFRED reload)
  is gated on phase 184 B8.
- Todo 248: HMM columns carry the todo 451 mask and stay out of every family until the 186-26 rebuild.
- Todo 372: `Panel.sync_shift_null_p` finding 1 lacks independent review; finding 2 (`volume_z` detrending) untouched.
- N1 nonlinear combiner is structurally inconclusive; do not cite as pass or fail.
- Survivorship: every universe reads current state; phase 185 D0 bounds past verdicts.
- E17 battery units show `failed` because the drivers exit non-zero on a pre-registered verdict fail; the runs
  completed and the verdicts are the record (canonical: `e17-battery-daily-v2`). Do not rerun seeds for a pass.

## Delete-after list (disk housekeeping)

Everything under `data/` and `logs/` is git-ignored. Never delete `logs/phase181`, `logs/phase179` (`repro_frozen`
replays frozen verdicts from them), `logs/research/snapshots`, the step A and B evidence under `logs/research/`,
`.venv`. Worktrees (`git worktree list`) are per-session; remove one only when its branch is merged or abandoned.

| Path | Delete when |
|---|---|
| `data/backups/185-38` | find its phase's retention rule first |

## Process pointers

- `.planning/todos/PRIORITIES.md` is the sole todo priority source; the research ledger is the sole verdict source.
- Methodology changes go through `docs/plans/methodology-change-ledger.md`.

## Key decisions (load-bearing)

- `HMM_RANDOM_STATE = 42`: changing it invalidates every regime-derived output.
- Executable returns only, open to open: `panel.forward_returns` is the one target definition; new code never
  reads a target table.
- `ON CONFLICT` on partial indexes in TimescaleDB: column list plus WHERE clause, not `ON CONSTRAINT`.
- Provider history plane (phase 190): `HistoryProvider` protocol in `src/providers/base.py`, one fetcher with a
  provider registry, per-provider budgets from `infra.<provider>.*`; concrete provider leaves import only inside
  `src/providers/` (test_provider_leaf_boundary).
- Corpus pipeline: `--compute-only` silently skips every symbol if `backfill_status` is empty; seed it first
  (query in `.planning/milestones/v3.4-STATE.md`, "Corpus Pipeline Gotcha").
