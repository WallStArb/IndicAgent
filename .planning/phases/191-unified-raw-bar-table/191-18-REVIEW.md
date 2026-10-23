# Plan 191-18 Review: bookkeeping (close todo 530, reconcile the folded-in todos, indexes)

Reviewer: fresh-context review session
Date: 2026-10-22
Commit reviewed: 0ceb8089a (against 191-18-SUMMARY.md, 191-18-PLAN.md)

Verdict: PASS

## Method

Read the commit diff in full (13 files), then verified each SUMMARY claim against the code,
the cited plan records, the live database and the guard tests. Re-ran the tests the SUMMARY
cites. Read-only apart from this file.

## Checks and evidence

1. Links resolve. `pytest tests/unit -q -k "priorities or todos or planning"`: 4 passed,
   exit 0 (includes `test_todo_priorities_link_integrity.py`). Every path referenced in the
   changed files exists on disk: the seven cited phase SUMMARYs, `services/ohlcv_raw_writer.py`,
   `scripts/ops/bars/ops_old_store_backup.py`, `data/backups/191/old_store_backup_manifest.json`,
   both guard test files, both docs/plans references in PRIORITIES rows, and all 13 pending
   todo links touched by the table edits. Todo 530 is in `todos/completed/` and gone from
   `todos/pending/`. The design doc section exists: `docs/plans/2026-10-12-unified-raw-bar-table-design.md:359`
   ("D-191-H: explicit deferrals").

2. Todo 530 closure evidence is real.
   - Plan 03 balance: `191-03-SUMMARY.md:24` records "archive 201.7M, observation 15.6M,
     canonical 318.5M rows inserted" with the four-shard balance check, exactly the classes
     the closed todo cites.
   - Plan 11 R6 over raw: `191-11-SUMMARY.md:37` "R6 now balances every served bar against
     ohlcv_raw and the revision log and exits 0 live"; `:125` records the `--gate` exit 0.
   - Plan 17 close gate: `191-17-SUMMARY.md:18-19` "R6 `ops_capture_completeness --gate`:
     exit 0, unexplained 0 in every (source, timeframe) group (2026-10-18 run)". The three
     `logs/` files that SUMMARY cites all exist (selection gate json, dry-run TSV, legacy
     restamp json).

3. Folded-in dispositions match code reality (all six checked, not just two).
   - 520: `services/ohlcv_raw_writer.py:66` defines
     `FUTURE_TOLERANCE_KEY = "threshold.bar_integrity.future_bar_tolerance_s"`, the refusal
     fires at `:214` and the tolerance is applied at `:411`; seeded by
     `production/migrations/473_future_bar_guard_apr.sql`, live in config_state (value 3600),
     tested in `tests/unit/services/test_ohlcv_raw_writer.py`.
   - 527: `_ANSWERED_WINDOWS_SQL` is a single constant in
     `scripts/infrastructure/backfill/_d1_gaps.py:61`; the service-side copies the todo keeps
     open are still there (`services/bar_derivation.py:225`
     `_SELECT_ANSWERED_WINDOWS_SQL`, `services/bar_auditor.py:82` mirror), matching the
     disposition exactly.
   - 524: `191-16-SUMMARY.md:33-35` records the explicit URA run with 429 raw 15m/1h rows
     (338 + 91) into `ohlcv_raw` only.
   - 521: `191-10-SUMMARY.md:98` (deviation 6) "ops_bar_nightly needed no edit: plan 07
     already moved it to the raw contract".
   - 504: `191-10-SUMMARY.md:8-9,40,50` record the dividend writer on `ohlcv_raw` +
     `ohlcv_revision` only, `pair_d1_series` under D-191-D.
   - 531: `191-01-SUMMARY.md:39,57` record the glossary pass on the new raw-layer names.
   - 189-11 (bonus claim, verified live): `market_data_ohlcv` 15m/1h holds kind `5m_grid`
     only, 15m 106,308,989 and 1h 29,236,103 rows, zero vendor rows; sum 135,545,192 matches
     STATE's "135.5M derived rows".

4. Arithmetic. STATE frontmatter `completed_plans: 120`; recount base 119 verified at commit
   6fb204e77; plan-level SUMMARY files across phase dirs count exactly 120 (11 + 52 + 26 + 8
   + 6 + 17); ROADMAP 191-18 box checked by this commit. ROADMAP, STATE and the SUMMARY file
   count agree at 120. See finding 2 for a wording nit inside the note.

5. Deviation 1 (retire clause repointed to 191-25). Sound and contractually necessary.
   `test_temporary_allow_list_expiry.py:36` parses plan ids, `:49-62` marks the entry done
   once the named plan's SUMMARY exists, and `:82-83` fails it then; with `retire: 191-18`
   and this SUMMARY on disk the entry would have failed while the key is still seeded. The
   plan's own action text (`191-18-PLAN.md:58`) instructs noting removal "on or after
   2026-11-12", never deletion by plan 18, and `191-25-PLAN.md` exists and is the key
   retirement plan that closes todo 533 (ROADMAP:669). Reasoning recorded in three places:
   the test comment (`tests/unit/test_table_and_apr_key_readers.py:153-159`), SUMMARY
   deviation 1, and todo 533's status section. All three guard test files pass (33 passed,
   exit 0, re-run by this review).

6. Deviation 2 (concurrent 123 restore) is documented, not silent: SUMMARY deviation 2 names
   the time (23:52:31Z), the writer's scope (frontmatter only) and the restore basis. Current
   STATE carries 120 with no trace of 123; the commit's parent had 119, so nothing of the
   concurrent write was committed. Deviation 3 also matches reality: main is 3 commits ahead
   of origin/main (this commit unpushed), as stated.

Style: no em dashes and no attribution in any added line (the one grep hit is the literal
doc name "CLAUDE.md 5.63.0" in STATE prose).

## Findings

None at P1 or P2.

- P3-1 (precision): `.planning/todos/pending/533-bar-source-column-split-vendor-and-kind.md:13`
  and `.planning/todos/PRIORITIES.md:58` say the close gates were "R6 and D7 gate exit 0".
  191-17-SUMMARY records exit 0 for R6 (:18), the selection gate (:48) and repro_frozen
  (:53), but D7's gate 2 (:20-38) is a "same known failures or better on every condition"
  comparison with known failures still present (freshness_1d 8 names, session_coverage 181);
  no D7 exit code is recorded. STATE's own plan 18 bullet says it precisely ("D7
  same-or-better", STATE.md:106). Suggest aligning the two 533 texts to the STATE wording;
  the closure itself is unaffected.
- P3-2 (wording, inherited): `.planning/STATE.md:123` says "ROADMAP checked plan rows 118".
  118 was the count of all checked boxes in ROADMAP at recount time, not checked plan rows
  (95 plan rows were checked: 94 PLAN.md rows plus 183-11; the other checked boxes are
  requirement and phase rows). The note was introduced by 6fb204e77 and restated here; the
  operative arithmetic it supports (119 + 1 = 120 = 120 plan-level SUMMARY files) is correct,
  so this is a label nit, not a count error.
- P3-3 (stale adjacent text): `.planning/todos/PRIORITIES.md:127`, the 521 row this commit
  rewrote, still carries "Phase 2 all-names canonical 5m load is RUNNING 2026-10-10".
  STATE records that load as landed 2026-10-10 (220.1M rows). Pre-existing clause left
  unrefreshed in an edited row.

## Verdict rationale

Every load-bearing claim in the commit was independently confirmed: closure evidence
citations match the plan records verbatim, all six folded-in dispositions match code and DB
reality, the count arithmetic reconciles three ways, the guard repoint is required by the
guard's own contract with the reasoning recorded, and the concurrent-writer restore is
documented. The three findings are wording nits that do not affect any decision the records
feed.
