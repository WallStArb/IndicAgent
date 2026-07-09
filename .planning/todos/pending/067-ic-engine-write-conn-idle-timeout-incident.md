# 067 — ic_engine.py write_conn idle-timeout incident (fixed 2026-07-08)

**Status:** fix applied and unit-tested same session; needs a fresh corpus rerun to confirm in
production before this todo closes.

## What happened

The 2026-07-07 corpus rerun (started 17:00) failed at step 4/7 (`ic_engine.py`) twice:

1. First attempt (20:32-21:29, exit 1): orchestrator declared FAILED after 3462s; the captured
   log has only RuntimeWarnings, no traceback — root cause on this attempt unconfirmed, likely
   the same issue below given the timing (well past any reasonable idle threshold).
2. Second attempt (resumed ~00:36, presumably by a concurrent session): ran the full per-symbol
   pass + cross-sectional pass successfully — 53 minutes of compute, 819,538 representative
   rows through corpus-wide BH-FDR — then failed at the very first DB write with
   `"server closed the connection unexpectedly"` (`ic_engine.log.1`, 01:29:58).

## Root cause (confirmed)

`write_conn = _connect_db(settings)` was opened at the *start* of the run (before the
per-symbol ProcessPoolExecutor pass and the cross-sectional pass), then held completely idle
— zero queries — for the entire ~53+ minute compute phase, only used at the very end for the
actual writes. A connection idle that long is exactly the profile that gets dropped (this DB
has an active idle-session timeout — confirmed via `docker logs timescaledb`, which shows
routine `FATAL: terminating connection due to idle-session timeout` entries roughly every
15 minutes for other sessions throughout the night). Ruled out: Postgres crash/restart
(`pg_postmaster_start_time` unchanged since 2026-07-04), OOM kill (checked `dmesg`/`journalctl`,
nothing), container health (`docker inspect` shows healthy, no restart).

## Fix applied (`services/ic_engine.py`, this session)

1. Moved `write_conn`'s connect call from the top of the run to immediately before its first
   real use (right before `_write_ic_results`) — idle time is now ~0 regardless of how long the
   compute phases take.
2. Added an intermediate `conn.commit()` between the pooled_rows and regime_rows batches in
   `_write_ic_results` — both use `ON CONFLICT ... DO NOTHING` (verified idempotent), so
   committing early is safe and shrinks the blast radius of any future write failure from
   "lose the whole run" to "lose whichever single batch was mid-flight."
3. `tests/unit/test_ic_engine_*.py` (32 tests) + full `tests/unit/` suite run green after the
   change (see session log; full-suite run was in flight when this todo was filed — confirm
   before closing).

## What's still open

- The **first** attempt's failure (20:32-21:29) never got a real root-cause — its log only has
  RuntimeWarnings. If it recurs after this fix, that's a second, different bug.
- Consider (not done here, scope creep for an incident fix): the same "long-idle-then-write"
  pattern may exist in other long-running corpus-DAG steps — worth a quick audit of
  `ensemble_trainer.py`/`alpha_publisher.py`/`forward_return_writer.py` for the same idiom if
  this recurs elsewhere.

**Update 2026-07-09:** the 6th corpus rebuild resumed from step 4 today and got through this
exact write path — the idle-connection fix held, no recurrence. It then hit a **different,
unrelated** OOM in the per-symbol `ProcessPoolExecutor` pass (plain `fetchall()`-before-reduce
pulling a full 392K-row/150-column symbol cell client-side, ~4.3GB/worker × 12 workers > box
memory) — root-caused and fixed in the same session that discovered it: switched to a chunked
named server-side cursor, same shape as the sibling fixes in migrations 183 and 209
(`infra.ic_engine.symbol_fetch_chunk_rows`, migration 212). That fix is a separate incident, not
a recurrence of this todo's bug — no new todo filed for it since it's fully resolved (root
cause, fix, and regression-preventing pattern match to prior sibling fixes), not deferred.
**This todo's own closure gate is unchanged and still open:** no corpus rerun has completed
successfully end-to-end yet. Resume via
`bash scripts/ops/corpus/ops_corpus_pipeline_run.sh --from-step 4` and confirm `feature_ic_scores`
gets fully populated for `training_window_end = 2025-12-24 05:15:00+00` before closing.
