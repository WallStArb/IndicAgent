---
title: Investigate 33 pre-existing HMM causal-decode / regime-writer test failures
status: pending
discovered_by: phase-142A (142A-01 execution)
discovered: 2026-07-02
---

## What

33 test failures discovered running the full `tests/unit/` suite during Phase 142A
execution (post-merge gate, confirmed reproducible twice — identical failure set
before and after merging plan 142A-01). Confirmed via `git diff --stat` against
these files that none were touched by 142A-01's commits — pre-existing on `main`
at `8cd562f6`, not caused by any recent phase.

Full breakdown logged in
`.planning/phases/142A-ensemble-ic-measurement-planned/deferred-items.md`.

**Affected files:**
- `tests/unit/scripts/test_fetch_htf_bars.py` (3 failures)
- `tests/unit/scripts/test_roll_batch.py` (1 failure)
- `tests/unit/scripts/test_run_historical_pipeline.py` (14 failures)
- `tests/unit/services/test_regime_writer.py` (8 failures)
- `tests/unit/test_causal_hmm_decoding.py` (6 failures)
- `tests/unit/test_regime_writer.py` (1 failure)

**Suspected cause:** HMM causal-decode numeric/JIT precision drift — test names
reference `causal_decode_vectorized_matches_original`, `causal_pre_switch_bars_consistent`,
`causal_is_truly_causal`. Likely an environment-level numeric or Numba JIT precision
issue in `regime_writer.py`'s causal decode path, not a logic regression from any
specific phase.

## Why it matters

`regime_writer.py` feeds the per-symbol HMM regime labels (`feature_vectors.regime`)
used as one of two live regime systems (see MEMORY.md Dual Regime System). If the
causal decode path is numerically drifting, downstream regime-stratified IC
measurements (including Phase 142A's ensemble IC engine) could be silently
consuming degraded regime labels in production, even though this specific test
suite run isn't blocking on it.

## Suggested approach

- Bisect when these started failing (`git log -- services/regime_writer.py` +
  rerun suite at a few historical commits) to rule in/out a recent numpy/numba/
  scipy dependency bump vs. a long-standing environment issue.
- Compare local vs CI test environment (numba JIT caching, BLAS backend) if the
  failures are non-deterministic across machines.
