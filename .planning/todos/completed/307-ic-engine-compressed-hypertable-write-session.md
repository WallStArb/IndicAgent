# 307 - Wrap ic_engine.py's two raw feature_ic_scores UPDATE paths in a compressed-hypertable write session

## Fixed 2026-08-20

Both call sites wrapped in `_write_session` (`compressed_hypertable_write_session` aliased,
matching `regime_writer.py`/`ops_ic_shrinkage.py`'s own import convention):

1. `_FEATURE_STATUS_REFRESH_SQL` block inside `main()` (~line 5375) -- wrap scoped to the
   `if refresh_symbols:` block's two writes (the UPDATE itself plus the sibling
   `ic_cell_fingerprints` upsert already committed together) and their existing `conn.commit()`.
2. `_backfill_bh_fdr`'s `bh_adjusted_p`/`passes_fdr` `executemany()` UPDATE (~line 4062) --
   wrap scoped to just the write; the preceding `SELECT ... WHERE passes_fdr IS NULL` reads fine
   against compressed chunks, no decompress needed for that half.

Confirmed via read-through both call sites' connection lifecycles before wrapping (todo's own
step 1): `conn` (status-refresh site) is opened at `main()`'s top via `_connect_db()` and
explicitly closed before the `ProcessPoolExecutor` dispatch phase begins; `_backfill_bh_fdr` runs
on a separate, freshly-opened `post_compute_conn` (`_short_lived_conn`) specifically scoped to
the post-compute block, with its own comment confirming "no intervening compute... no idle-
connection risk." Neither call site's connection is held open across the multi-hour worker-pool
compute phase, so bracketing each independently (not sharing one session across both, which
would leave the table decompressed for that entire phase) is correct.

**Step 3 correction:** the todo's own text said to *remove* `services/ic_engine.py`'s entry from
`test_compressed_hypertable_write_boundary.py`'s `_ALLOW_LIST` "once fixed" -- verified this is
wrong. Wrapping the write in a session doesn't remove the literal `UPDATE feature_ic_scores` SQL
text the guard's regex matches; removing the entry would make the guard fail
(`assert_no_unlisted_references`), not pass. Updated the entry's reason text from
`TEMPORARY: ... deliberately NOT touched` to `PERMANENT: ... fixed 2026-08-20, wrapped in
compressed_hypertable_write_session`, matching the exact pattern the other 3 already-wrapped
entries in that same allow-list use.

**Step 4 (test coverage):** `_backfill_bh_fdr` already had dedicated unit tests
(`tests/unit/test_ic_engine_incremental_write.py`) using a hand-rolled fake connection that didn't
implement `compressed_hypertable_write_session`'s full call sequence (`.rollback()`, the
compression-job/APR/GUC-override round trips, etc.) -- broke on the wrap, fixed by switching to
the `ScriptedConn`/`ScriptedCursor` fake already built for exactly this purpose in
`tests/unit/scripts/test_ops_regime_null_out_and_verify.py`. Extracted that fake (previously local
to one file) into a new shared module, `tests/unit/_compressed_hypertable_write_session_fakes.py`,
now imported by both files rather than duplicated a second time -- this fake's internal sequence
is documented as having already changed twice (2026-08-14, 2026-08-15), each requiring every copy
to update in lockstep, so a second hand-rolled copy would have been a real (not hypothetical)
future maintenance cost.

`_FEATURE_STATUS_REFRESH_SQL`'s call site had zero prior execution-path test coverage (only
SQL-content assertions) and is inlined directly in `main()` -- too large and dependency-heavy
(args parsing, worker pool, live DB connections) to unit-test behaviorally without a scope-
expanding extraction this todo didn't ask for. Added a source-inspection regression test instead
(`test_feature_status_refresh_is_wrapped_in_compressed_hypertable_write_session`,
`tests/unit/test_ic_engine_fingerprint.py`) proving the wrap exists and is positioned correctly,
honest about its coverage level (structural, not behavioral).

**Verified**: full `tests/unit/` suite green, including all 3 touched/added test files plus the
CI guard test itself. Not deployed -- `ic_engine.py` is currently mid-corpus-run (live process,
PID confirmed via `ps`); this code change lands on `main` but does not touch or restart that
process. The next `ic_engine.py` invocation picks up the fix.

## `/simplify` pass, 2026-08-20 -- altitude finding applied, one real bug fixed in the test itself

Reuse/efficiency passes on the same diff found nothing. Simplification found two real issues
(applied): the earlier `test_feature_status_refresh_is_wrapped_in_compressed_hypertable_write_
session` compared `source.index()` positions, which only proves ordering, not real nesting --
replaced with an AST-based check (walks the `with _write_session(...)` node's own subtree for a
`Name` reference to `_FEATURE_STATUS_REFRESH_SQL`), immune to comments and multi-line wrapping in
a way even my prior indentation-walk fix (from the `/code-review` pass) wasn't. Manually verified
both directions (a broken/unnested case correctly fails, the real code correctly passes) since
this exact test had already been flagged twice for weak verification. A second finding (duplicate
`_update_calls` test helper across two files) turned out moot -- the altitude fix below already
eliminated the only other copy.

**Altitude finding, applied**: `_backfill_bh_fdr`'s `bh_adjusted_p`/`passes_fdr` UPDATE was a
hand-rolled `executemany()` -- exactly the 6-key/2-set-column shape `bulk_update_by_key` exists
for, and `scripts/ops/alpha/ops_ic_shrinkage.py` already has a near-identical `_PK_COLS`/
`_COL_TYPES` call against this same table. Migrated: added `_BH_FDR_KEY_COLS`/`_BH_FDR_SET_COLS`/
`_BH_FDR_COL_TYPES` constants (mirroring `ops_ic_shrinkage.py`'s naming), replaced the raw SQL
executemany with `bulk_update_by_key(...)`. This is strictly better than the CI-guard-based
protection the original fix relied on: `bulk_update_by_key` structurally refuses to run against a
compressed hypertable with no active session (`RuntimeError`, not just a grep-detectable pattern),
so forgetting the wrap becomes impossible rather than merely CI-catchable. As a side effect, this
call site's SQL is now built dynamically and no longer matches the CI guard's regex at all --
updated `test_compressed_hypertable_write_boundary.py`'s allow-list entry to reflect only 1 raw
call site remains (`_FEATURE_STATUS_REFRESH_SQL`), not 2.

Test for `_backfill_bh_fdr`'s write half rewritten: `bulk_update_by_key` is monkeypatched out
(its own COPY/temp-table/JOIN-UPDATE mechanics are already covered by `test_batch_utils.py`) and
the test asserts on what it was called with (`table`/`key_cols`/`set_cols`/`rows`) instead of
inspecting raw SQL text that no longer exists in `ic_engine.py`'s source. New
`test_backfill_bh_fdr_key_cols_match_feature_ic_scores_primary_key` replaces the old source-grep
PK-column test. Full `tests/unit/` suite green throughout.

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
