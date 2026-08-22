---
status: pending
priority: P3
filed: 2026-08-21
source: /simplify's reuse-angle review of the causal_rank.py O(n log n) rewrite (todo,
  see completed/ once filed -- Fenwick-tree fix for the shared causal_expanding_rank
  helper)
---

# `services/equity_regime_model.py` still carries its own inline, unfixed O(n^2) causal-rank loop

## What

`causal_rank.py`'s `causal_expanding_rank()` was rewritten 2026-08-21 from an O(n^2)
`list`+`bisect.insort` implementation to an O(n log n) Fenwick-tree implementation (the
old algorithm turned an 8-hour runtime on a 392K-row intraday series, see that commit for
full detail). `breadth_vol.py` and `curve_credit.py` both call the shared helper and get
the fix automatically.

`services/equity_regime_model.py:237-257` (`_compute_vix_pct_rank`) has its own hand-copied
inline version of the *exact same* algorithm -- same NaN guard, same first-value=1.0 special
case, same `(bisect_left+bisect_right)/2/len(window)` tie formula -- that never got migrated
onto the shared `causal_rank.py` helper when it was extracted (todo 092, 2026-07-24). It
still carries the O(n^2) complexity the shared helper just fixed.

## Why this is P3, not P0/P1

`equity_regime_model.py`'s own docstring marks it **DEPRECATED (Phase 144, 2026-07-12)**:
superseded by `services/cross_sectional_regime_model.py`, the generic multi-group dispatcher
that now runs in the corpus pipeline's step-4 slot. This file is retained only as an
emergency single-group rollback path and has had "no functional changes" since that
migration. It is not on the live path today -- confirmed via `ops_corpus_pipeline_run.sh`
step 4 invoking `cross_sectional_regime_model.py`, not this file.

## Fix (if ever picked up)

Replace the inline `sorted_window`/`bisect` loop in `_compute_vix_pct_rank`
(`services/equity_regime_model.py:237-257`) with a call to
`causal_expanding_rank()` from `src.intelligence.regime_signals.causal_rank`, exactly as
`breadth_vol.py` and `curve_credit.py` already do. Drop the now-dead `bisect`/`math.isnan`
imports if unused elsewhere in the file. Needs its own TDD pass against
`tests/unit/services/test_equity_regime_model_causal.py` -- deliberately not done as part
of the causal_rank.py fix itself (different file, different test file, this file's own
"no functional changes" policy since the Phase 144 migration argues for a deliberate,
separately-reviewed change rather than a drive-by).

## Do NOT

Do not "fix while you're in there" as part of any other regime_signals change -- this file
is an emergency rollback path; changing it casually undermines the one property that makes
it useful as a rollback (bit-for-bit unchanged since the migration that deprecated it).
