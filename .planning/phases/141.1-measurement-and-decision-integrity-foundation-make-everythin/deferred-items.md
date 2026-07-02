# Deferred Items — Phase 141.1 Plan 01

Out-of-scope discoveries found during execution. Not fixed here per the executor's
scope boundary rule (only auto-fix issues directly caused by the current task's changes).

## Pre-existing HMM causal-decode signature mismatch

**Found during:** Task 3 full-suite verification (`.venv/bin/pytest tests/unit/ -q`)

**Issue:** `_causal_decode()` in `services/regime_writer.py` calls `_alpha_pass()` with 5
positional arguments, but `_alpha_pass()`'s current signature only accepts 3. This is a
`TypeError` at call time, unrelated to any file this plan touches.

**Evidence (reproduced in isolation, not a DB-contention flake):**
```
tests/unit/test_causal_hmm_decoding.py::TestCausalVsViterbi::test_causal_and_viterbi_differ
TypeError: _alpha_pass() takes 3 positional arguments but 5 were given
```

**Affected test files (33 failures total, all pre-existing, zero diff against this plan's commits):**
- `tests/unit/scripts/test_fetch_htf_bars.py` (3 failures)
- `tests/unit/scripts/test_roll_batch.py` (1 failure)
- `tests/unit/scripts/test_run_historical_pipeline.py` (16 failures)
- `tests/unit/services/test_regime_writer.py` (8 failures)
- `tests/unit/test_causal_hmm_decoding.py` (5 failures)
- `tests/unit/test_regime_writer.py` (1 failure)

**Verification this plan's changes are not the cause:** `git diff --stat HEAD~2 HEAD -- <each file above>`
shows zero diff — none of these files were touched by this plan's commits
(`ops_corpus_pipeline_run.sh`, `OOS-EVAL-PROTOCOL.md`, `ops_oos_holdout_eval.py`,
`test_oos_holdout_eval.py`).

**Suggested owner:** whichever phase/plan last touched `services/regime_writer.py`'s
`_alpha_pass`/`_causal_decode` signature (HMM improvement plan, per MEMORY.md
"vectorized: batch (n,K) log_emit precomputed before alpha-pass loop"). Likely a
refactor left `_alpha_pass()`'s signature out of sync with its caller.
