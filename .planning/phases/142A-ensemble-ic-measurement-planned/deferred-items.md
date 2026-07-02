# Deferred Items — Phase 142A Plan 01

Out-of-scope discoveries logged during execution of 142A-01-PLAN.md. Not fixed
(scope boundary: only auto-fix issues directly caused by the current task's changes).

## Pre-existing HMM causal-decode test failures (33 tests)

**Discovered during:** Task 2 full unit-suite verification (`pytest tests/unit/ -q`).

**Files affected (none touched by this plan):**
- `tests/unit/scripts/test_fetch_htf_bars.py` (3 failures)
- `tests/unit/scripts/test_roll_batch.py` (1 failure)
- `tests/unit/scripts/test_run_historical_pipeline.py` (14 failures)
- `tests/unit/services/test_regime_writer.py` (8 failures)
- `tests/unit/test_causal_hmm_decoding.py` (6 failures)
- `tests/unit/test_regime_writer.py` (1 failure)

**Verification these are pre-existing, not caused by this plan:**
`git diff --stat 8cd562f6 HEAD -- tests/unit/scripts/ tests/unit/services/test_regime_writer.py tests/unit/test_causal_hmm_decoding.py tests/unit/test_regime_writer.py services/regime_writer.py`
returns empty — zero lines changed in any of these test files or `services/regime_writer.py`
by 142A-01's commits. The failures exist independent of this plan's work.

**Suspected cause:** HMM causal-decode numeric/JIT precision drift (test names reference
`causal_decode_vectorized_matches_original`, `causal_pre_switch_bars_consistent`,
`causal_is_truly_causal`) — likely an environment-level numeric or Numba JIT precision
issue unrelated to Phase 142A's ensemble IC measurement work.

**Action:** Not fixed (out of scope for 142A-01 per CLAUDE.md scope boundary — these
failures are in `regime_writer.py`/HMM causal decoding, not `ensemble_ic_engine.py`,
migration 195, or `service_auditor.py`). Flagging for separate investigation; not
blocking 142A-01 or 142A-02.

**All 6 new Phase 142A test files (`test_ensemble_ic_*.py`) pass cleanly**, and the
overall suite result is 33 failed / 5378 passed / 41 skipped — the 33 pre-existing
failures are isolated to the HMM/regime-writer causal decode surface.
