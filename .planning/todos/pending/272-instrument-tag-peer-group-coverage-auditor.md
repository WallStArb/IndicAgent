# 271: No automated audit for thin/missing instrument_tags peer groups

**Filed:** 2026-08-05
**Source:** altitude review during `/simplify` pass on migration 299 (single-name/basket
sector-orthogonality expansion, 153 -> 211 instruments)

## What

`cross_sectional_regime_model.py` builds its cross-sectional breadth/dispersion peer groups
entirely from `instrument_tags` (`tag_filter` prefix matching), never from
`contract_details->>'sector'`. Every sector/theme gap filled across migrations 296 and 299
tonight (agriculture N=1, GOOGL/META entirely missing from tech, AMT untagged for its real
wireless-carrier-capex relationship, several `fi_*`/`fx_*` peer groups still at N=1) was found
by a human asking "what about X?" in conversation -- not by any query against the schema.

`regime_coverage_auditor.py` (the existing coverage-check service) only checks per-symbol NULL
`feature_vectors.regime` rows. Nothing checks `instrument_tags` peer-group cardinality or
audits sector/theme completeness against a reference taxonomy. `tag_vocabulary`/
`instrument_tags` (migration 220) enforce no minimum-cardinality constraint either.

## Why this matters

A cross-sectional breadth/dispersion computation across a peer group of N=1 is not "weak
signal" -- it's mathematically undefined (nothing to disperse relative to), and
`cross_sectional_regime_model.py` is presumably still emitting output for these groups right
now as noise dressed up as a real signal. Per this project's "silent wrong answers are worse
than loud crashes" principle, this should be a loud, queryable fact, not something that
resurfaces by accident whenever someone happens to ask about a sector in conversation.

Still open even after tonight's two migrations -- confirmed 2026-08-05:
`fi_muni`, `fi_preferred`, `fi_tips`, `fi_credit_hy`, `fx_usd`, `fx_commodity`, `eq_small_cap`,
`convertible` are all still single-ETF peer groups (N=1). These need more bond/FX ETFs, not
more equities -- separate scope from the equity sweep tonight.

## Proposed fix

A `regime_coverage_auditor`-style query (or an extension to the existing service) that:
1. Flags any `tag_filter` group (per `cross_sectional_regime_model.py`'s own group
   definitions) with peer count below a floor -- 8-10 single names was the working estimate
   established in conversation tonight (1/sqrt(N) diminishing-returns reasoning, same style of
   justification as the existing 20,000-raw-bars IC Sharpe gate), lower for basket-ETF-only
   groups where N>=2 may be adequate.
2. Optionally, a periodic sector-completeness check against a reference taxonomy (e.g. GICS
   sector list) to catch full-sector omissions like GOOGL/META before a human happens to
   notice.

Not scoped/estimated yet -- this todo exists to capture the gap, not to prescribe the
implementation.
