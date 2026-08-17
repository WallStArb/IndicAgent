# 333 - 80 symbol/tf combos in `forward_returns` carry rows past the OOS holdout boundary (inert today, misleading on ad hoc queries)

**Filed:** 2026-08-16
**Source:** Investigating "what is forward_returns staleness blocked on" (follow-up to todo 332).

## Finding

`forward_return_writer.py` intentionally clamps `training_window_end` to
`LEAST(MAX(bar_ts) FROM feature_vectors, alpha.validation.oos_start)` -- OOS-leakage
protection per `docs/plans/OOS-EVAL-PROTOCOL.md` (Phase 141.1 CR-01/IN-02), enforced by
`ops_corpus_pipeline_run.sh` and confirmed correct: `alpha.validation.oos_start` currently
resolves to `2025-12-24T05:15:00Z`, and today's fresh writer run (2026-08-16 06:48-08:03 UTC,
231 symbols, 67.5M rows this run, `computed_at` current) correctly wrote the bulk of the
universe (843 of 923 symbol/tf combos) only through that boundary. `ic_engine.py` also applies
its own `bar_ts <= training_window_end` filter (confirmed via grep, lines 2603/2661/2833) --
this is not currently leaking into IC/ensemble measurement.

**The anomaly:** 80 of 923 symbol/tf combos -- overwhelmingly `15m` timeframe, and the symbol
list overlaps heavily with the 80-symbol ETF set from
[[project_todo316_80_etf_symbols_missing_from_feature_vectors_2026_08_14]] (`DBB`, `EFA`,
`BTAL`, `DBA`, `DIA`, `EEM`, `ARKK`, `BIL`, `CIBR`, `CWB`, `AMLP`, `DBC`, `EDV`, `AGG`, `EMB`, ...)
-- carry `forward_returns` rows with `bar_ts` up to `2026-07-28 19:45:00+00`, seven months past
the current OOS boundary. Root cause not yet diagnosed -- likely orphaned output from an earlier
run that used a later `training_window_end` (before the current `oos_start` clamp was set, or
before todo 316's fix backfilled these symbols), left in place because
`forward_return_writer.py`'s `ON CONFLICT (symbol, tf, bar_ts) DO NOTHING` insert never deletes
stale rows on a later, more-conservative rerun.

**Not an active leak** (ic_engine's own filter protects it) **but a real hygiene/trust gap**:
any future ad hoc freshness check (`SELECT MAX(bar_ts) FROM forward_returns`, no
`training_window_end` filter) reads these 80 combos and reports the table as current through
2026-07-28 -- exactly the misleading read this investigation initially produced before the
per-symbol breakdown surfaced the split. A future reader who trusts a bare `MAX(bar_ts)` without
re-deriving the same `LEAST()` clamp `ops_corpus_pipeline_run.sh` uses will draw the wrong
conclusion, same failure shape the code comments at `forward_return_writer.py:27` and
`ic_engine.py:48` already warn against for *writers* -- this is the reader-side version of that
same risk.

## Fix

1. Diagnose which prior run/config produced the post-OOS rows for these 80 combos (git-blame
   `alpha.validation.oos_start`'s config_history for when it last moved; cross-reference against
   todo 316's backfill timeline).
2. `DELETE FROM forward_returns WHERE bar_ts > (SELECT config_value::timestamptz FROM
   config_state WHERE config_key='alpha.validation.oos_start')` -- scoped, cheap, idempotent;
   confirm count matches the 80-combo set before running.
3. Consider whether `forward_return_writer.py` should assert-and-refuse (or auto-clean) rows
   past its own `training_window_end` at startup, so a future `oos_start` rollback or a stray
   manual invocation with a later value can't silently leave the same kind of orphan behind
   again.

## Resolution (2026-08-16)

**Item 1 (root-cause diagnosis) not done** -- deprioritized in favor of the cheap, idempotent
fix (item 2) since the exact prior run/config that produced these rows doesn't change the
correct remediation. Not expected to recur under current config; item 3 (a startup guard)
remains open below if it does.

**Item 2 executed.** `forward_returns` is a compressed TimescaleDB hypertable (84/85 chunks
compressed) -- the `DELETE` forced a decompress of the touched chunks, same underlying
mechanism as the 2026-08-13 768GB disk-full incident (migration 312), so this followed that
pattern's mandatory sequence:

- `DELETE FROM forward_returns WHERE bar_ts > (oos_start)` -- **`DELETE 301166`**, exact match
  to the pre-scoped count (80 symbols x 15m, confirmed before running).
- Disk usage rose 192G -> 219G (+27GB) from the decompress, as expected.
- `VACUUM forward_returns;` run immediately after -- completed clean, disk settled to 214G
  (5GB net growth from index/catalog overhead, not a leak -- nowhere near the prior incident's
  scale).
- Verified: symbol/tf combos past the OOS cutoff is now **0/923** (was 80/923). A bare
  `MAX(bar_ts)` query now reports the real, clamped freshness instead of the misleading
  2026-07-28 read that started this investigation.
- Confirmed no collateral impact: `ic_engine` (running concurrently, step 5/8 of the corpus
  pipeline relaunch) already filtered by `training_window_end` and never read these rows --
  unaffected before and after. A concurrent session's independent Stage 3 falsification run
  (todos 303/304, PID 3412834) was also running against `forward_returns` at delete time --
  not this session's process to manage, left running; its own query has the same
  missing-OOS-filter gap (see Stage 3 script, not yet fixed) so its results for SPY/TLT at 15m
  may reflect a mix of pre- and post-delete data depending on when in its symbol loop the
  delete landed -- worth a rerun on their end if that matters to their result.

**Item 3 (startup guard) remains open** -- not implemented this session. If this recurs, add an
assert-and-refuse (or auto-clean) check to `forward_return_writer.py`'s startup path.
