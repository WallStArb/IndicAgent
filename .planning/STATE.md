---
gsd_state_version: 1.0
milestone: v3.5
milestone_name: Unified Research Pipeline
status: in_progress
last_updated: "2026-11-24T12:00:00.000Z"
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
- Data layer: the Massive archive (2003-09-10 to 2026-11-18, 82 GB, `--verify` and `--verify-etag` exit 0, a second copy on ubuntu2, no off-site copy by owner decision) is loaded raw. Canonical is Massive to the pinned seam 2026-11-16 (`config/bars/massive_archive_end.json`), then Alpaca; no IBKR (code, units and raw from 2003-09-10 deleted, the 672,245 earlier rows stay, ledger E22); 1m and 4h are not canonical. The Massive step 7 canonical rebuild, D5 timers and Part F are done ("step 7" below means the stage 2 membership rebuild and re-pin).
- Rulings in force: Massive is the yardstick (an incumbent-defect call needs a third witness); survivorship is measured and disclosed, never a gate; extended hours are raw only; low-value names (owner 2026-11-15) get no more effort.
- Stage 2 universe (todo 609, s0 to s8 done): the s5 rebuild and re-pin are done (membership 1,042,561 rows over 12,857 securities; `CLOSED_LIST_CANDIDATES_SHA256` af96da67, `22be5378a`); the data gate at scope 1d passes. The 1d-first corpus run record is `a4f6ad40` (commit b373cb0, rebuild key beb8d2b6; data_gate and pin_gate completed, the feature pilot failed G1 to G3 and G6, todo 652; parked); 252928d9 and e8f95b33 are superseded. `rebuild_code_key()` on main (cd0af500) differs, so any new run gets a new pin and none resumes. Todo 648 (`security_type` table, writer, membership wiring) is on main. Years 2003 to 2006 and 2009 stay under the 2,950 member floor and are disclosed, not chased. Both amendments (2026-11-21 and 2026-11-21b, placement rule P1) are adopted (owner veto reserved).
- Dividends (todo 651, closed): Massive is a third dividend coverage source (rule `massive-dividend-coverage-v1`, migration 608), loaded and read by the research snapshot. Measured on the first counted panel: `div_covered` covers 59.7% of member cells (was 23.1% with Yahoo alone), 6,700 of 12,245 names; 5,292 member names stay uncovered (all dead: 5,192 with no events at all, 96 whose coverage misses their member days, 4 with gap rows only); ledger 2026-11-21d (`74bb4ffd0`).
- Pin gate: `d2_landed` for dead members is open and held by a worker (branch `wip/pin-gate-d2-member-verdicts`; ledger 2026-11-21e pending).
- Splits and the A3 sweep: todo 646 landed 3,026 Massive reference rows plus 140 reverse splits, with corrections; the member history audit is clean (0 findings, proven starts written for 11,163 inactive members). The strict sweep is gated by materiality (owner 2026-11-20, CLAUDE.md): split-shaped or wrong-scale breaks in the name-years the compute reads (C for 1d, B for 5m); the rest is disclosed with class counts. Lane A2 landed 31 market split rows, 17 dispositions and two bad bars; the disclosure and the open lists are in todo 629.
- E17 batteries: the statistic memory fix landed (todo 638). Amendment A4 (2026-11-21c) dropped M3 from the daily residual family; the reduced family passed pooled on seed bases 7,000,000 and 8,000,000 and the record `research/battery_passes/daily_residual_2026-11-21.json` is bound (H-C seasonality rebound at the same commit). Both daily residual specs have run (nine charged vintage_1 looks including three killed attempt rows; ledger 2026-11-22b and 2026-11-22c); `reversal_21` is the only member with a small raw p (0.001 h5, 0.0002 core), before StepM. The phrase "reversal_21 pooled replication" is retired (ledger 2026-11-23b): R-1 is a non-gating, non-independent sub-period disclosure of the two recorded runs (charges no look) and R-2 is the forward confirmation at book freeze; owner veto reserved.

Next family after the daily residual run (lead ruling 2026-11-22; outcomes and the order after them in `docs/plans/2026-11-24-family-order-after-1d-corpus.md`): H-C seasonality (E23, 4 looks; E17 pass bound, `runner.static_gate` passes, covered by the E21 lift), then family 9 (E26, 2 looks), then family 10 (E24, 4 looks). Family 9's kernel is on main (`families/high_anchor.py`, unregistered, no battery); its close member input edits two runner statistic functions, so it lands only after both counted runs, with both battery records rebound in the same commit (todo 653, P2).

Queue (lead, 2026-11-24; one heavy job at a time, detached, under the DIMM watchdog with the host thermal cap on and 4 workers; recipe `launch_family10.sh` and `rerun_block2.sh`, gate in `f10_common.sh`):
- Host fault (ledger 2026-11-24b, 2026-11-24g): DIMM overheating on 2026-11-23 corrupted memory and killed the first family 10 runs; the data scan was clean. Standing rules: host thermal cap on (`indicagent-host-thermal-cap.service`), DIMM alerts loaded (`production/alertmanager-rules.yml`; no receiver delivers until the owner supplies credentials), 4 workers, guarded launchers. Owner: clean or repaste, airflow.
- Lane A, counted-test path: done. The four family 10 counted runs completed on 2026-11-25 (07d6dfc3, 38229ce1, 11f2076f, 881528b6) and the StepM read over 16 series is recorded (ledger 2026-11-25b: `reversal_21` twice and `volume_shock_1_50` primary selected). Nothing further is counted until the corpus rerun lands and a new family is registered (order in `docs/plans/2026-11-24-family-order-after-1d-corpus.md`).
- Lane B, data integrity: todo 649 detector and timer live (installed 2026-11-26, daily 07:45Z; base rate measured over a month). Todo 600: the final capture runs now (restat 0 drifted, file catch-up done 2026-11-26, reference capture dated 20261126, a worker captures the other entitled families and verifies the ubuntu2 copy; plan in `docs/operations/massive-final-capture.md`); the last 20 tape sessions (327 GB, `massive_tape_slice`, about 7 h) start on the lead's go after the repilot (all 20 sessions are published) and the last pass, on the earlier of the month-end list being served (2026-12-01 or 12-02) and the expiry minus 2 days, adds the 2026-11-30 month-end lists (order in `docs/operations/massive-final-capture.md`); renew or lapse is the owner's call (lead recommends lapse after that pass).
- Lane C, corpus rerun: the re-pin landed (ff7c28acd, d5645d391) and runs eca9e854 and f9f69166 are superseded and deleted through the tool; runs 04db3930 and 0e020c5a stay as evidence until released. Run dcb7caa4-b1d0-4736-be54-197c9e521dce (scope 1d, code key 487f4ab434df, commit 86161748e): the pilot passed G1 to G6 (exit 0 at 02:33Z, 64 units, 48.9 s per unit, run_resource peak 1.90 GiB). `stage_1d` runs through `scripts/ops/corpus_stage_launch.sh` (`--through feature_complete`, about 7.0 h, peak disk 55.7 GB of 1,089 GB), started 05:14Z under the floor `infra.run_guarded.mem_floor_gib.stage_1d` = 24 (APR, migration 622; the config_history reason cites the pilot peak). The six blocking timers stay quiesced until the 1d IC measure completes (`ic_measure_launch.sh` re-quiesces and releases). Resume after a stop: `setsid -f bash scripts/ops/corpus_stage_launch.sh <run> <key prefix>`. Next: the 1d IC measure (width 16, `ic_tfs` 1d only, todo 471). Lead: indicagent-9b. Todo 669 build (persistent h5 route, stored influence series in migration 624, stepm_persistent and its 20-cell attestation) is ready unpushed at 65d9b9a07 in /home/bg/dev/indicagent-wt-669; the 656 task 3 harness at b1f0629ea in /home/bg/dev/indicagent-wt-656; landing sequence, battery commands and the four owner rulings: that worktree's docs/research/handoff-669-656-landing-2026-11-27.md (lands after the IC measure). Status 2026-11-27 12:00Z: run dcb7caa4 stage_1d completed (515 units, 24,417,050 rows, 11,887 names, peak 1.77 GiB); feature_complete FAILED the column screen at 10:53Z (G1 11: SPY self-residual and SGOV vol columns; G2 23: dividend_yield 8 names, rest singles; G3 489: ob_mitigation_pct 183 names, trend_direction, trend_duration_bars and trend_leg_count 86 each; report logs/feature_column_screen_20261127T105353Z.json in the run worktree); timers held by design. Next: a materiality ruling and diagnosis, then resume with corpus_stage_launch.sh; the 669 landing waits for the IC measure.
- Sessions (ListAgents 2026-11-27): lead indicagent-9b; indicagent-a1 operates the Massive final capture (todo 600: tape slice on the lead's go, then the final pass); indicagent-03 works todo 681; indicagent-b9 holds the launcher and pilot-timing stack. Update this line when the roster changes.
- Lane D, hygiene (idle workers, light): worktree dispositions, 656 tasks 3 to 5 (the residual run is counted; task 3 starts a capped test container, task 4 reads production, so both wait for the family 10 runs to be recorded; todo 529 is closed). Todo 654 waits for a planned window.
- Owner only: todo 600 plan call, the sudo operator step below, the ledger 2026-11-23b veto (R-1, R-2).

Timers (live since D5): standby probe every 5 min, Alpaca nightly 04:40Z, derivation 05:20 and 05:45Z, audits 06:00Z, Yahoo dividends 06:30Z; the ubuntu2 mirror pulls at 04:30Z (`/home/bg/mirror`, no `--delete`).

Massive dated list (todo 600): the plan lapses about 2026-12-10 (owner: renew or lapse; the lead recommends lapse after the capture). Final dated reference capture and file catch-up about 2026-12-07 (`docs/plans/2026-11-15-massive-plan-lapse-deadlines.md`). No filings capture from Massive (EDGAR direct if ever needed). The Massive nightly leaf (`ops_massive_nightly`) stays off unless the plan renews.

Pending operator steps (sudo): remove the installed bar-writer, cross-asset, macro-compute, roll-batch and hmm-training units, reinstall wave targets, daemon-reload, restart `service_auditor`. Enable user linger (todo 681 part B precondition): `sudo loginctl enable-linger bg`, because with `Linger=no` the user manager stops when the last session closes and takes the run scopes with it; reversible (`disable-linger`); verify with `loginctl show-user bg -p Linger` reading `Linger=yes`.

Working rules (binding): a worker editing anything a timer or service runs (providers, the nightly, bar_derivation, D7, shared writers, the dashboard) works in a detached worktree off origin/main; nothing unpushed stays on shared main; every landing gets an independent review; measure a defect class and its base rate before naming a rule; judge tests by the summary line or exit code, never a tail; one heavy job at a time, detached; after a dashboard package change, `npm ci` before restarting `indicagent-dashboard`.

## Starting a new session

Read this file, then `.planning/todos/PRIORITIES.md`, `ROADMAP.md`, and the design sections for your work. Message
the lead (ListAgents) before starting a lane. Use a detached worktree off origin/main when the shared checkout is
dirty. Never two backfills at once; kill by PID only; never edit a module a live fingerprinted run imports.

## Decisions waiting on the owner

Commands, checks, deadlines and recommendations for the owner-only items below: `docs/operations/owner-action-sheet.md`.

- Host cooling (ledger 2026-11-24b): clean or repaste the ubuntu1 unit and add airflow over the DIMMs; the software cap, watchdog and alerts are in place but the relaunch gate (DIMMs 60 C or less at start) and any move from 4 to 8 workers depend on it. Alert delivery needs Discord or Telegram credentials (the Alertmanager receiver is a no-op).
- Corpus rerun directive (relayed by a peer 2026-11-24, not heard by the lead): confirm it should start right after the family 10 counted runs, 4 workers, scope 1d.
- More sessions: the backlog supports a session for todos 667 and 668 (ic_measure time chunks and checkpoint grain), one for the 558 candidate list, and the next session starts the todo consolidation at batch 5 and the 25 deferred todos (`docs/research/priorities-decision-log.md`, 2026-11-24).
- Accept the 2004-2015 member shortfall (about 2,000 against the 2,950 floor, plus three empty months in 2003) as a disclosed property of the early years rather than a gate (lead recommendation: disclose).
- The E21 clean-data lift for price-derived 1d families, the 27 compute_eligible_1d=false names and the entity classes.
- Todo 600 ruled by the owner 2026-11-26: the Massive plan lapses about 2026-12-10, no renewal unless it is needed when the system goes live (its purpose was the 20-plus years of history for all stocks, now acquired); the HX370 copy is dropped (copies stay ubuntu1 and the ubuntu2 mirror); the fx and crypto aggregate capture is dropped (owner 2026-11-26, partial by design; `docs/operations/massive-final-capture.md`). Left for the lead: the final pass about 2026-12-07, then the plan lapse date read off the account page.
- Todo 547: certify the reversal members and book now, hold `reversal_5_skip1` and the two momentum members (S1 drift), or hold the family. E17 landed; the StepM attestation passed; `select_books.py` is unblocked.
- Todo 558: the pre-rebuild feature-additions pass; the lane owners' candidate list is the owner's to change.
- Daily residual family: todo 636 closed 2026-11-27 (battery pass bound under A4, both counted runs completed, the StepM read of ledger 2026-11-25b selected `reversal_21` primary and core); its use waits on the owner's 547 ruling. Adopted 2026-11-18 and no longer waiting: A1, A2, A3, E23, E24, E26 and the stage 2 amendments (ledger and the stage 2 preregistration).
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
