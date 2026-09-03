# Deferred Items — Phase 141.1 (Wave 1: plans 01, 02, 03)

Out-of-scope discoveries found during execution. Not fixed here per the executor's scope
boundary rule (only auto-fix issues directly caused by the current task's changes).

## Pre-existing test failures (out of scope, not caused by any Wave 1 plan)

9 of these failures, all traced to the same root cause, confirmed present at each worktree's
base commit `efe64993` (before any Wave 1 changes) — not a regression introduced by plans 01,
02, or 03. None touch `production/migrations/192_feature_ic_scores_regime_scope.sql`,
`services/ic_engine.py`, `tests/unit/test_regime_scope.py`, `ops_corpus_pipeline_run.sh`,
`OOS-EVAL-PROTOCOL.md`, `ops_oos_holdout_eval.py`, `test_oos_holdout_eval.py`,
`ops_cost_hurdle_calibration.py`, or `test_cost_hurdle_calibration.py` (the only files these
three plans modify).

**Root cause:** `_causal_decode` is a backward-compat alias for `_alpha_pass` in
`services/regime_writer.py` (see commit `85b659e0`), but `_alpha_pass` was rewritten
under commit `c4ab422f` (141-P2 JIT wiring) with a different signature (and
`_compute_symbol_tf` now returns a 3-tuple, not 2) than these tests still exercise.

**Affected tests:**
- `tests/unit/test_regime_writer.py::test_causal_decode_vectorized_matches_original`
  (`TypeError: _alpha_pass() takes 3 positional arguments but 5 were given`)
- `tests/unit/services/test_regime_writer.py::test_causal_decode_valid_states`
- `tests/unit/services/test_regime_writer.py::test_causal_decode_no_predict`
- `tests/unit/services/test_regime_writer.py::test_causal_decode_deterministic`
- `tests/unit/services/test_regime_writer.py::test_causal_decode_uses_only_past_observations`
- `tests/unit/services/test_regime_writer.py::test_causal_decode_single_obs`
- `tests/unit/services/test_regime_writer.py::test_compute_symbol_tf_returns_tuple_structure`
  (`ValueError: too many values to unpack (expected 2, got 3)`)
- `tests/unit/services/test_regime_writer.py::test_compute_symbol_tf_regime_values`
- `tests/unit/services/test_regime_writer.py::test_compute_symbol_tf_probabilities_sum_to_one`
- plus 5 more instances of the same root cause in `tests/unit/test_causal_hmm_decoding.py::TestCausalVsViterbi`

**Scope:** Per executor scope-boundary rules, pre-existing failures in unrelated files are
logged here, not fixed.
**Suggested owner:** todo 026 (HMM regime audit / regime_writer JIT follow-up) or a
dedicated test-sweep task on `_alpha_pass` signature and `_compute_symbol_tf` return-shape
changes.

## Full-suite hang: tests/unit/providers/test_ibkr_equity.py (pre-existing, not caused by any Wave 1 plan)

`pytest tests/unit/ -q` (full 5386-test collection) deterministically hangs at
`tests/unit/providers/test_ibkr_equity.py::TestIBKRUseRTH::test_fetch_equity_bars_uses_rth`
(confirmed via verbose run: this is the last test to start before the process stalls
indefinitely; reproduced 3x independently, including with zero sibling agents active).
Confirmed via isolated run: `pytest tests/unit/providers/test_ibkr_equity.py -v` alone
times out after 30s with no output progress past this test. The test mocks `provider._ib`
via `patch.object`, but something inside `provider.fetch_historical_bars` (or a fixture/
import side effect) is not fully isolated from real I/O — likely a retry/backoff loop or
circuit-breaker path not covered by the mock (see CLAUDE.md IBKR gotchas: real IBKR Gateway
lives at `127.0.0.1:7497`, TWS connection attempts can hang without a reachable gateway).

Pre-existing: introduced in commit `c07e1cea` ("feat(ibkr): equity STK qualification +
useRTH=True for historical bars"), well before any Wave 1 plan's base commit `efe64993`.
Not touched by any Wave 1 plan's files.

Confirmed the whole `TestIBKRUseRTH` class is affected, not just one test:
`test_fetch_futures_bars_no_rth` (same class, same mocking pattern) also hangs
indefinitely in isolation (`timeout 20 pytest ...::test_fetch_futures_bars_no_rth`
exceeded a 2-minute outer wrapper without completing).

**Suggested owner:** a dedicated fix task for `tests/unit/providers/test_ibkr_equity.py` —
audit `fetch_historical_bars` for unmocked I/O paths (retry/backoff, circuit breaker) that
`patch.object(provider, "_ib")` does not cover.

## Additional pre-existing failures found via full-suite run (out of scope)

Full run (`pytest tests/unit/ -q --ignore=tests/unit/providers/test_ibkr_equity.py`,
completed in 226.62s): **33 failed, 5309 passed, 41 skipped**. Zero failures in any Wave 1
plan's own new/modified test files. All 33 failures cluster into three pre-existing,
unrelated groups:

1. **Stale module path** — `tests/unit/scripts/test_fetch_htf_bars.py` (3 failures):
   `ModuleNotFoundError: No module named 'scripts.debug.replay.debug_fetch_htf_bars'`.
2. **`production.scripts.run_historical_pipeline` import/patch path broken** —
   `tests/unit/scripts/test_roll_batch.py` (1 failure: hardcoded roll date `ESM6` vs
   actual `ESU6`, a stale fixture date) + `tests/unit/scripts/test_run_historical_pipeline.py`
   (15 failures: `AttributeError: module 'production' has no attribute 'scripts'` —
   `production/scripts/` is not a proper importable package from the patch target's
   perspective, or the module moved to `scripts/infrastructure/backfill/`).
3. **`regime_writer`/`_alpha_pass` signature mismatch** (documented above) — 14 failures
   across `tests/unit/services/test_regime_writer.py`, `tests/unit/test_regime_writer.py`,
   and `tests/unit/test_causal_hmm_decoding.py::TestCausalVsViterbi`.

None of these files were touched by any Wave 1 plan. Logged here per scope-boundary rules;
not fixed.

## Full-suite runtime note (environmental, not a defect)

Running `pytest tests/unit/ -q` (full 5386-test collection) while 2-3 sibling parallel-wave
worktree agents run the identical command concurrently against the same TimescaleDB instance
also causes severe slowdown independent of the ibkr_equity hang above. Isolating the affected
slice (`tests/unit/services/`, 652 tests) and running it standalone completes in 7.3s —
confirming DB/socket contention between concurrent agent processes compounds the hang above.
Verified `services/ic_engine.py` and `tests/unit/test_regime_scope.py` both collect and pass
cleanly in isolation and as part of the `services/`-adjacent slice.
