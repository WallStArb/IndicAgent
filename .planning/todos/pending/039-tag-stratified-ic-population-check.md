# Population-count check before adding tag-stratified cross-sectional IC

**Found:** 2026-07-01, during design review of the cross-sectional regime model plan
(`docs/plans/2026-07-01-cross-sectional-regime-model.md`).

## Context

`regime_group` (single-membership, one signal per group — equity/rates/commodity/fx/...)
answers "what peer set shares a causal regime driver." `instrument_tags` (many-to-many,
already supports weighted multi-membership — e.g. SDOG carries both `defensive_yield` and
`benchmark`) answers "what characteristics does this symbol have." These are two different
questions and must stay on two different mechanisms — see the routing-invariant fix applied
directly to the plan doc (`AmbiguousRegimeGroupError`, `_build_symbol_regime_class` now fails
loud on tag_filter overlap instead of silently picking first-match-by-array-order).

The natural next ask — "what's the IC of feature X restricted to just the high-yield subset
of the equity group" — requires a second, additive filter dimension on top of `regime_group`
in `ic_engine`'s cross-sectional pass (query-time slice by `instrument_tags`, not a new
regime_group). That mechanism does not exist yet and should not be built speculatively.

## Renaissance-grade reasoning

Before writing any query-time tag-filter code: check whether any tag intersection actually
has enough symbols/bars to produce a usable IC estimate. This codebase already enforces a
sample-size bar everywhere else that promotes a statistic to something acted on —
`shadow_registry` promotion requires `n >= 100 AND bootstrap_ci_lower(pnl_r) > 0.0`; IC
Sharpe gating requires 20,000 raw bars minimum. Slicing IC by an intersection like
"equity ∩ defensive_yield" with 2-3 tickers would silently produce IC numbers that look real
but are noise — a false-discovery machine, not a new feature. Building the general-purpose
filter mechanism before checking this is optimizing a capability nobody has shown has enough
data to use (5-step mandate: delete/simplify before accelerate/automate).

## Action

1. Run population counts per `(instrument_tags.tag, regime_group)` intersection against the
   current 79-ETF universe: `SELECT tag, COUNT(DISTINCT symbol) FROM instrument_tags GROUP BY tag
   ORDER BY 2 DESC;` cross-referenced against which regime_group each tagged symbol falls into.
2. For any intersection with sufficient N (apply the same bar used elsewhere — n >= 100
   bar-level observations per stratification cell, not just symbol count, since IC is computed
   per-bar not per-symbol; check actual `feature_ic_scores` row-count feasibility at the
   relevant TFs), it's a candidate for tag-stratified IC.
3. Only if at least one candidate clears that bar, add the query-time tag filter to
   `ic_engine.py`'s cross-sectional pass (`_compute_cross_sectional_tf` gains an optional
   `tag_filter` param restricting the peer set further within a `regime_group`) as a
   follow-on to migration 187 (`regime_group` rename), not before it.
4. If no intersection clears the bar today, leave a note in this todo and defer — re-check
   after the ETF universe expansion (58 → 79) lands, since it may create more tag density.

**Blocked on:** `regime_group` (migration 187) shipping first — this stratifies within groups
that don't exist as a queryable column yet.
