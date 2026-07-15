# 086 — HMM regime-writer test coverage gaps

**Resolved 2026-07-14 (corpus-rebuild idle window).** Both gaps closed:

1. **`_check_occupation_gate` dedicated test** — already existed by the time this was checked
   (`tests/unit/test_regime_writer_occupation_gate.py`, added by commit `45bb73c6` during Phase
   143.1, after this todo was filed). 7 tests: degenerate-fit flagged, healthy-fit not flagged,
   exact-floor-boundary case (0.05 == floor → healthy; one bar below → degenerate),
   empty/single-bar/non-converged all flagged without divide-by-zero or IndexError, and a
   uniform-shape check across every skip reason. Nothing left to do here.
2. **`test_no_smooth_or_backward_in_factory` false-positive** — fixed. Replaced the blunt
   `_smooth|smoothed|backward` grep with a check for the word "backward" alone (a much stronger
   signal — production code has no legitimate reason to describe itself as backward-looking,
   whereas "smoothed" legitimately describes causal noise reduction too), with the one
   deliberate, documented exception (`_canary_acausal_placebo`, a positive-control canary
   proving the IC significance gate detects real contamination) excluded by stripping its own
   function body structurally, not by a line-number allowlist. Added 3 synthetic tests proving
   the exclusion logic itself: a causal-smoothing docstring doesn't trip it, the canary's own
   "backward-shifted" reference is correctly excluded, and a genuine new violation elsewhere in
   the file is still caught — closing the "tightening a check could silently make it vacuous"
   risk. `tests/unit/test_feature_factory.py` now 63/63 green (was 60 passed + 1 known failure).

Source (original problem, for context): council-style rigor review during Phase 142B EIC-04
remediation (2026-07-08), triggered by discovering `tests/unit/ -q` had 34 silent failures in
`regime_writer`/causal-decode tests for 9+ days (since commit `85b659e0`, 2026-06-29) — a
name-only backward-compat alias (`_causal_decode = _alpha_pass`) preserved the import but not
the call signature, so every test still using the pre-refactor 5-arg form TypeError'd before the
assertion ever ran. Fixed same session; these were the two residual gaps found during that
investigation.
