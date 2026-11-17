---
gsd_state_version: 1.0
milestone: v3.5
milestone_name: Unified Research Pipeline
status: in_progress
last_updated: "2026-11-15T23:20:00.000Z"
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

Position 2026-11-15: Massive is acquired and verified (11,658 files, 2003-09-10 to 2026-11-09, 82 GB), every raw
load is done and gated (403.3M Massive rows in `ohlcv_raw`), the placed-span load and A11 witness gate are met
(zero placed spans left; the installed map is `data/ticker_entity_map/20261115_6195ae11abff`, the one B4 read), and IBKR code, gateway, units and
83 APR keys are deleted (migrations 590-592). IBKR raw rows stay until Part F (no export, owner 2026-11-13; the 672,245 rows before 2003-09-10 stay for good, ledger E22).
The 8a load-check runner is archived (tags `archive/massive-8a-load-checks`, `archive/step7-plan-8a-input`); its
outputs are the admission record and gate nothing.

Canonical after step 7: Massive from 2003-09-10 to the archive end, then Alpaca, no fallback, no IBKR; 1m and 4h
leave canonical. Rulings in force: Massive is the yardstick (an incumbent-defect call needs a third witness);
survivorship is measured and disclosed, never a gate; pre-2016 5m has no IBKR fallback; extended hours raw only.

Step 7 done through D4 (2026-11-16): canonical is rebuilt from raw under d2-v6 (rows after: 5m 452,992,974, 1d 6,308,315,
15m 158,174,558, 1h 43,631,204; 1m and 4h empty). D1 `--verify` exited 0; the 5m selection gate met the B3 criteria (exit 3: no residue other than 290 unreviewed basis flags); the archive-end seam witness left no name unexplained (1d and 5m: 0 of 1,403 names, all one_sided); the NVDA canaries read
canonical_matches_massive at 2024-06-10 5m (gate PASS) and at 2007-09-12 1d (informational); D4 `split_horizon_fresh` 1,529 pass, 0 fail with 0
new red `split_continuity` or `canonical_recompute` rows (198 other new red rows: 93 `session_coverage`, 93 `proven_start_1d`, 9 `slot_coverage`, 3 `alpaca_basis_run`, from the switch to Massive; `partd4_new_red_all.tsv`). B4 passed on the slim gate earlier (1d 3,427 and 5m 95,546 unexplained residue disclosed
as one total per timeframe); map `20261115_6195ae11abff` is installed. D5 (timers, compression auditor, service auditor by hand, Alpaca nightly
last) is done 2026-11-16; Part F (IBKR raw delete, `run_partf.sh`) is pending. Real-data compute
may start now that D1 `--verify` exited 0 and the B3 criteria passed, subject to the owner's clean-data lift and the stage 2 gates.
Low-value names (owner 2026-11-15) get no more effort: unplaced or excluded under todo 512.
Held post-D1 landings (lead ruling 2026-11-15): the `wt-refactor-land` stack (supersedes `wt-refactor-batch`),
`wt-l1-kernels`, `wt-r2-prodpin`, the L3 universe projection fix (`agent-a9b86b958ee414b2e`) and the `wt-i2-tier`
doc; the landing order, gates and owners are in `docs/plans/2026-11-15-post-d1-landing-runbook.md`. Never land them
before D1. The research lane has landed drafts only (published-prior shortlist `docs/ideas/signal-published-prior-shortlist.md`,
top-three prereg drafts `docs/plans/2026-11-15-published-prior-top3-prereg-drafts.md`, 5m tier amendment
`docs/plans/2026-11-15-stage2-5m-tier-and-intraday-universe.md`); no real-data number exists for any of them.
Landed outside step 7: todo 614 rows 4, 5, 7, 14, 18, 19, 21 (a)(d), 22; mypy baseline repaired (a86654717);
migration 594 is applied live (verified 2026-11-15: `alert.lag.bar-writer` gone, `migration_594` history row present).
Pending operator steps (sudo, after step 7): remove the installed bar-writer, cross-asset, macro-compute, roll-batch and
hmm-training units, reinstall wave targets, daemon-reload, restart `service_auditor`.

Lead goal (owner 2026-11-15): get the compute universe data optimal (step 7 rebuild, B4 rulings, stage 2 universe) so the
feature and IC work can start; every session and worker assignment is picked by whether it shortens that path. The
clean-data rule (E21) still holds: no real-data hypothesis test until the data gate passes.

Next, in order:
1. D5 and Part F if still pending (`run_partd5.sh --apply`, then `run_partf.sh`; the lead launches each;
   `docs/operations/massive-step7-runbook.md`).
2. The held post-D1 landings in the landing runbook's order.
3. Todo 609 stage 2 point-in-time universe (preregistration `docs/plans/2026-11-13-stage2-universe-preregistration.md`).
4. A3 split sweep against the rebuilt canonical, the pre-rerun window (todos 551/552/558/516), the 584 pin and the
   corpus rerun (`docs/operations/corpus-rerun-runbook.md`), then 186-28 and the first counted tests.

Timers: live since D5 (2026-11-16): the standby probe every 5 min, Alpaca
nightly 04:40Z, derivation 05:20 and 05:45Z, audits 06:00Z, Yahoo dividends 06:30Z. The IBKR fetcher is gone. Dated: the
Massive plan lapses about 2026-12-10; the archive has a second copy on ubuntu2 (`indicagent-data-mirror.timer` there,
04:30Z, `/home/bg/mirror`, no `--delete`, current through the previous night) and no off-site copy by owner decision
2026-11-15 (todo 618 closed, accepted risk).

Massive dated list (todo 600): the seam is the first NYSE session after the manifest's last file day
(`archive_end_of`), so every file added to the manifest moves it (files now run to 2026-11-13, seam 2026-11-16;
the runbook sets `SEAM=2026-11-16`). Step 7 pins one fixed seam date before B4 is re-ruled; the B4 evidence is
checked against the seam it used. Before 2026-12-01: filings sizing decision. About 2026-12-07: final dated
reference capture (after an entitlement probe) and a final file catch-up with `massive_download --verify`.
Before 2026-12-10: the plan renewal decision (owner) and the HX370 copy named in todo 600 item 1 (owner to confirm or drop, since nothing else goes off-site). The Massive nightly leaf
(`ops_massive_nightly`, on main, timer not installed) stays off until the renewal call; under a lapse it is never installed
(`docs/plans/2026-11-15-massive-plan-lapse-deadlines.md`).

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

- Pending adoptions (list in `docs/plans/2026-11-15-published-prior-top3-prereg-drafts.md`, lead recommends adopt for each):
  the 5m tier amendment ($25M entry, $12.5M exit), the seen-name holdout, A1 (daily residual universe), A2 (sixth member)
  the E23 ledger entry for the three published-prior families, and the family 9 registration with E26
  (`docs/plans/2026-11-15-family9-52week-high-prereg-draft.md`), and the stage 2 closed-list membership amendment for months after the
  last Massive list (`docs/plans/2026-11-15-stage2-membership-after-archive-end-amendment-draft.md`). Nothing is built or run until adopted.
- Todo 600 item 1: keep or drop the HX370 copy of the Massive archive.
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
