---
phase: 185-daily-data-foundation
plan: 35
subsystem: data-integrity
tags: [verification, d7, freshness_1d, d-28, etha, todo-490, gap_closure]
requires: [185-31, 185-37, 185-38, 185-41, 185-46, 189-08]
provides:
  - "D7 run on the final 1d verdict code (freshness_1d, migration 455) verified through systemd: Result success, 715 s, 10 verdict rows per compute_1d name"
  - "D-28 gate output, both live integration tests (13 passed), ETHA split confirmation"
  - "todo 490 closing note citing 185-31's commits and grid batches"
affects: [185-42, 185-43, 189-10, 185-47]
key-files:
  created:
    - .planning/phases/185-daily-data-foundation/185-35-SUMMARY.md
  modified:
    - .planning/todos/completed/490-grid-stage-archive-verify-fails-on-revised-bars.md
decisions:
  - "Orchestrator call: the D7 run verified here is a manual systemd start of indicagent-bar-reconciliation-audit.service, not a timer fire; the first timer fire on this code is 2026-10-08 02:00 EDT"
  - "Two D-28 FAILs are reported, not fixed (plan: verification only, no code edits)"
requirements: [D-12, D-21, D-26, D-28]
metrics:
  started: 2026-10-07T22:24:48Z
  completed: 2026-10-07T22:40:00Z
  duration: about 16 minutes
  tasks: 2
  files: 2
---

# Phase 185 Plan 35: Operational closing check on the 1d verdict code Summary

D7 ran on the final 1d design through its own systemd unit and wrote 10 verdicts for each of the 1,502 compute_1d names. Both live integration tests pass and ETHA's split is on one scale. The D-28 gate fails two conditions, each named below with its residue.

## How the run was obtained

This was a manual systemd start, not a timer fire. The orchestrator decided not to wait for the timer. `systemctl start indicagent-bar-reconciliation-audit.service` (via sudo) ran the same unit and code path the timer fires. The only earlier timer fire after 185-41, 2026-10-07 02:00 EDT (06:00 UTC), took 42 s and wrote no bar_integrity rows. It predates the verdict code (a51df6fb3, 08:54 EDT), 185-41 (10:23 EDT) and 185-46's freshness_1d (ea6d9d349, 13:51 EDT). No timer fire has yet run the verdict code.

Follow-up for the next session: confirm the 2026-10-08 02:00 EDT timer fire (journalctl -u indicagent-bar-reconciliation-audit.service and the D7 rows: 10 per compute_1d name, evaluated_at near 06:00 UTC).

## State before the run

- `indicagent-nightly-backfill.timer`: not-found (units deleted by 189-07).
- `indicagent-ibkr-history-fetcher.service` and `.timer`: inactive, timer disabled. Not started.
- `indicagent-tradier-daily.timer`: disabled, inactive (185-46). Not started.
- No backfill_feature_factory, fetcher or Tradier process running.

## Measurements

D7 run, invocation 098a0415a8a3488eaffe16d425c579ea:

- Start 2026-10-07 18:24:48 EDT (22:24:48 UTC), exit 18:36:43 EDT. Result=success, ExecMainStatus=0.
- 11 min 55 s wall, 9 min 33 s CPU, 490.5 MB peak.
- 1d verdicts were written at 22:29:57 UTC and intraday verdicts at 22:36:43 UTC.

Per check, rows written by this run:

| Check | Names | Pass | Fail | Newest evaluated_at (UTC) |
|---|---|---|---|---|
| canonical_recompute | 1,502 | 1,502 | 0 | 22:29:57 |
| digest_fresh (1d and intraday) | 2,222 | 2,222 | 0 | 22:36:43 |
| freshness_1d | 1,502 | 1,428 | 74 | 22:29:57 |
| lineage_missing | 1,502 | 1,502 | 0 | 22:29:57 |
| policy_conformance | 1,502 | 1,502 | 0 | 22:29:57 |
| refused_head_1d (informational) | 1,502 | 1,502 | 0 | 22:29:57 |
| report_age | 1,502 | 1,502 | 0 | 22:29:57 |
| session_coverage | 1,502 | 1,176 | 326 | 22:29:57 |
| unexplained_seam | 1,502 | 1,496 | 6 | 22:29:57 |
| vendor_basis_run | 1,502 | 1,471 | 31 | 22:29:57 |
| slot_coverage | 240 | 0 | 240 | 22:36:43 |
| grid_parity | 480 | 349 | 131 | 22:36:43 |
| stray_vendor_rows | 480 | 480 | 0 | 22:36:43 |
| coverage_cache | 240 | 5 | 235 | 22:36:43 |

Every compute_1d name (1,502 in `instruments`) has 10 1d rows (AAPL: `AAPL|1d` 10 rows, plus 3 each on 5m, 15m and 1h).

Comparison with 185-37's hand run at 19:03 UTC:
- freshness_1d: 72 fail before, 74 now.
- session_coverage: 240 fail before, 326 now.
- unexplained_seam: 8 fail before, 6 now.
- vendor_basis_run: 31 fail before and now.
- The four zero-tolerance checks: 0 fail before and now.

freshness_1d failures, by sessions behind (threshold 2):
- 1,425 names are 1 session behind and 3 are 2 behind. Their last bar is 2026-10-06, the last Tradier load; this run came after the 2026-10-07 close.
- 74 fail. 73 of them have a newest canonical bar from `ibkr_named`, so they are names under an open IBKR exception row, and the IBKR fetcher is stopped.
  - 3 sessions: HWM (ibkr_named) and QRVO (tradier, last bar 2026-10-02).
  - 5 sessions: 35 names, last bar 2026-09-30.
  - 139 sessions: 15 names, last bar 2026-03-19.
  - 89 to 4,244 sessions: 22 single names: FROG, CART, AUGO, RGEN, NEXN, LION, FLUT, ELS, EU, UAMY, FUBO, DKNG, SNEX, MTCH, CC, CNH, AAOI, SAIC, WEX, CUBE, LGND, LEA.
  - Some of these hold almost no canonical history. LEA has 9 canonical 1d bars, all in November 2009. WEX's ends 2013-04-12.
  - These are the class B and C names in 185-46's evidence doc. freshness_1d now names them as verdicts.

session_coverage: the 86 new failures are the 2026-10-07 session.
- 74 of them are 1 session behind, missing only 2026-10-07. Their histories are short, about 48 to 991 sessions, so one missing session puts coverage under the 0.999 threshold.
- The other 12 are stale ibkr_named names, 3 to 5 sessions behind.
- session_coverage judges through the last completed session, so it repeats freshness_1d's staleness on short-history names. These names stay failing until 189-10's update lane lands the 2026-10-07 session. The 240 names that failed before still fail.

Prometheus now carries `bar_integrity_failing_names` for every check, including zero values (for example canonical_recompute 0 and freshness_1d 74). 185-46 found no such series in the prior 36 h; this run clears that.

## Task 2: ETHA, closing checks, todo 490

ETHA:
- corporate_action ed939e61: reverse_split, effective 2026-10-02, factor 1/3, inferred_by tradier_refetch, recorded 2026-10-06 12:38 UTC, 552 changed days. It was confirmed, not inserted.
- Canonical 1d closes, 2026-09-24 to 2026-10-06, all source tradier: 60.99, 60.93, 60.45, 60.84, 60.36, 61.11, 60.33 (10-02), 61.29, 60.89. One scale, no seam.
- The pre-10-06 bars carry a relative residue of about 1e-10 from the factor (60.990000006099). This is not a scale issue.
- This run's verdicts: unexplained_seam pass, canonical_recompute pass, vendor_basis_run pass, freshness_1d pass (lag 1). session_coverage fails (0.99820), one of the 74 short-history names missing 2026-10-07.

`.venv/bin/python -m scripts.ops.bars.ops_data_bar_check`, exit 1:

```
FAIL scrub_pass_complete: fact=True; dry-run keys 72: quarantined 26, replaced 44, open 2; legacy 1d keys 15 (expect 15): quarantined 5, replaced 10, open 0; replaced bars hidden by a stale price_sanity_status 10
PASS seam_audit_complete: fact=True; seam_audit actions 0; without pre-seam split_seam flags 0
FAIL late_name_dispositions: IBKR-sourced late names 52; unresolved 3 (FUBO, LION, RCAT); Tradier-owned excluded 25 (unresolved under IBKR answers: CHTR, SIL, UNG, VCIT, VCSH)
PASS no_pre_move_bars_visible: IBKR-source pre-move 1d bars in tradeable view 0; venue_bars_1d=false
PASS dividend_coverage: yahoo coverage 1502/1502 (100.0%, needs >= 99%); total_return importable=True
PASS survivorship_apr_keys: present 6/6
PASS inventory_is_active: inventory names with is_active false: 0
5/7 conditions pass
```

The two failing conditions and their residue:

- scrub_pass_complete is a regression from 185-34, which had PASS with quarantined 28 and open 0. The 2 open keys are RSPM and RSPS on 2010-05-06, the flash-crash day.
  - Neither key has any bar_quality_flag row now.
  - The stored bars are source tradier (RSPM close 10.534, low 7.178; RSPS close 10.37, low 9.346).
  - The ohlcv_revision rows hold the old ibkr_named closes (10.53, 10.37). The daily stage wrote them at 2026-10-07 11:37:40 and 11:37:41 UTC (`bar_derivation-daily`, chained from the last Tradier load before 185-46 disabled the timer).
  - The newest 1d scrub fact is 2026-10-03 20:59:45 UTC, which predates those revisions. The keys are therefore neither quarantined nor "replaced and judged".
  - Unblocking them needs a 1d scrub pass after 2026-10-07 11:38 UTC to judge the new Tradier bars. The script cannot say whether the flags were removed or never re-created on the replacement; that question goes to whoever runs the scrub.
- late_name_dispositions: 3 unresolved IBKR-sourced late names, FUBO, LION and RCAT. All three appear in 185-34's residue list of 7, so this is known residue, down from 7. The excluded Tradier-owned names unresolved under IBKR answers are CHTR, SIL, UNG, VCIT and VCSH.

Live integration tests (`-m integration`; the fetcher service was inactive, so the grid test ran):

- `tests/integration/test_d2_single_writer_live.py`: 6 passed (only d2-v2 canonical sources, ibkr_named only under an exception row, lineage complete, sampled derive_daily_v2 recompute equal, digest covers every month, no scale break across a split).
- `tests/integration/test_derived_grid_live.py`: 7 passed (no session at two 1h minutes, derived and session-anchored, equals direct 5m aggregation, first 1h open equals first 5m open, agreement with IBKR SMART 1d, archive holds removed observations, digest covers 5m/15m/1h).

Todo 490: the file moved to completed/ in 4925cea6d (2026-10-06), and its PRIORITIES row already cited 185-31. Its frontmatter still said `status: pending` and it had no closing note. This plan set `status: completed` and added a "Closed 2026-10-07" section citing 185-31's commits (7bd83731d, a01b82a55, 9cc064c2c, fd888c2c1, eba482774) and the grid batches (f5c5323f-d1b9-4869-862c-37ebb8f46680 completed with 240 symbols and no failures; 91190fc2-00b2-4dcc-890e-631716c1ff4c completed, idempotent). `tests/unit/test_todo_priorities_link_integrity.py`: 4 passed.

## Commits

| Task | Commit | What |
|---|---|---|
| 2 | da68f3d0d | todo 490 closing note and status |

Task 1 was verification only and has no commit.

## Verification

- Task 1 verify (D7 half; the Tradier half was dropped by the 2026-10-07 amendment): `systemctl show indicagent-bar-reconciliation-audit.service -p Result --value` prints success.
- Task 2 verify:
  - The link-integrity test passes.
  - The ETHA tradier_refetch count is 1.
  - `ls .planning/todos/completed/ | grep '^490-'` matches.
- Must-have truths:
  - The nightly timer is gone. Met.
  - The fetcher is still stopped. Met.
  - ETHA is recorded and on one scale. Met.
  - D7 run verified with every compute_1d name judged on every 1d check. Met, by a manual systemd start rather than a timer fire.
  - Closing checks: the live tests pass. ops_data_bar_check exits 1 and names only real residue. todo 490 is closed.
- No code was edited. Nothing was written to the database beyond the D7 run's own verdict rows.

## Deviations from plan

1. [Orchestrator decision] The D7 run is a manual `systemctl start` of the same unit, not the first timer fire. The plan's point is observing the timers' own fires, so the 2026-10-08 02:00 EDT fire still needs confirming; the follow-up line above names it.
2. [Plan text] Todo 490 was already in completed/ with its PRIORITIES row updated (4925cea6d), so no move was needed. Only the closing note and status were added.
3. [Not fixed, reported] ops_data_bar_check exits 1. scrub_pass_complete regressed on RSPM and RSPS (see above). The plan's acceptance allows a failure that names real residue, and both failures do.
4. STATE.md, ROADMAP.md and REQUIREMENTS.md were not written: the brief forbids in-place writes, and D-28 is not fully met. The orchestrator records the plan.

## For the next plans

- Next session: confirm the 2026-10-08 02:00 EDT D7 timer fire.
- 185-42: nothing in this plan changes its delete list. The ops_data_bar_check scrub condition needs a 1d scrub pass after 2026-10-07 11:38 UTC for RSPM and RSPS 2010-05-06. If 185-42 or 185-43 reruns the gate, run the scrub first, or expect this FAIL. FUBO, LION and RCAT remain the late-name residue.
- 189-10: until the update lane lands 2026-10-07 and later sessions, every D7 run fails freshness_1d on the 74 stale names and session_coverage on about 74 short-history names. The Grafana freshness alert fires for that reason (expected, 185-46).
- 185-47: 73 of the 74 freshness failures are names with an open IBKR exception row whose IBKR series stops in the past, in several cases years ago (LEA's whole canonical history is 9 bars from 2009). The swap's from-D policy does not repair their history. 189-10 Task 1b's refresh, the gap-fill lane and the class C decisions must cover them.

## Known stubs

None.

## Threat flags

None. T-185-35-01: no timer was started or enabled. T-185-35-02: the ETHA corporate_action row was confirmed, not inserted.

## Self-Check: PASSED

- FOUND: .planning/phases/185-daily-data-foundation/185-35-SUMMARY.md
- FOUND: .planning/todos/completed/490-grid-stage-archive-verify-fails-on-revised-bars.md (status completed, closing section)
- FOUND commit: da68f3d0d
