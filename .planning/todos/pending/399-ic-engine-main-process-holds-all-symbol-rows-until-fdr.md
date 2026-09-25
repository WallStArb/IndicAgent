---
status: pending
priority: P2
filed: 2026-09-23
source: memory warning during the Phase 176-08 corpus run (main process RSS growth measured live)
---

# ic_engine's main process holds every symbol's full result rows in RAM until corpus-level FDR

## What

`_record_symbol_result` (`services/ic_engine.py`, ~line 5783) writes each symbol's rows as they
arrive, then also appends the full row dicts to `per_symbol_results` for the rest of the run.
The list is only read at the end, to patch `bh_adjusted_p`/`passes_fdr` onto the pending cluster
representatives and to emit per-(symbol, tf) health gauges.

Measured on the 176-08 run (2026-09-23): main-process RSS went from 1.2 GB at start to 4.1 GB
after about 55 of 233 symbols, roughly 58 MB per symbol. At 233 symbols the cold pages go to
swap (51 GB free) and the run survives, with the box at about 1 GB available RAM mid-run. At the
1000+ symbol universe the correlation-regime/breadth design points toward
(`docs/research/correlation-regime-and-single-name-breadth-design.md`), that is about 58 GB, more
than RAM plus swap on this box.

## Fix

Keep only what the end-of-run step needs: for each pending representative, its FDR key
`(feature_name, symbol, tf, regime, lookahead_bars)` and p-value (already in `pvals_flat`), and
compute the health gauges at record time instead of at the end. After corpus-level BH-FDR,
update the pending rows in the database by key (a bulk UPDATE) instead of mutating retained
dicts. Memory then scales with the number of pending representatives, not with total rows.

Acceptance: identical `feature_ic_scores` content on a small fixed-symbol run before and after
(same fingerprints, same FDR columns), and main RSS flat in symbol count on that run.

## Gate

Edits `services/ic_engine.py`, which moves `code_content_key`. Land it with the next change that
already forces a recompute (for example todo 389's post-176-08 landing), never mid-run.

## Update 2026-09-24: first fix did not hold; real root cause found

The post-176 bundle (db48829c8) removed `per_symbol_results`, but main RSS still grew ~44 MB per
symbol in the Phase 178 recompute (5.7 GB at 103/233, 27 of 29 GB used). The remaining holder is
the `futures = {pool.submit(_run_ic_worker, wa): wa[0] ...}` dict in `main()`: every completed
`Future` keeps its full result (pooled_rows, regime_rows, all_results) until the pool block
exits. Fix: `del futures[future]` (and drop `result`) once `_record_symbol_result` returns, plus a
test that the dict shrinks as results are consumed.

Not applied yet: editing `ic_engine.py` mid-run moves `code_content_key` and discards every
completed cell. The 178 run was killed at 103/233 and resumed (fingerprinted cells skip) as the
workaround. Land the one-line fix after the 178 run completes, with the next change that already
forces a recompute. Acceptance unchanged: main RSS flat in symbol count.

## Update 2026-09-24: landed with 412

`del futures[future]` after each result is recorded (guard test in
test_ic_engine_fingerprint.py). Close when the next full recompute shows main RSS flat in symbol
count.
