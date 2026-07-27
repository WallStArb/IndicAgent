---
status: completed
priority: P1
filed: 2026-07-17
completed: 2026-07-17
source: discussed while diagnosing why the 143.1-07 corpus re-run's two crashes wrote zero
  rows to feature_ic_scores despite ~30 hours of compute each time
---

## Resolution (2026-07-17)

Implemented as proposed. `services/ic_engine.py` now writes each unit of compute immediately:
`_write_symbol_results` (one symbol, called via new shared `_record_symbol_result` from both
the checkpoint-resume loop and the ProcessPoolExecutor `as_completed` loop in `main()`) and
`_write_cs_cell_results` (one cross-sectional cell). `bh_adjusted_p`/`passes_fdr` are left NULL
for cluster-representative rows at insert time (non-representatives already got their final
`passes_fdr=False` at compute time, unchanged). A new `_backfill_bh_fdr` runs once after both
compute passes finish: queries `feature_ic_scores WHERE training_window_end = %s AND
passes_fdr IS NULL`, applies one corpus-wide BH-FDR correction via the shared `apply_bh_fdr()`
helper (`src/intelligence/statistics/ic_math.py`), and writes results back with a single batched
`UPDATE ... FROM (VALUES %s)` via `psycopg2.extras.execute_values`, joined on the
`feature_ic_scores` primary key. This is DB-query-driven rather than in-memory-offset-driven, so
it's naturally resumable across a crash regardless of which process wrote the pending rows.
`_persist_corpus_results` and `_accumulate_worker_result` (the old deferred-write accumulators)
are deleted.

A real bug was caught and fixed during review: the `as_completed` loop was only writing/recording
a symbol's rows in the non-error branch, silently dropping any tf's already-computed rows when a
*different* tf for the same symbol failed (each tf is caught independently inside the worker).
Fixed by calling `_record_symbol_result` unconditionally after the error/checkpoint branch.

Also fixed during review (reuse pass): swapped an inline `multipletests()` call for the shared
`apply_bh_fdr()` helper (removed the now-dead `statsmodels` import); and (efficiency pass): the
FDR-backfill patch loop now skips the dict lookup for rows that already have a final
`passes_fdr` (non-representatives), cutting ~800K wasted hash/lookup ops per run down to the
~20K that are actually representatives.

New test file: `tests/unit/test_ic_engine_incremental_write.py` (13 tests, TDD — written and
confirmed failing before implementation). Full `tests/unit/` suite green, ruff/black clean.

Not addressed here, tracked separately: `.planning/todos/pending/129-ic-engine-short-lived-conn-helper.md`
covers extracting a shared connection context-manager for the now 9 near-identical
connect/try/finally/close blocks in this file (this todo added 4 more of that same shape).

# `ic_engine.py` holds all corpus results in memory until the very end — decouple raw-row persistence from the corpus-wide FDR backfill

## Problem

`ic_engine.py` computes every result for the entire run (all 80 symbols' per-symbol cells, then
every cross-sectional cell) and holds it all in memory — `corpus_pooled_rows`,
`corpus_regime_rows`, `corpus_cs_rows`, plus the p-value lists — before writing anything to the
DB. The actual writes (`_write_ic_results`, `_write_cross_sectional_results`) only happen once,
at the very end, after one corpus-wide `multipletests()` (Benjamini-Hochberg FDR) call.

This is not an accident — the FDR correction is intentionally corpus-wide (todo history: doing
it per-cell/per-symbol previously inflated the effective false-discovery rate ~232x, the
already-fixed "P2 bug"). But the corpus-wide-dependency only applies to the *p-values*, a small
scalar list. It does not require holding the full result rows unwritten. As currently built, any
crash near the end of a multi-day run (see the 143.1-07 corpus re-run's two crashes,
`services/ic_engine.py`'s `_compute_cross_sectional_tf` connection-lifecycle bug, fixed
separately as todo 128) throws away the *entire* run's compute — both crashes left
`feature_ic_scores` at 0 rows despite each run completing the full 80-symbol per-symbol pass and
starting the cross-sectional pass before dying.

## Proposed fix

Decouple two kinds of state currently conflated:
1. **Raw per-cell result rows** — fully determined the moment that cell's compute finishes;
   don't depend on anything else in the run. Write these as soon as each cell completes, with
   `bh_adjusted_p`/`passes_fdr` left NULL/pending.
2. **Corpus-wide FDR annotation** — a cheap, second-pass statistical computation over the full
   p-value list, applied as a lightweight `UPDATE`-only backfill onto the already-persisted rows
   once the whole corpus's p-values are known.

This means a crash mid-run loses only the (cheap, rerunnable-in-seconds) FDR backfill step, not
hours-to-days of already-completed compute. It also gives natural per-cell resumability for
free — `existing_keys` (already used for the per-symbol checkpoint mechanism) would see raw rows
as they land, rather than only after the entire run finishes.

## Scope note

This is a real architectural change to the write path of a capital-relevant measurement engine —
touches `_write_ic_results`, `_write_cross_sectional_results`, the corpus-level BH-FDR block in
`main()`, and needs a migration (nullable `bh_adjusted_p`/`passes_fdr` at insert time — check
current schema/constraints first) plus a follow-up backfill UPDATE query design. Deliberately not
implemented in the same session that found it — deserves its own dedicated session (TDD, full
`/simplify` + review cycle, careful thought about the backfill query's own failure modes).

## References

- `services/ic_engine.py` — `_write_ic_results` (~line 2114), corpus-level BH-FDR block
  (~line 3300+, `multipletests(...)`), `_write_cross_sectional_results` (~line 2248)
- `.planning/todos/completed/192-ic-engine-coarse-resume-no-checkpoint.md` — narrower, already
  code-fixed (commit `53267bbd`) checkpoint-key issue for the *existing* per-symbol local-file
  checkpoint mechanism; that mechanism is unrelated to this todo's DB-write-timing gap and
  doesn't cover the cross-sectional pass at all
- `.planning/todos/completed/128-ic-engine-cross-sectional-connection-lifecycle.md` — the
  connection-lifecycle fix that prompted this discussion (fixes the crash; this todo is about
  making a *future* crash, from any cause, cheap instead of catastrophic)
