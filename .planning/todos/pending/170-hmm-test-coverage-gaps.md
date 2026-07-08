# 170 — HMM regime-writer test coverage gaps

Source: council-style rigor review during Phase 142B EIC-04 remediation (2026-07-08), triggered
by discovering `tests/unit/ -q` had 34 silent failures in `regime_writer`/causal-decode tests
for 9+ days (since commit `85b659e0`, 2026-06-29) — a name-only backward-compat alias
(`_causal_decode = _alpha_pass`) preserved the import but not the call signature, so every test
still using the pre-refactor 5-arg form (`obs, means, covars, transmat, n_components`) TypeError'd
before the assertion ever ran. Fixed same session (adapter helper in both test files, `git log`
confirms root cause + timeline). Two residual gaps found during that investigation, not yet
addressed:

1. **`_check_occupation_gate` (P2b degenerate-model guard) has zero dedicated unit test.**
   `test_compute_symbol_tf_*` tests were tripping it accidentally (synthetic ranging-price
   fixture produces one HMM state at 2.9% occupation, below the 5% floor) and got patched with
   `min_state_occupation=0.0` to bypass it for those structural tests — correct for what those
   tests verify, but leaves the gate itself unverified: no test confirms it correctly skips a
   genuinely degenerate fit, or correctly passes a healthy one at the boundary.
2. **`test_feature_factory.py::test_no_smooth_or_backward_in_factory`** is a blunt grep for
   `_smooth|smoothed|backward` in `feature_factory.py`, intended to catch look-ahead bias. It
   currently false-positives on `_rolling_mean_series` (Phase 142.5's Parkinson/Garman-Klass
   volatility estimators) — confirmed causal (trailing window, `eff_w = min(window, i+1)`,
   strictly backward-looking in *index* terms only) but uses the English word "smoothed" in
   variable names/docstrings. The check conflates "noise-reduced via causal averaging" with
   "non-causal/backward-looking" — not currently failing (not touched this session), but the
   next legitimate causal smoother added to that file will trip the same false positive. Worth
   tightening the check (e.g. flag `center=True`, non-monotonic windowing, or actual future-index
   reads) rather than the literal string "smooth".

Neither blocks Phase 142B or any live pipeline — both are test-quality/coverage gaps on
already-correct production code. Low urgency, but the occupation gate in particular guards a
load-bearing data-integrity property (rejecting degenerate regime fits before they're written)
and deserves real coverage rather than incidental exercise.
