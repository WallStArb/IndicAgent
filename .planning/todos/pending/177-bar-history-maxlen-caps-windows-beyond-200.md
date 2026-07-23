---
status: pending
priority: P2
filed: 2026-07-23
source: Phase 163 (VP/SR Structural Primitives) code review, CR-02 (163-REVIEW.md) --
  fixed CR-02's specific instance (feature.session_vp.rolling_window, migration 256
  description correction + regression test), this todo tracks the broader systemic gap
  CR-02 surfaced but did not fix
gate: none -- ready to investigate/fix independently
---

# `FeatureVectorPipeline.BarHistory(maxlen=200)` silently caps every live-path feature window below its configured value, for several pre-existing features too

## Context

`services/feature_vector_pipeline.py:126` hardcodes `self._bar_history = BarHistory(maxlen=200)`.
Every live-path feature computation that reads a trailing window from this history is silently
bounded at 200 bars regardless of its own APR-configured window size. Phase 163's code review
(CR-02) found this for `feature.session_vp.rolling_window` (default 480) -- fixed via a
description-only migration (256) correcting the misleading claim that live "genuinely reaches
the full 480-bar window," plus a regression test
(`tests/unit/intelligence/test_volume_profile_primitives.py::test_poc_rolling_dist_atr_live_cap_gap_cr02`)
pinning the gap so it can't silently widen further.

That fix was deliberately scoped to just the one key Phase 163 introduced. CR-02's own review
text flagged that **this is not new** -- several pre-existing `feature.*` windows already exceed
200 and are already silently capped the same way:

- `momentum_zscore_window` (default 252)
- `hurst_window` (default 252, needs verifying against the live default)
- `vix_zscore_window` (default 252)

(these three were named in the review as examples found during CR-02's investigation; a full
sweep of `FeatureFactoryConfig`'s ~90 window fields against `BarHistory`'s 200-bar cap has not
been done)

## What needs to happen

1. Enumerate every `FeatureFactoryConfig` window field whose APR-seeded/default value exceeds
   200, cross-referenced against which of `compute()`'s live-path inputs actually derive from
   `self._bar_history` (some windows may be fed from a different, unbounded source -- verify
   per-field, don't assume).
2. Decide the fix shape for the systemic gap -- two real options (same tradeoff CR-02 named for
   the one-field case):
   - **(a)** Raise `BarHistory`'s maxlen to cover the largest configured window across all
     affected APR keys (or make it config-driven/computed from the live `FeatureFactoryConfig`
     at startup) -- fixes every affected feature at once, but increases live per-symbol/tf memory
     footprint and needs a cost check (58 symbols x 5 tfs x N bars x row size).
   - **(b)** Audit each affected window individually and either lower its default to fit within
     200 (if the larger window wasn't load-bearing) or accept and document the live/backfill skew
     per field (the CR-02 pattern) -- cheaper, no memory impact, but window-by-window and doesn't
     close the gap for future new features that assume unbounded history is available.
3. Whichever shape is chosen, verify IC/feature-quality impact for any field whose *effective*
   live window changes (raising `BarHistory`'s maxlen changes computed values for every affected
   feature, not just fills in missing history) -- this is a live-serving behavior change, not a
   pure bugfix, and should go through the same rigor as any other feature-computation change.

## Acceptance criteria

- [ ] Full list of `FeatureFactoryConfig` window fields whose value exceeds 200, cross-referenced
      against actual `BarHistory`-sourced live inputs
- [ ] Fix shape decided and justified (memory cost for (a) vs per-field skew documentation debt
      for (b))
- [ ] IC impact verified for any field whose live-computed value changes as a result
- [ ] Migration 256's `feature.session_vp.rolling_window` description updated again if this todo
      changes its live-path behavior (currently accurately describes it as capped)
