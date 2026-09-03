---
status: pending
priority: P2
filed: 2026-07-30
source: follow-up scrutiny after closing todo 176 (1d VP-at-0% backfill question) -- traced
  the code's stated rationale back against Phase 163's actual design history rather than
  accepting the docstring at face value
---

# Rolling-track VP (`poc_rolling_dist_atr`, `poc_session_rolling_divergence_atr`) is suppressed
# for `tf='1d'` via the same branch as session VP, but D-18's design review never actually
# examined whether the rolling case applies to 1d -- likely dropping real signal, not a
# reviewed exclusion

## Not the same question as todo 176 (closed)

176 asked "is 1d's 0%-populated VP a backfill bug or by design?" -- answered: by design,
`feature_factory.py:6188-6189`/`:6694-6695` explicitly branch `if tf == "1d": vp_extra =
dict(_NEUTRAL_VP_EXTRA)`. That answer is correct and stands.

This todo asks a different question: **is that design decision itself correct for BOTH of the
two mechanisms it suppresses, or does it conflate a well-justified exclusion (session VP) with
an unexamined one (rolling VP)?**

## The two mechanisms are not the same claim

- **Session VP** (`poc_dist_atr`, `va_position`, `nearest_hvn_above_dist_atr`, etc.) is anchored
  to an intraday trading session. D-16's rationale ("a single daily bar has no intraday
  distribution, so session-anchored VP is not meaningful") is airtight here -- there is no
  intraday session inside one 1d bar.
- **Rolling VP** (`poc_rolling_dist_atr`, `poc_session_rolling_divergence_atr`, the D-18
  additions) is a trailing N-bar window (`config.session_vp_rolling_window`, currently 480,
  tf-agnostic), computed identically regardless of what a "bar" represents. For `tf='1d'`, that
  window is just the last ~480 daily bars (~2 years) -- a long-run value anchor, not a
  session concept at all.

D-18 itself (`.planning/milestones/v3.1-phases/163-vp-sr-structural-primitives/163-CONTEXT.md:218-256`) argued
`poc_session_rolling_divergence_atr` has "genuine standalone economic meaning" as "session
dislocation from the multi-day value anchor... an open-drive/trend-day vs. balance-day signal
(first-order auction-market-theory concept)". That argument doesn't stop applying at 1d --
if anything, "today's bar's dislocation from a ~2-year value anchor" is a coherent, arguably
*more* natural read of the same auction-market-theory concept than the 5m/15m/1h version.

## What's actually verified vs assumed

- **Verified:** three independent review passes (D-16, D-17, D-18, one more at D-19) scrutinized
  every VP-family field addition/rejection for collinearity, cost, and scope discipline. None of
  them discuss timeframe-applicability of the rolling track specifically -- confirmed via direct
  grep of `163-CONTEXT.md`, no hits for "1d" + "rolling" anywhere in the phase's design docs.
- **Verified:** the code applies the identical neutral-suppression branch to both mechanisms
  (`compute()` at line 6188, `compute_batch()` at line 6694) -- one `if tf == "1d"` gate covers
  both, no independent gate for rolling vs. session.
- **Verified live:** `feature_vectors` at `tf='1d'` has 0/332,103 non-null for
  `poc_rolling_dist_atr` and `nearest_hvn_above_dist_atr` alike -- both suppressed identically.
- **Not yet verified:** whether computing rolling VP at 1d would actually produce a
  non-degenerate signal (480 daily bars is plenty of data for a volume-histogram, but this
  needs an actual incremental-IC check, not assumed) -- this project's own promotion discipline
  (earn promotion through proof, p<0.05) applies before treating this as settled either way.

## Fix (staged, do not skip the empirical step)

1. Confirm mechanically that `_rolling_poc_price`/`_derive_session_vp`'s two rolling-track
   fields have no structural dependency on intraday session concepts (read `_rolling_poc_price`
   and the two output derivations again with 1d specifically in mind -- likely none, since the
   function only consumes `highs`/`lows`/`closes`/`volumes` arrays, tf-agnostic).
2. If confirmed clean, compute `poc_rolling_dist_atr`/`poc_session_rolling_divergence_atr` for
   `tf='1d'` on a scoped backfill sample (a handful of symbols, full daily history) and check
   for non-degenerate variance -- same bar this project holds every other feature to.
3. If non-degenerate: run this feature pair through the standard incremental-IC bar (D-07's
   methodology, same as every other Phase 163 field) before promoting to production -- do NOT
   just enable it because it's technically computable.
4. If IC is real: separate the `tf == "1d"` branch into two independent gates (session vs.
   rolling) in both `compute()` and `compute_batch()`, land via migration + `--refresh` backfill
   (same mechanism todo 176 already proved out), same discipline as any other structural-column
   addition.
5. If IC is not real or the mechanism turns out to have a structural flaw not yet identified:
   close this todo with that finding recorded -- a legitimate possible outcome, not assumed.

## Secondary, smaller finding (not blocking, note for whoever picks this up)

`config.session_vp_rolling_window` (APR `feature.session_vp.rolling_window`) is a single scalar
(480) applied uniformly across all tfs where rolling VP is computed -- at 5m that's ~40 hours,
at 1h that's ~20 days. If 1d rolling VP is built, its own window value likely needs independent
calibration (a "2-year lookback" read of 480 vs. whatever's appropriate), same gradient-naming
concern this project's CLAUDE.md already flags elsewhere (per-tf scale qualifiers, not one
constant stamped across every tf) -- distinct enough to scope separately once/if this todo's
Step 2 shows the feature is worth building at all.

## References

- `.planning/todos/completed/176-feature-vectors-historical-backfill-new-structural-columns.md`
  -- the backfill-vs-design question this todo is distinct from
- `.planning/milestones/v3.1-phases/163-vp-sr-structural-primitives/163-CONTEXT.md` D-16/D-17/D-18 -- the design
  history this todo traces; D-18 specifically (rolling-track field additions, no tf-scoping
  discussion anywhere in it)
- `src/intelligence/feature_factory.py:6188-6199` (`compute()`), `:6694-6705`
  (`compute_batch()`) -- the shared suppression branch
- `src/intelligence/feature_factory.py:3383-3419` (`_rolling_poc_price`) -- the rolling-track
  mechanism itself, tf-agnostic by construction
