---
status: pending
priority: P3
found_during: phase-151-post-execution-simplify
found_date: 2026-08-05
updated: 2026-08-05
---

# equity_beta_z/rate_beta_z are allocated on FeatureCache but never computed on the live path

## Update 2026-08-05 (code review WR-03 fixed the fake-zero part, wiring gap remains)

Code review (151-REVIEW.md WR-03) caught the sharpest edge of this: the live default was
`0.0`, not `None`, fabricating a fake "zero beta" indistinguishable from a genuine
measurement -- a direct violation of `FeatureVector`'s own "None means not measured"
contract, which every sibling cross-asset field correctly honors. **Fixed**: `FeatureCache.
equity_beta_z`/`rate_beta_z` now default to `None` (`src/intelligence/feature_cache.py`),
so an unwired live row now honestly reads NULL instead of a fabricated 0.0. The wiring gap
itself (no live computation exists at all) is UNCHANGED and still needs the work below --
this update only closes the "silent wrong answer" half of the problem, not the "feature
doesn't work live yet" half.

## What

Confirmed by an altitude-review /simplify agent, corroborated by direct grep: Phase 151 Plan 04
added `equity_beta_z`/`rate_beta_z` fields plus two dedicated deques
(`_equity_beta_history`, `_rate_beta_history`) to `FeatureCache`
(`src/intelligence/feature_cache.py:80-81`), but nothing in the live pipeline
(`services/feature_vector_pipeline.py`) ever writes to them:

```
grep -rn "equity_beta_history\|rate_beta_history" services/ src/ --include="*.py"
# zero hits outside the declaration in feature_cache.py
```

The live `compute()` path reads `cache.equity_beta_z`/`cache.rate_beta_z`, which (as of the
2026-08-05 fix above) now correctly stay `None` rather than a fabricated `0.0` on any
live-serving row -- but still carry no real live-computed value at all.

## Context

Plan 09 (same phase, merged after Plan 04) DID wire the 5 symbol-independent cross-asset
fields (`tip_tlt_ret_z`, `hyg_lqd_ret_z`, `sb_corr_fast/slow/z`) onto a shared live/batch
builder (`build_cross_asset_series()`), closing an analogous gap for those fields. Plan 09's
own SUMMARY explicitly scoped `equity_beta_z`/`rate_beta_z` OUT ("per-symbol, out of scope per
151-04's own key-decisions") since they're per-symbol (not symbol-independent broadcast
values) and a live per-symbol beta series for ~80-111 symbols is a different, larger scope
question than the 5 broadcast fields Plan 09 did fix.

Todo 261 (P1, filed by Plan 09) tracks deploying the grain-corrected broadcast-field mechanism
once IBKR ingestion resumes -- it does NOT mention the beta gap. This todo exists so the gap
doesn't fall through the cracks between the two.

## Impact

Batch/corpus path is unaffected -- `services/backfill_feature_factory.py`'s
`build_symbol_beta_series()` computes real values for the training corpus; this gap is
live-daemon-only. Currently low urgency since live IBKR ingestion has been intentionally
stopped since 2026-07-27 (no live-serving consumer exists to be affected right now), same
underlying operational context as todo 261.

## What needs to happen

Either:
1. Design and wire a live per-symbol equity/rate beta computation (harder than the 5
   broadcast fields -- needs a rolling OLS slope per symbol against SPY/TLT daily returns,
   maintained per-symbol rather than per-tf), or
2. Explicitly decide these two fields stay batch-only indefinitely and document that as a
   permanent, intentional live/batch asymmetry (not silently-forgotten scope) -- update
   FeatureCache's docstring/comments to say so plainly rather than leaving unused deques with
   no live writer.

## References

- `src/intelligence/feature_cache.py:80-81` -- the dead deque fields
- `.planning/milestones/v3.1-phases/151-feature-primitives-expansion-theory-motivated-interaction-la/151-04-SUMMARY.md` -- original field addition
- `.planning/milestones/v3.1-phases/151-feature-primitives-expansion-theory-motivated-interaction-la/151-09-SUMMARY.md` -- the analogous fix for the other 5 fields, explicit scope boundary for these 2
- `.planning/todos/pending/261-deploy-grain-corrected-cross-asset-mechanism-once-ingestion-resumes.md` -- sibling deployment todo, does not cover this gap
