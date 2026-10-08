---
phase: 185-daily-data-foundation
plan: 50
subsystem: data-integrity
tags: [todo-508, bar_source_policy, closed_at, revision-waiver, changed-only, d2-v2, d7, gap_closure]
requires: [185-49]
provides:
  - "bar_source_policy.closed_at (migration 460), stamped by the append-only trigger on the one allowed closing UPDATE"
  - "daily revision waiver and --changed-only probe read GREATEST(recorded_at, closed_at) against one per-symbol baseline"
  - "FTV, IP, STE re-derived under their closed 185-38 rows; policy_conformance 3 to 0"
  - "todo 508 closed"
affects: [189-10, 186-26, todo 512, todo 515]
key-files:
  created:
    - production/migrations/460_bar_source_policy_closed_at.sql
    - tests/unit/test_bar_source_policy_closed_at_migration_contract.py
    - tests/unit/services/test_bar_derivation_policy_change_sql.py
    - .planning/phases/185-daily-data-foundation/185-50-SUMMARY.md
  modified:
    - services/bar_derivation.py
    - tests/unit/services/test_bar_derivation_daily.py
    - docs/research/stale-tradier-heads-policy.md
    - .planning/todos/completed/508-stale-basis-tradier-heads-and-185-38-rows-against-continuity.md
    - .planning/todos/PRIORITIES.md
decisions:
  - "A closed_at column stamped by the trigger, not a stored-source vs policy mismatch waiver"
  - "One per-symbol baseline for waiver and probe: the start of the batch that wrote the symbol's last applied daily load"
  - "The three 185-49 closes backfilled at the apply log's upper bound, 2026-10-08 20:15:26.826 UTC"
requirements: [D-06, D-07]
metrics:
  completed: 2026-10-08
  duration: about 35 minutes
  tasks: 5
---

# Phase 185 Plan 50: a policy close visible to the daily stage; FTV, IP, STE re-derived (todo 508) Summary

A close of a bar_source_policy row is now a recorded time: migration 460 adds `closed_at`, set by
the append-only trigger on the closing UPDATE. The daily stage's revision-ratio waiver and its
`--changed-only` probe compare `GREATEST(recorded_at, closed_at)` with the symbol's own baseline.
FTV, IP and STE were re-derived with counts equal to the 185-49 preview, and todo 508 is closed.

## Fix chosen and why

- `closed_at` over the stored-source mismatch alternative. The mismatch rule would waive any name
  whose stored sources differ from what policy implies, which also happens after interior fallback
  admission changes, so it is broader than "the policy changed" and harder to keep narrow. A close
  timestamp records the fact the waiver asks about.
- Stamped by the trigger (`NEW.closed_at := now()` in the UPDATE branch), not by the writer:
  `ops_source_policy.py --close` needed no change and no writer can omit or forge the stamp. An
  INSERT carrying `closed_at` raises; a closed row stays immutable, `closed_at` included; CHECK
  `closed_at IS NULL OR (valid_to IS NOT NULL AND closed_at >= recorded_at)`.
- Legacy closed rows keep NULL (GREATEST ignores it, so they count at recorded_at). The only
  closes whose effect was not yet in the bars are the three 185-49 ones (D7 policy_conformance
  failed on exactly FTV, IP, STE), so the migration backfills those three, matched on policy_id
  and valid_to, with the trigger disabled for that one UPDATE inside the transaction. The stamp is
  2026-10-08 20:15:26.826 UTC, the last write of `logs/185-49/policy_apply.log`; the closes ran
  after OUT's insert at 20:15:24.633.
- One baseline for waiver and probe (`_LAST_DAILY_LOAD_CTE`): the start of the batch that wrote
  the symbol's latest applied `bar_derivation-daily` load, else that load's `loaded_at`. The
  policy is read once at run start, so a close between batch start and the symbol's load row was
  not applied by that load; batch start counts it.

## Migration 460

Rollback dry run first (column added, 3 rows stamped, trigger enabled, rolled back, column
absent). Applied live 2026-10-08 20:55:29 UTC; a second apply ran clean with `UPDATE 0`
(idempotent). Contract test `tests/unit/test_bar_source_policy_closed_at_migration_contract.py`.
Number 460: 457 reserved for 185-48, 458 and 459 taken; 452 appears only in stale 185-43 plan
text (that migration landed as 459).

## Tests

- RED first (05b06477f): `tests/unit/services/test_bar_derivation_policy_change_sql.py` runs the
  exact waiver and probe SQL on the local PostgreSQL against TEMP tables that shadow the real
  names, inside a rolled-back transaction (skipped without a DB, as `test_resource_lease.py`).
  Cases: a close after the last load waives and is due; a later batch over other symbols does not
  hide it; another symbol's close, a close before the load and an unstamped legacy close do not
  waive; a default-row close still waives; a close after batch start but before the load waives;
  refused or other-caller loads are not the baseline; new answers after the symbol's own load are
  due past a later batch; a symbol with no applied load is due. Four more attach the live trigger
  function to a TEMP copy of the table: the close stamps, an insert cannot carry it, an inserted
  closed row keeps NULL, a closed row stays immutable.
- `test_bar_derivation_daily.py`: the probe test now checks that the tradier_owned predicate
  (not the whole probe) has no ohlcv_load read, plus one test that waiver and probe share the
  baseline and the GREATEST.
- Full `tests/unit/ -q` green (exit 0). repro_frozen not run: nothing under
  `src/intelligence/research` or `statistics` changed.

## Narrowness, measured live

Read-only over the 1,529 names with 1d observations: the waiver fires on 31 names under the new
SQL and 28 under the old, and the difference is exactly FTV, IP, STE. The 28 shared are the 27
names with no applied daily load (first-load waiver) and CTVA (its corporate action recorded
15:13 UTC, after its last load). No other name gained a waiver.

## Re-derivation versus the preview

| name | preview removed / changed | dry run 185-50 | applied (21:08:49 to 21:08:52 UTC) | dry run after |
|---|---|---|---|---|
| FTV | 14 / 2,579 | 14 / 2,579 | 0 new, 2,579 changed, 14 removed | 0 / 0 / 0 |
| IP | 2,414 / 2,618 | 2,414 / 2,618 | 0 new, 2,618 changed, 2,414 removed | 0 / 0 / 0 |
| STE | 1,166 / 3,866 | 1,166 / 3,866 | 0 new, 3,866 changed, 1,166 removed | 0 / 0 / 0 |

Every other column also equal (n_stored, n_canonical, changed_source_only 2/4/2, refused_head,
refused_interior 0). The pre-apply dry run ran with `--changed-only` and found all three due; after
the apply `--changed-only` reports them unchanged. Removed dates are exactly the IBKR head before
Tradier's first observation: IP 2006-10-03 to 2016-05-06, STE 2006-10-03 to 2011-05-20, FTV
2016-06-14 to 2016-07-01.

## D7 before and after (1d failing names)

| check | before (20:55 to 21:07 UTC) | after (21:09 UTC on) |
|---|---|---|
| policy_conformance | 3 (FTV, IP, STE) | 0 |
| canonical_recompute | 4 (CTVA, FTV, IP, STE) | 1 (CTVA, todo 515) |
| vendor_basis_run | 13 | 13 |
| unexplained_seam | 6 | 6 |
| freshness_1d | 4 (CTVA, PSKY, QRVO, WBD) | 4 |
| session_coverage | 260 | 263 (FTV 0.9942, IP 0.5203, STE 0.7681) |
| lineage_missing, digest_fresh, report_age | 0 | 0 |

The per-name diff of the two verdict exports moves only FTV, IP and STE. Their session_coverage
failure is the 185-49 amendment's accepted cost: wrong-scale data becomes holes. Records in
`logs/185-50/` (git-ignored): d7_before.out, d7_after.out, verdicts_before.tsv,
verdicts_after.tsv, daily_dryrun.tsv, daily_apply.tsv, daily_dryrun_after.tsv,
daily_dryrun_after_changed_only.tsv.

## Commits

| Stage | Commit | What |
|---|---|---|
| RED tests | 05b06477f | SQL behavior tests and the migration 460 contract |
| Fix | 636b48347 | per-symbol baseline, GREATEST(recorded_at, closed_at) in waiver and probe |
| Migration | a8a42b9ec | migration 460, applied live |
| Apply results | 6b068bbd0 | policy doc "Completed by plan 185-50", D7 before and after |
| Todo | 38d15abc3 | todo 508 to completed/, PRIORITIES row and Data line |
| Summary | this commit | 185-50-SUMMARY.md |

## Deviations from plan

1. [Rule 1 - Bug] The probe's baseline was the newest completed daily batch of any scope, so a
   `--symbols` run moved the watermark for every name. The 185-49 38-name batch finished at
   20:16:36, after the FTV, IP, STE closes (20:15) and CTVA's corporate action (15:13), so a
   `closed_at` alone would still have left the three invisible to `--changed-only`. Fixed by the
   per-symbol baseline for all three probe arms (answers, actions, policy). Under the old SQL the
   probe found 0 names due today; under the new one 31 (the same 31 the waiver names).
2. [Rule 1 - Precision] The waiver's baseline moved from the load's `loaded_at` to its batch's
   `started_at`: policy and observations are read before the load row is written, so the old
   baseline could count a change made mid-batch as applied when it was not.
3. [Process] The pre-commit black pass left a stale index entry for
   `test_bar_derivation_daily.py` after 636b48347 (worktree equal to HEAD); restored that one
   index entry with `git restore --staged`.
4. [Process] No separate /simplify or /review skill pass inside this executor; the diff was
   self-reviewed, and the orchestrator's gate applies.
5. [Scope] STATE.md, ROADMAP.md and REQUIREMENTS.md not written (brief). CTVA untouched.

## For the fetcher launch (189-10 Task 3)

- The run-end daily stage (`--stage daily --symbols <touched> --apply`) is unaffected for normal
  names. A name with a policy insert or close since its last applied daily load is now waived as
  intended; no such name is outstanding after this apply.
- CTVA is waived today by its corporate action, under both the old and the new SQL. Any daily
  apply that includes CTVA (a touched-name run, or an unscoped one) applies the rewrite todo 515
  holds. The fetcher must keep CTVA out of the daily stage until 515 lands.
- Nothing runs `--stage daily --changed-only` today (the bar-derivation unit runs the grid stage;
  the fetcher and the Tradier chain pass `--symbols`). If an unscoped nightly `--changed-only
  --apply` is ever added, it would now pick up CTVA and the 27 names with no applied daily load
  (first-load waiver), which 189-10's record says stay observation-only. Scope such a run to
  compute_1d and exclude held names first.
- FTV, IP, STE: their head dates are holes on dates IBKR answered at the wrong scale and Tradier
  never answered; gap-fill cannot fill them under the current rows. IP's 0.52 and STE's 0.77
  coverage go to todo 512.

## Known stubs

None.

## Threat flags

None. No IBKR or Tradier request, no fetcher or loader start; the one live schema change is
migration 460, and the trigger stays the only path that sets `closed_at`.

## Self-Check: PASSED

- Files exist: production/migrations/460_bar_source_policy_closed_at.sql,
  tests/unit/test_bar_source_policy_closed_at_migration_contract.py,
  tests/unit/services/test_bar_derivation_policy_change_sql.py,
  .planning/todos/completed/508-stale-basis-tradier-heads-and-185-38-rows-against-continuity.md.
- Commits 05b06477f, 636b48347, a8a42b9ec, 6b068bbd0, 38d15abc3 are in history and pushed.
- Live: `closed_at` present, three rows stamped; post-apply dry run 0/0/0; D7 after exit 0;
  tests/unit/test_todo_priorities_link_integrity.py passes; full tests/unit green.
