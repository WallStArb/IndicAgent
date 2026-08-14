# 307 - Wrap ic_engine.py's two raw feature_ic_scores UPDATE paths in a compressed-hypertable write session

**Filed:** 2026-08-14
**Source:** Same investigation as todo 306's "Step 3 hit a second bug" update -- see
`project_disk_full_incident_2026_08_13` memory and `services/_batch_utils.py`'s
`compressed_hypertable_write_session` docstring for the full root-cause writeup (a compressed
TimescaleDB chunk has no usable per-row index; any UPDATE against one forces a full
decompressing Seq Scan regardless of predicate selectivity, ~1000x the cost of the same query
against a decompressed chunk).
**Status:** pending, P1 -- real, confirmed exposure (not theoretical), deliberately deferred
out of the 2026-08-14 sweep rather than rushed.

## What

`services/ic_engine.py` has two raw, hand-rolled `UPDATE feature_ic_scores` call sites, neither
migrated in the 2026-08-14 sweep that fixed every other writer against this table:

1. `_FEATURE_STATUS_REFRESH_SQL` (~line 1550) -- refreshes `feature_status_at_eval` from
   `concept_registry`, scoped by `symbol = ANY(%(symbols)s)` + `training_window_end`.
2. The `bh_adjusted_p`/`passes_fdr` writeback pass (~line 4060) -- per-row `executemany()`
   keyed by `(feature_name, symbol, tf, regime, lookahead_bars, training_window_end)`.

Both are genuinely exposed to the same forced-full-scan cost proven against `feature_vectors`
on 2026-08-14 -- `feature_ic_scores` has the identical compressed-hypertable shape (confirmed:
`compression_enabled = true`). Whether either currently causes a visible problem depends on how
often `ic_engine.py` runs and how much of `feature_ic_scores` is compressed at that point --
not yet measured for this file specifically the way `feature_vectors` was.

## Why deferred, not fixed 2026-08-14

`ic_engine.py` is this codebase's largest, most heavily-relied-upon, already-audited write
path -- `ops_ic_shrinkage.py`'s own docstring already calls this out explicitly ("keeps
ic_engine.py's large, already-audited write path untouched (RESEARCH.md Open Question 2)").
Bracketing two write paths inside it with `compressed_hypertable_write_session` is a small,
mechanical change in isolation, but this file deserves a focused session with its own careful
read-through and testing, not a rushed edit folded into an unrelated sweep under time pressure.

## Recommended approach

1. Read both call sites' full surrounding functions -- confirm connection lifecycle (single
   serial connection expected, per CLAUDE.md's ProcessPoolExecutor rule which already cites
   this file as the reference example) and transaction boundaries before wrapping.
2. Wrap each in `compressed_hypertable_write_session(conn, "feature_ic_scores")`, same pattern
   as every other call site fixed 2026-08-14 (see `services/regime_writer.py`,
   `scripts/ops/alpha/ops_ic_shrinkage.py` for the pattern).
3. Remove `services/ic_engine.py`'s entry from
   `tests/unit/test_compressed_hypertable_write_boundary.py`'s `_ALLOW_LIST` once fixed --
   that test's own message says exactly this.
4. Add/extend unit test coverage for both call sites if none exists today.

## Where

- `services/ic_engine.py` (`_FEATURE_STATUS_REFRESH_SQL`, ~line 1550; bh_adjusted_p/passes_fdr
  executemany pass, ~line 4060)
- `services/_batch_utils.py::compressed_hypertable_write_session` (the helper to use)
- `tests/unit/test_compressed_hypertable_write_boundary.py` (allow-list entry to remove)
