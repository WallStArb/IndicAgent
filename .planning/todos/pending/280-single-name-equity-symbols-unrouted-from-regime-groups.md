---
status: pending
priority: P2
filed: 2026-08-08
source: found while running the Phase 171 candidate-regime-axes identifiability sweep
  (`171-CANDIDATE-REGIME-AXES-FINDINGS.md` §5.5) -- the sweep resolves each test symbol's
  regime_group through ic_engine._build_symbol_regime_class and 5 of its 17 symbols came
  back unrouted.
---

# `single_name_equity`-tagged symbols match no enabled `alpha.regime.groups` filter and are silently excluded from all regime-stratified IC

## What

`_build_symbol_regime_class` (`services/ic_engine.py`) routes a symbol to a regime_group
by prefix-matching its `instrument_tags` against each enabled group's `tag_filter` in the
`alpha.regime.groups` APR config. The equity group's filter is `["eq_*", "intl_*"]`.

AAPL, MSFT, GOOGL, AMZN and JPM carry `single_name_equity` as their only group-relevant
tag. That string does not start with `eq_` (or `intl_`, `fi_`, `fx_`, `commodity_*`), so
none of them matches any enabled group and all five are omitted from the routing dict.

Verified against the live config and `instrument_tags`:

```
AAPL  | single_name_equity,mid_cycle
AMZN  | single_name_equity
GOOGL | single_name_equity,mid_cycle
JPM   | single_name_equity,early_cycle
MSFT  | single_name_equity
```

## Why it matters

Omitted symbols get no regime_group and are therefore excluded from the regime-stratified
IC cut entirely. The pooled IC pass still covers them, so **no data is dropped** -- but a
whole instrument class receives no regime-conditional measurement. This is the documented,
intentional behaviour of `_build_symbol_regime_class` (explicit gap over silent
mislabeling, with the caller logging unrouted symbols loudly), so it is not a bug in that
function. The question is whether the *tag data / group config* was meant to leave single
names out.

The universe recently expanded 111 -> 231 instruments. Five unrouted symbols were visible
in a 17-symbol sample; the true unrouted set across 231 is probably much larger and has
never been audited.

## What to do

1. Run `_build_symbol_regime_class` over the full active universe and count/list unrouted
   symbols by tag. (Cheap -- the sweep script already does this for its own scope.)
2. Decide per class whether to extend an existing `tag_filter` (e.g. add
   `single_name_equity` to the equity group) or add a group. Note the mutual-exclusivity
   invariant: enabled groups' tag_filters must not both match a symbol, or
   `AmbiguousRegimeGroupError` is raised.
3. Check whether the caller's `ic_engine.unrouted_symbols` warning is actually being read
   -- if it has been firing on dozens of symbols unnoticed, the log alone is not doing its
   job.

Related: todo 272 (instrument-tag peer-group coverage auditor) covers adjacent ground and
these two may want to merge.

**2026-08-08 addendum:** todo 283 ran this exact check (step 1 above) scoped to the 151 symbols
added in the 2026-08-05/06 universe expansion and found **115/151 (76%) unrouted** — the same
failure mode at roughly 20x this todo's 5/17 sample. Merge scope with 283 before fixing either;
283 also flags this todo's PRIORITIES.md placement (filed P3 there despite this file's own P2
frontmatter) and suggests P1 given the new scale evidence.
