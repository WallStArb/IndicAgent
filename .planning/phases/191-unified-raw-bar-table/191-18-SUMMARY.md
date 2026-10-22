# Plan 191-18 Summary: bookkeeping (close todo 530, reconcile the folded-in todos, indexes)

Status: complete
Date: 2026-10-22
Author: gsd executor session (plan 191-18)

## Task 1: todo 530 closed, folded-in todos reconciled, indexes updated

**Todo 530 closed** (moved to `.planning/todos/completed/`, PRIORITIES row removed). Closure
evidence recorded in the todo: plan 03's bulk-backfill balance check counted every old-store
residue class into `ohlcv_raw` (archive 201.7M, observation 15.6M, canonical 318.5M; the small
live-fetcher twins dispositioned by plan 04's delta), plan 11 rebuilt R6 over the raw plane
(exit 0 live), and plan 17's close gate ran `ops_capture_completeness --gate` exit 0 with
unexplained 0 in every (source, timeframe) group (2026-10-18). The open item the todo last
carried (derived 1d: 859,949 writer-labeled load rows with no bar-label join) is dissolved as a
class by the (vendor, kind) keying. The R6 gate runs in the nightly without paging on
known-dead rows, which was the todo's done-when.

**Folded-in todos**, each checked against code before any claim:

| Item | Disposition |
|---|---|
| 520 future-timestamp guard | Writer guard delivered by plan 02 (`services/ohlcv_raw_writer.py`, APR `threshold.bar_integrity.future_bar_tolerance_s`, tested; verified in code). Open remainder: the D7 1d condition, recorded as explicit deferral D-191-H. Todo stays open. |
| 524 parity volume basis | Parity lane serves into `ohlcv_raw` (plan 16). Open remainder: D7's dated tolerance rule and price/volume split, D-191-H. Todo stays open. |
| 527 simplify backlog | Answered-window consolidation done for the `_d1_gaps` copy in plan 06. The service-side copies and the 5m shaper dedup are D-191-H; items 3 to 9 unchanged and open; all listed in the todo's disposition section. Todo stays open. |
| 504 dividend source registry | Not delivered; plan 10 moved the IBKR derivation to `ohlcv_raw` (D-191-D) so the `ohlcv_observation` dependency is gone; the registry and per-symbol failure policy remain open as designed. |
| 521 Alpaca nightly | Nightly wired to the raw contract by plan 07 (confirmed by plan 10's deviation note). Scheduling stays open pending the owner's wiring call. Todo stays open. |
| 531 glossary pass | Phase 191 glossed the new raw-layer names only (plan 01). `market_data_5m`'s naming pass is D-191-H; the other relations unchanged. Todo stays open. |
| 189-11 vendor rows out of the canonical grid | Measured live 2026-10-22: `market_data_ohlcv` 15m/1h holds derived rows only (15m 106,308,989, 1h 29,236,103; zero vendor rows). The 38.8M vendor rows are gone; the criterion is satisfied by the phase 191 layout. 189-11's own plan (its remaining verification items) stays with phase 189; STATE's 186-26 bullet now records the measured fact instead of the stale 38.8M. |
| 533 | Stays pending. New status section in the todo: steps 3 to 9 done (plans 01 to 18), remaining plans 191-19 to 191-25 (Tradier retirement); `scripts/ops/bars/ops_old_store_backup.py` and `data/backups/191/` removed on or after 2026-11-12. PRIORITIES row rewritten to the same. |

The four D-191-H deferrals (design doc "D-191-H: explicit deferrals", planner decision, owner
acknowledgement pending) are recorded in their todo files: todo 520's D7 condition, todo 524's
D7 tolerance rule and price/volume split, todo 531's `market_data_5m` naming pass, and todo
527's 5m shaper dedup (plus its answered-window service copies). None is claimed done.

**Indexes:** ROADMAP 191-18 checked; STATE position bullet replaced (plan 18 done, next plan 19,
recount base 119 plus this plan = 120 completed); STATE's stale 38.8M clause replaced with the
measured zero; PRIORITIES rows for 520, 521, 524, 527, 504, 531, 533 updated and the 530 row
removed.

## Deviations

1. The plan-17 `_PENDING_RETIREMENT` entry in `tests/unit/test_table_and_apr_key_readers.py`
   said "plan 18 deletes the script and the backup together", but this plan's own action text
   (and plan 16's recorded retention) keeps `data/backups/191/` until 2026-11-12. Deleting
   rollback material three weeks early is the wrong resolution, so the retire clause was
   repointed from `retire: 191-18` to `retire: 191-25` (the phase's key-retirement plan that
   closes todo 533; removal tracked in 533's status section). Contractually required: with a
   191-18 SUMMARY on disk, the old clause would fail `test_temporary_allow_list_expiry` while
   the key is still seeded.
2. STATE.md's frontmatter was concurrently rewritten mid-session (23:52:31Z) with the known
   overcount `completed_plans: 123`; restored to the recount base (119, commit 6fb204e77) plus
   this plan = 120. Only the frontmatter was touched by that writer.
3. The plan text says "commit ... and push"; per the coordinator's standing rules for this
   execution (commit path-scoped, never push), the commit is local and CI is the backstop.

## Verification

- `.venv/bin/pytest tests/unit -q -k "priorities or todos or planning"`: 4 passed, exit 0
  (includes `test_todo_priorities_link_integrity.py`, every pending todo has a row and every
  link resolves).
- `.venv/bin/pytest tests/unit/test_temporary_allow_list_expiry.py
  tests/unit/test_table_and_apr_key_readers.py`: 12 passed, exit 0, after the retire-clause
  repoint (the reader-list guard rejects `retire: todo <n>` for this list; a plan id is
  required). `tests/unit/scripts/test_ops_old_store_backup.py`: 21 passed, exit 0.
- `ls .planning/todos/completed | grep -c "^530-"` prints 1; `grep -n "191" .planning/STATE.md`
  shows the current position (plan 18 done, next plan 19).
