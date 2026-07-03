# Deferred Items — Phase 142B.1

## Plan 01 — Wave-merge gate (`.venv/bin/pytest tests/unit/ -q`) full-suite failures

**Status:** Out of scope, NOT auto-fixed (scope boundary rule — only auto-fix issues
directly caused by the current task's changes).

Full unit suite run (5414 passed, 33 failed, 41 skipped, 620.59s) on top of Plan 01's
changes. All 33 failures are in modules never touched by this plan's diff
(`services/ensemble_ic_engine.py` + new `tests/unit/test_ensemble_ic_pooled_dispatch.py`
only):

- `tests/unit/scripts/test_fetch_htf_bars.py` (3 failures)
- `tests/unit/scripts/test_roll_batch.py` (1 failure)
- `tests/unit/scripts/test_run_historical_pipeline.py` (16 failures)
- `tests/unit/services/test_regime_writer.py` (8 failures)
- `tests/unit/test_causal_hmm_decoding.py` (5 failures)
- `tests/unit/test_regime_writer.py` (1 failure)

These cluster around HMM causal-decode determinism, historical backfill pipeline, roll
batch, and HTF bar fetching — none of which this plan's Wave 0 (migration 196 + pooled
cross-sectional dispatch) reads, writes, or imports. Confirmed via `git diff --name-only`
against this plan's commits: only `services/ensemble_ic_engine.py` was modified.

Not investigated further per the scope boundary rule. Flagging for a future
todo/investigation rather than fixing here.
