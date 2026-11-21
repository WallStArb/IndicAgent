---
gsd_state_version: 1.0
milestone: v3.5
milestone_name: Unified Research Pipeline
status: in_progress
last_updated: "2026-11-17T04:00:00.000Z"
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

Goal (owner 2026-11-15): get the compute universe data optimal so the feature and IC work can start; pick every assignment by whether it shortens that path. The clean-data rule (E21) holds: no real-data hypothesis test and no corpus compute until the data gate passes.

Position:
- Data layer: the Massive archive (2003-09-10 to 2026-11-18, 82 GB, `--verify` and `--verify-etag` exit 0, a second copy on ubuntu2, no off-site copy by owner decision) is loaded raw. Canonical is Massive to the pinned seam 2026-11-16 (`config/bars/massive_archive_end.json`), then Alpaca; no IBKR (code, units and raw from 2003-09-10 deleted, the 672,245 earlier rows stay, ledger E22); 1m and 4h are not canonical. Step 7 rebuild, D5 timers and Part F are done.
- Rulings in force: Massive is the yardstick (an incumbent-defect call needs a third witness); survivorship is measured and disclosed, never a gate; extended hours are raw only; low-value names (owner 2026-11-15) get no more effort.
- Stage 2 universe (todo 609, s0 to s8 done): 12,561 securities ever, 4,938 in the tier. Todo 648 is built and on main (192c13ea4: `security_type` table, writer, membership wiring, pin `730622ae`), rehearsed in a rolled-back transaction, nothing applied; month-end members 3,007 (2008-06-30), 3,129 (2012-06-29), 3,824 (2016-09-30) against 2,138, 2,023, 2,188 under the label rule. Years 2003 to 2006 and 2009 stay under the 2,950 floor and are disclosed, not chased. Waits on the owner adopting the 2026-11-21 amendment (preregistration), then: placement install (runbook step 5), step 6b (migration 606 and the writer), rebuild and re-pin (step 7).
- Splits and the A3 sweep: todo 646 landed 3,026 Massive reference rows plus 140 reverse splits, with corrections; the member history audit is clean (0 findings, proven starts written for 11,163 inactive members). The strict sweep is gated by materiality (owner 2026-11-20, CLAUDE.md): split-shaped or wrong-scale breaks in the name-years the compute reads (C for 1d, B for 5m); the rest is disclosed with class counts. Lane A2 landed 31 market split rows, 17 dispositions and two bad bars; the disclosure and the open lists are in todo 629.
- E17 statistic memory fix landed (todo 638): the fitted-book certificate is void on purpose (todo 639); the daily residual and H-C batteries need a rerun and rebind. The `reversal_21` pooled replication is pre-declared (run after the pin; owner veto reserved).

Next, in order: (1) the scoped strict sweep rerun and its disclosure (todo 629); (2) the plan-only data gate rerun and the 77 active members whose latest nightly `proven_start_1d` fact fails (check the 06:11Z audit); (3) the 584 pin readiness table (`.planning/todos/pending/584-corpus-rerun-fix-manifest.md`), a pilot at the new pin, then the corpus rerun (`docs/operations/corpus-rerun-runbook.md`); (4) the `reversal_21` pooled replication and the first counted tests (186-28). Prefix-sum port: not before the pin.

Timers (live since D5): standby probe every 5 min, Alpaca nightly 04:40Z, derivation 05:20 and 05:45Z, audits 06:00Z, Yahoo dividends 06:30Z; the ubuntu2 mirror pulls at 04:30Z (`/home/bg/mirror`, no `--delete`).

Massive dated list (todo 600): the plan lapses about 2026-12-10 (owner: renew or lapse; the lead recommends lapse after the capture). Final dated reference capture and file catch-up about 2026-12-07 (`docs/plans/2026-11-15-massive-plan-lapse-deadlines.md`). No filings capture from Massive (EDGAR direct if ever needed). The Massive nightly leaf (`ops_massive_nightly`) stays off unless the plan renews.

Held post-D1 landings (lead ruling 2026-11-15): `wt-refactor-land`, `wt-l1-kernels`, `wt-r2-prodpin`, the L3 universe projection fix and the `wt-i2-tier` doc; order and gates in `docs/plans/2026-11-15-post-d1-landing-runbook.md`. Pending operator steps (sudo): remove the installed bar-writer, cross-asset, macro-compute, roll-batch and hmm-training units, reinstall wave targets, daemon-reload, restart `service_auditor`.

Working rules (binding): a worker editing anything a timer or service runs (providers, the nightly, bar_derivation, D7, shared writers, the dashboard) works in a detached worktree off origin/main; nothing unpushed stays on shared main; every landing gets an independent review; measure a defect class and its base rate before naming a rule; judge tests by the summary line or exit code, never a tail; one heavy job at a time, detached; after a dashboard package change, `npm ci` before restarting `indicagent-dashboard`.

## Starting a new session

Read this file, then `.planning/todos/PRIORITIES.md`, `ROADMAP.md`, and the design sections for your work. Message
the lead (ListAgents) before starting a lane. Use a detached worktree off origin/main when the shared checkout is
dirty. Never two backfills at once; kill by PID only; never edit a module a live fingerprinted run imports.

## Decisions waiting on the owner

- Accept the 2004-2015 member shortfall (about 2,000 against the 2,950 floor, plus three empty months in 2003) as a disclosed property of the early years rather than a gate (lead recommendation: disclose).
- The E21 clean-data lift for price-derived 1d families, the 27 compute_eligible_1d=false names and the entity classes.
- Todo 600: renew or lapse the Massive plan before about 2026-12-10, and keep or drop the HX370 copy of the archive.
- Todo 547: certify the reversal members and book now, hold `reversal_5_skip1` and the two momentum members (S1 drift), or hold the family. E17 landed; the StepM attestation passed; `select_books.py` is unblocked.
- Todo 558: the pre-rebuild feature-additions pass; the lane owners' candidate list is the owner's to change.
- Daily residual family (todo 636): a failed battery postpones and is never a verdict; the next move after the pooled replication is a lead and owner decision. Adopted 2026-11-18 and no longer waiting: A1, A2, A3, E23, E24, E26 and the stage 2 amendments (`docs/plans/2026-11-16-609-owner-gates-summary.md`).
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
