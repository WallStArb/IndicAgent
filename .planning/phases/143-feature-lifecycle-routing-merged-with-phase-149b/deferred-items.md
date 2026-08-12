# Deferred Items — Phase 143

Items discovered during plan execution that are out of scope for the current task
(SCOPE BOUNDARY rule) — logged here rather than fixed inline.

## From Plan 02 (feature_registry lifecycle routing)

- **`tests/unit/test_feature_factory.py::TestRegimePrimitives::test_no_smooth_or_backward_in_factory`**
  fails on the full `tests/unit/` suite run. Confirmed pre-existing and unrelated to this plan's
  changes: `test_feature_factory.py` is byte-identical to its state at commit `37a52320` (the
  commit immediately prior to Plan 02's first commit) — verified via `git show 37a52320:... | diff`.
  Neither `feature_registry_service.py` nor either new migration is imported or referenced by this
  test file. Not fixed here per SCOPE BOUNDARY (out-of-scope for LIFECYCLE-01).
- **`test_causal_decode_vectorized_matches_original`** (regime_writer) — pre-existing TypeError in
  `_alpha_pass()` signature, unrelated to this plan. Already logged by Plan 01's summary
  (143-01-SUMMARY.md line 90); Plan 01's own `deferred-items.md` write appears not to have landed
  on `main` (file did not exist in this worktree until now) — re-noted here for continuity since
  this phase directory previously had no `deferred-items.md` on disk.
