# Deferred Items — Phase 143 Plan 01

## Pre-existing test failure (out of scope, not touched by this plan)

- `tests/unit/test_regime_writer.py::test_causal_decode_vectorized_matches_original` fails
  with `TypeError: _alpha_pass() takes 3 positional arguments but 5 were given`. Confirmed via
  `git stash` that this failure pre-dates this plan's changes (fails identically on the
  pre-plan state of `services/regime_writer.py`). The test calls `_causal_decode(obs, means,
  variances, A, K)` (5 args) but `_causal_decode` is now a backward-compat alias for
  `_alpha_pass(log_emit, A, pi0)` (3 args, different signature: expects precomputed log
  emissions, not raw obs+means+variances). Likely stale from a prior refactor (the
  `_log_emit_diag`/`_log_emit_full` split). Not fixed here per SCOPE BOUNDARY (unrelated to
  P2b/P2c). Needs a todo.
