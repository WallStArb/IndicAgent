---
status: pending
priority: P3
filed: 2026-09-23
source: found during live end-to-end verification of the underflow-7symbol-real-column debug
  session (.planning/debug/resolved/underflow-7symbol-real-column.md)
---

> Renumbered 389 -> 392 on 2026-09-23: filed as a duplicate number 389, colliding with
> `389-execute-short-horizon-ic-cell-deletion-prereg-post-176-08.md` (which keeps 389 -- it is
> cross-referenced from STATE.md, MEMORY.md, and the pre-registration doc). Content unchanged.

# `backfill_status.error_msg` is never cleared when a previously-failed cell later succeeds

## What

`_MARK_COMPUTE_COMPLETE_SQL` in `services/backfill_feature_factory.py` only sets
`status`/`rows_written`/`theoretical_max`/`completed_at` on success -- it never touches
`error_msg`. A cell that failed once and is later re-run successfully (e.g. via `--refresh`
after a fix lands) keeps displaying its stale failure text in `error_msg` even though
`status='complete'` and `completed_at` is fresh.

Confirmed live: after the underflow-7symbol-real-column fix landed and all 12 previously-failed
BIL/VRP/ENPH/GLD/NAD/SHY/STIP cells were re-run and reached `status='complete'`, their
`error_msg` column still reads the original `"value out of range: underflow"` text. `status`
and `completed_at` are authoritative and correct; `error_msg` is cosmetically wrong. Not a
correctness bug in the pipeline itself -- purely a status-table hygiene gap that could mislead
a future dashboard view or operator glance at `backfill_status` into thinking a completed cell
is still broken.

## Fix

Add `error_msg = NULL` to `_MARK_COMPUTE_COMPLETE_SQL`'s `SET` clause so a successful completion
always clears any prior failure text.

## Where

- `services/backfill_feature_factory.py` -- `_MARK_COMPUTE_COMPLETE_SQL` (the `UPDATE
  backfill_status SET status = 'complete', ...` statement)
- Related: [312](completed/312-regime-writer-hmm-probability-underflow-real-columns.md) (the
  original underflow-clamp fix for a different write path), the now-resolved
  `underflow-7symbol-real-column` debug session that surfaced this gap
