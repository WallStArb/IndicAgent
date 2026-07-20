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

**Gate cleared, checked live 2026-07-19:** `regime_group` shipped as **migration 222**, not 187
(the number in this todo was always wrong — 187 is a different migration; `alpha.regime.groups`
config confirms `equity` (tag_filter `eq_*`/`intl_*`) and `rates` (`fi_*`) are the only enabled
groups). The column exists and is queryable.

**Population-count check run 2026-07-19 (Action items 1-2, done):**

| Tag (within enabled equity/rates groups) | N symbols | Bar count (1d / 1h / 15m / 5m) |
|---|---|---|
| `eq_sub_sector` | 13 | 54K / 392K / 1.4M / 4.2M |
| `eq_sector` | 11 | 47K / 339K / 1.3M / 3.9M |
| `intl_em` | 7 | 27K / 179K / 748K / 2.2M |
| `intl_developed` | 6 | 29K / 179K / 778K / 2.3M |
| `fi_treasury` | 6 | 20K / 133K / 534K / 1.5M |
| 14 other eq_*/fi_* tags | 1-2 | not queried — symbol count alone disqualifies |

**Finding: the bar-count criterion as originally written is not the real gate — it's trivially
satisfied everywhere** (tens of thousands to millions of bars per cell even at the 5-symbol
`eq_broad` tag). The binding constraint is **symbol-level breadth** (statistical independence of
the cross-section), which this todo's Action item 2 conflated with bar count. That's the same
question todo 029's "Effective-breadth consistency" row is about (N_eff from the correlation
matrix, not raw symbol count) — don't re-derive it here, cross-reference instead.

**Revised recommendation:** the 5 tags with 6-13 symbols (`eq_sub_sector`, `eq_sector`,
`intl_em`, `intl_developed`, `fi_treasury`) are plausible tag-stratified-IC candidates on symbol
count alone; building the query-time `tag_filter` mechanism in `ic_engine.py` is justified **for
this short tag allowlist**, not as a fully general filter over all 68 tags — the 14 tags with
1-2 symbols should be explicitly excluded (a 1-2 name "cross-section" isn't a rank correlation,
it's a coin flip), and any tag outside the enabled equity/rates groups (commodity/fx tags) is out
of scope until those regime groups are enabled. Still gated on running 029's effective-breadth
metric on at least the 3 largest of these 5 before trusting the resulting IC as real rather than
lucky — sequence after 029, not before.
