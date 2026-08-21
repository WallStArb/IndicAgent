# 339 - `backfill_feature_factory.py` worker rows held unbounded in memory across the ProcessPoolExecutor IPC boundary

**Filed:** 2026-08-21
**Source:** `/simplify` (efficiency + altitude angles, independently) and `/code-review medium`
(the review's sole finding) all converged on the same point while fixing [[todo 318]]'s Bug 2.

## What

Todo 318 Bug 2's fix made `backfill_feature_factory.py`'s `ProcessPoolExecutor` workers
compute-only (CLAUDE.md invariant): `_compute_symbol_tf` now returns every computed row for
a (symbol, tf) pair as a Python list instead of flushing it to the DB in
`insert_batch_size` (500-row) chunks as it went; `_run_compute_worker` collects all 4
timeframes' full row lists for one symbol into `results` and returns the whole thing across
the IPC boundary; the main process only re-applies `insert_batch_size` chunking once the
whole payload has already been pickled, sent, and unpickled.

**Concrete cost (code review's numbers):** summed across `_DEPTH_YEARS`/`_BARS_PER_DAY`, one
symbol's full-depth backfill (5m+15m+1h+1d) is roughly 191,520 `feature_vectors` rows, each a
300+-field tuple (`FeatureVector` schema). Held in full in the worker, pickled whole, held
again in the main process before chunked writes begin. With `n_workers > 1`, and because
`ProcessPoolExecutor.map` preserves submission order, peak memory scales with how many
symbols are concurrently in flight (compute-side across workers, plus whatever's queued
waiting on the now-serialized single-connection writer) rather than staying bounded to
~500 rows/worker like the pre-318 code.

**Not a correctness bug** — this is the same `update_rows`-over-IPC shape `regime_writer.py`
already uses successfully (todo 318's own fix deliberately mirrors that established
pattern), just proportionally heavier per row here (full feature vectors vs. scalar HMM
labels). Real risk is confined to full-depth/`--refresh` recompute runs at a high
`n_workers` setting, not the common incremental-gap-fill case (e.g. todo 316's remediation,
which touched far fewer rows/symbol than a full-depth backfill would).

## Why not fixed inline with todo 318

Bounding memory here for real would mean either (a) a `multiprocessing.Queue`/`imap`-based
incremental hand-off so a worker can flush `insert_batch_size`-sized chunks back to the main
process as it computes rather than returning one giant per-symbol payload, or (b) spooling
computed rows to a local temp file and returning only the path. Both are a real design
change to the worker/main IPC shape — well outside todo 318's own scope (eliminating
concurrent writers), and this project's own precedent (todo 291, Phase 172's `/simplify`
gate) is to split memory/efficiency follow-ups like this out rather than bolt them onto an
already-landed correctness fix.

## Fix shape (not yet decided)

- Cheapest: cap `n_workers` for `--refresh`/full-depth runs via an APR key
  (`infra.feature_factory.refresh_workers`, lower than the routine incremental default) so
  peak concurrent-symbol memory stays bounded without touching the IPC shape at all.
- Deeper: restructure worker dispatch so each `pool.map()` unit of work is a
  (symbol, tf, chunk) tuple instead of a whole symbol, giving true `insert_batch_size`-bounded
  memory both in the worker and in transit. Bigger blast radius — touches `worker_args`
  construction, `_run_compute_worker`'s signature, and the main-process aggregation loop's
  per-cell status bookkeeping (a chunk boundary no longer aligns with a
  `backfill_status`-complete boundary).

## Where

- `services/backfill_feature_factory.py` — `_compute_symbol_tf` (row accumulation),
  `_run_compute_worker` (per-symbol results collection), `run_compute_stage` (aggregation
  loop chunking)
