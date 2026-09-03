**Closed 2026-07-20:** `cache.advance_bar(bar.ts, bar.high, bar.low, bar.close, float(bar.volume))` added to `_process_bar_compute` right after `FeatureFactory.compute()`, mirroring `compute_batch()`'s per-bar ordering. Regression test `tests/unit/services/test_feature_vector_pipeline_wk_vwap.py` confirmed the bug pre-fix (asserted `above_wk_vwap` stuck at 0.0) and passes post-fix. Codex peer review caught a real, narrower follow-on gap — `FeatureCache` is never warmed from the historical bars `_seed_bar_history_from_db()` already loads at startup, so `above_wk_vwap`/`hmm_duration` still start cold after every restart — filed as [159](159-feature-cache-advance-bar-not-warmed-from-seeded-history.md), not fixed here (different mechanism, deserves its own test).

# 158 — `above_wk_vwap` permanently frozen at 0.0 in the live path

**Found:** 2026-07-20, incidentally during Phase 163 (VP/SR Structural Primitives) planning —
`gsd-planner` verified the live wiring for `FeatureCache.update_session_vp()`'s call site and
discovered a pre-existing, unrelated bug in the process.

## What's wrong

`FeatureCache.update_wk_vwap()` (`src/intelligence/feature_cache.py:142`) is the mutator that
computes `above_wk_vwap` (1.0 if close > weekly VWAP, else 0.0) — but nothing in the live
pipeline ever calls it. `services/feature_vector_pipeline.py`'s `_process_bar_compute` calls
`FeatureFactory.compute()` directly without a preceding `cache.update_wk_vwap(...)` call.
`compute_batch()` (`feature_factory.py:4248`) DOES call it — so **the batch/backfill path
computes `above_wk_vwap` correctly, but the live path has never updated it since v3's
inception.** `above_wk_vwap` sits at its dataclass default (`0.0`) for every live bar, forever.

This is the same failure shape as todo 153 (VP/SR features stuck at constant defaults) —
except this one has a real live consumer path that's silently wrong, not just an
unmeasured stub. Any live-path logic reading `above_wk_vwap` gets a constant false signal.

## Why this matters

- `above_wk_vwap` is registered in `FEATURE_VECTOR_DOMAIN` (tagged `"calendar"`) and scored by
  `ic_engine` every corpus run — but only the BATCH corpus ever sees real values. If IC
  measurement runs against historical/batch data, the feature looks real; if any live-path
  consumer (dashboard, live scoring) reads it, it's always `0.0`. This is a live/batch
  computation-path divergence, not a "no consumer yet" issue like todo 153 — same failure
  mode CLAUDE.md's DAG invariants exist to catch (compute stages must produce consistent output
  regardless of stage).
- Silent wrong answers are worse than loud crashes (CLAUDE.md design mindset) — this has been
  silently wrong since v3.0 shipped (2026-06-21ish, Phase 137) with no test catching it, because
  unit tests likely exercise `compute()` directly with a pre-populated cache rather than through
  the live pipeline's actual call sequence.

## Fix

Add `cache.update_wk_vwap(...)` (and verify `advance_bar` / any other per-bar cache mutators are
also correctly called) to `services/feature_vector_pipeline.py`'s `_process_bar_compute`, in the
same call sequence Phase 163's `update_session_vp()` mutator is being wired into per its own
plan (163-02-PLAN.md Task 1) — same missing-call-site class of bug, same fix location.

## References

- `src/intelligence/feature_cache.py:142` (`update_wk_vwap()`)
- `services/feature_vector_pipeline.py` (`_process_bar_compute` — missing call)
- `src/intelligence/feature_factory.py:4248` (`compute_batch()` — the one path that gets this right)
- `.planning/milestones/v3.1-phases/163-vp-sr-structural-primitives/163-02-PLAN.md` (where this was discovered,
  and where the equivalent new `update_session_vp()` call site is being added correctly)
