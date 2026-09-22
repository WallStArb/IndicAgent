---
slug: ihf-5m-positive-input-error
status: resolved
trigger: >
  DATA_START
  IHF/5m feature-compute backfill writes zero feature_vectors rows. Todo 340
  (docs/... .planning/todos/pending/340-ihf-5m-feature-compute-zero-row-positive-input-error.md).
  backfill_status shows status='failed', error_msg="expected a positive input, got 0.0" for
  symbol=IHF, tf=5m. IHF has full history at 15m/1h/1d -- only 5m never started (0 rows).
  DATA_END
created: 2026-09-22
updated: 2026-09-22
goal: find_and_fix
tdd_mode: false
---

# Debug: IHF/5m feature-compute zero-row "expected a positive input" error

## Symptoms

- **Expected behavior:** `backfill_feature_factory.py --compute-only --symbols IHF` computes and
  writes 5m `feature_vectors` rows for IHF, the same way it already did for IHF's 15m/1h/1d
  timeframes and for every other symbol's 5m timeframe.
- **Actual behavior:** Zero rows written for IHF/5m. `backfill_status.status='failed'`,
  `error_msg="expected a positive input, got 0.0"`.
- **Error messages:** `"expected a positive input, got 0.0"` -- confirmed by direct grep that
  this exact string does not appear anywhere in the codebase. It is a third-party exception
  (candidates: scipy/numpy or statsmodels), caught generically at
  `backfill_feature_factory.py:1415-1417`:
  `except Exception as error: error_msg = str(error); worker_log.error("worker_failed", ...)` --
  and stringified without `exc_info=True`, so no traceback has ever been captured.
- **Timeline:** Filed 2026-08-21 as part of todo 259/296 closure audit. Re-run twice on
  2026-09-22 (`--workers 1`, for a clean single-worker traceback) -- both runs reproduced the
  identical error string, 0 rows written, no new diagnostic signal beyond confirming it's
  deterministic.
- **Reproduction:** `backfill_feature_factory.py --compute-only --symbols IHF --workers 1`
  reproduces it consistently (2/2 runs).

## Todo 340 constraints (read first)

- **Do not run `backfill_feature_factory.py --compute-only` concurrently with anything else
  reading/writing `feature_vectors`/`feature_ic_scores`.** It decompresses the ENTIRE hypertable
  regardless of `--symbols` scope (see `docs/reference/gotchas.md`'s
  `compressed_hypertable_write_session` entry) -- a single-symbol IHF run already took an
  `AccessExclusiveLock` on ~40 chunks and stalled a concurrent `ensemble_trainer.py` for ~10 min
  earlier this session.
- This todo also tracks a separate, structurally distinct bug: 7 other symbols
  (BIL/VRP/ENPH/GLD/NAD/SHY/STIP) failing with `error_msg='value out of range: underflow'` on
  partial/stalled backfills. That bug has a strong, code-inspection-only hypothesis (raw INSERT
  write path in `feature_vector_persistence.py` never got todo 312's `_clamp_to_real_range` fix)
  but is out of scope for this session -- only chase it if it turns out to share a root cause
  with IHF; otherwise it gets its own debug session after this one resolves.

## Pre-verified evidence (orchestrator checked before delegating)

- Confirmed live (2x reruns, 2026-09-22): error is deterministic, not a transient/race condition.
- Confirmed via grep: `"expected a positive input"` does not appear in `src/` or `services/` --
  it originates inside a third-party library call, not application code.
- Two RuntimeWarnings surfaced during the live IHF run, checked and triaged:
  - `feature_factory.py:2284` -- `illiq = log_rets_abs / dollar_vols` is genuinely unguarded (no
    `np.maximum` floor, unlike the codebase's usual pattern). A zero-dollar-volume bar produces
    `inf`/`nan` silently here. This is a warning, not the fatal error under investigation, but
    worth fixing regardless once the fatal error is resolved.
  - `feature_factory.py:1154` -- `np.where` division warning is confirmed benign (numpy evaluates
    both branches of `np.where` before masking; result is correct despite the warning). Eliminate
    this as a candidate; do not re-investigate.

## Current Focus

Resolved -- see Resolution below.

## Evidence

- timestamp: 2026-09-22 19:22 UTC
  checked: `logs/backfill_feature_factory.log`, the `worker_cell_failed` entry for
  `symbol=IHF, tf=5m` from the `exc_info=True` re-run (PID 118400), captured after the
  `gsd-debug-session-manager`/`gsd-debugger` subagents got cut off by an API rate limit
  ("You've hit your session limit · resets 5pm America/New_York") -- the traceback landed in the
  log before the cutoff, so the orchestrator read it directly rather than re-spawning agents into
  the same rate limit.
  found: full traceback:
  ```
  File "services/backfill_feature_factory.py", line 1369, in _run_compute_worker
      rows = _compute_symbol_tf(conn=conn, ...)
  File "services/backfill_feature_factory.py", line 1516, in _compute_symbol_tf
      batch_results = FeatureFactory.compute_batch(bars, ...)
  File "src/intelligence/feature_factory.py", line 8055, in compute_batch
      canary_acausal_placebo_val = _canary_acausal_placebo(closes, i)
  File "src/intelligence/feature_factory.py", line 1962, in _canary_acausal_placebo
      return float(math.log(closes[i + 2] / closes[i + 1]))
  ValueError: expected a positive input, got 0.0
  ```
  implication: `_canary_acausal_placebo` (a deliberate look-ahead-leak positive-control canary,
  not a real trading feature) guards `closes[i + 1] <= eps` (the denominator) but never guarded
  `closes[i + 2]` (the numerator). When `closes[i + 2] / closes[i + 1]` evaluates to exactly
  `0.0` (numerator is a non-positive price), `math.log(0.0)` raises this exact error.

- timestamp: 2026-09-22 19:3x UTC
  checked: `market_data_ohlcv_tradeable` and raw `market_data_ohlcv` for IHF/5m rows with
  `close <= 0`.
  found: exactly one row, both in the raw table and the tradeable view (so it legitimately
  passes the `volume > 0` filter): `2010-05-06 18:50:00+00`, `open=8.03, high=8.03, low=0,
  close=0, volume=2000`.
  implication: `2010-05-06` is the date of the "Flash Crash" -- this is a genuine historical
  data point (real volume, real print), not a synthetic/placeholder bar. Per this project's data-
  retention principle (never drop data that could contain signal), the fix must guard the
  *compute*, not filter the bar out of the corpus.

## Eliminated

- hypothesis: `feature_factory.py:1154`'s `np.where` division warning is the fatal error's
  source -- confirmed benign (numpy evaluates both `np.where` branches; result unaffected).
- hypothesis: an unguarded call in a real (non-canary) feature -- the actual culprit is a
  deliberately-injected look-ahead-leak *test* function, not a trading feature. Its own guard
  was just incomplete (checked one operand, not both).

## Resolution

root_cause: `_canary_acausal_placebo(closes, i, eps=1e-10)` (`src/intelligence/feature_factory.py:1950`)
is a deliberate positive-control canary (injects a genuine look-ahead leak so the IC-significance
gate can be proven to detect contamination when present -- not a real trading feature). Its guard
`if i + 2 >= len(closes) or closes[i + 1] <= eps: return 0.0` only checked the denominator
(`closes[i + 1]`), never the numerator (`closes[i + 2]`). IHF/5m has one real bar --
`2010-05-06 18:50:00 UTC` (Flash Crash), `close=0.0`, volume=2000 (a genuine print, not a
synthetic placeholder) -- that lands on `closes[i + 2]` for some `i`, making the ratio `0.0` and
`math.log(0.0)` raise `ValueError: expected a positive input, got 0.0`. This is a general-purpose
bug, not IHF-specific: any symbol/tf with a close-to-zero print two bars after a normal bar would
trip the same guard gap. IHF/5m is simply the corpus's only currently-known instance.
fix: widened the guard to `closes[i + 2] <= eps` as well:
`if i + 2 >= len(closes) or closes[i + 1] <= eps or closes[i + 2] <= eps: return 0.0`
(`src/intelligence/feature_factory.py:1960`). Matches the function's own existing fallback
semantics (return `0.0` for any degenerate/unavailable future-bar condition) -- not a new
behavior class, just completing the existing one. The Flash Crash bar itself is NOT dropped from
the corpus; only this one canary calculation now degrades to its documented `0.0` fallback for
that specific `i`.
verification:
  - Two new regression tests added to `tests/unit/test_canary_predictors.py`'s
    `TestAcausalPlaceboCanary`: `test_zero_when_numerator_close_is_degenerate` (closes[i+2]==0.0,
    mirrors the real IHF bar shape) and `test_zero_when_numerator_close_is_negative` (closes[i+2]<0,
    same guard covers both). Confirmed RED against pre-fix code
    (`ValueError: expected a positive input, got -0.0495...`), confirmed GREEN after the fix.
  - Full `tests/unit/test_canary_predictors.py` (43 tests) and `tests/unit/test_feature_factory.py`
    (88 tests, includes an AST-pattern check that specifically parses `_canary_acausal_placebo`'s
    definition) both green.
  - `ruff check` / `black --check` clean on both changed files.
  - **Not yet verified end-to-end against a live backfill run.** The original diagnostic process
    (PID 118400, started before this fix landed) is still alive as of this writing and holds an
    active `compressed_hypertable_write_session` on `feature_vectors` (86 chunks decompressed,
    not yet recompressed/VACUUMed) -- per this project's own gotcha, do not launch a concurrent
    `--compute-only` run while it's active. That process also has the pre-fix module already
    loaded in memory, so it cannot self-verify even once it reaches 5m again. **Next operational
    step (not more debugging):** once PID 118400 exits, run
    `backfill_feature_factory.py --compute-only --symbols IHF --workers 1` fresh to confirm real
    `feature_vectors` rows get written for IHF/5m and `backfill_status` flips to `complete`.
files_changed: ["src/intelligence/feature_factory.py", "tests/unit/test_canary_predictors.py"]
