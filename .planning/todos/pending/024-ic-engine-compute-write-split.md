# Todo 024 — ic_engine compute/write split + batch worker pattern rule

## Problem

`ic_engine.py` has the same concurrent-write deadlock risk as the old `regime_writer`:
`_compute_symbol_tf` does both HMM/IC compute AND `execute_batch` INSERTs into
`feature_ic_scores` inside `ProcessPoolExecutor` worker subprocesses. 12 concurrent
writers hitting the same hypertable = same index-page deadlock potential as the June 26
corpus run.

`regime_writer` was fixed in commits 52b76ce0..2c2cb16a: workers return `update_rows`,
main holds a single `write_conn` and writes serially.

## Fix

Apply the same pattern to `ic_engine._compute_symbol_tf`:

1. Rename/refactor `_compute_symbol_tf` so it returns `(pooled_rows, regime_rows, all_results,
   n_skipped)` instead of writing to the DB.
2. Add `_write_ic_results(conn, pooled_rows, regime_rows, ...)` — serial write, called in main.
3. Update `_run_ic_worker` to return rows instead of `n_committed`.
4. Update `main()` to open a single `write_conn` and call `_write_ic_results` per cell.

## CLAUDE.md rule to add

Add to the **Key Rules / Core Patterns** section:

```
- **ProcessPoolExecutor workers are compute-only**: workers must return serializable
  results (rows, dicts) to the main process. All DB writes go through a single serial
  connection in main. Never open a write connection or call execute_batch/conn.commit()
  for writes from a worker subprocess — concurrent writers on the same TimescaleDB
  hypertable cause index-page deadlocks. (Fixed in regime_writer; pattern applies to
  all batch services.)
```

## Scope

- `services/ic_engine.py` — compute/write split
- `CLAUDE.md` — add the rule above
- `tests/unit/services/test_ic_engine.py` — add tests for the new pure-compute function
  (same pattern as `test_compute_symbol_tf_*` in `test_regime_writer.py`)

## Reference

- `regime_writer` fix: `services/regime_writer.py` functions `_compute_symbol_tf` and
  `_write_regime_results`
- `test_regime_writer.py` `_make_mock_conn` pattern for testing compute without DB
