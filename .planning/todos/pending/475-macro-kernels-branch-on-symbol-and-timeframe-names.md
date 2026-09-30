---
status: pending
priority: P3
filed: 2026-09-30
source: plan 186-15 review (altitude, asset_agnostic invariant)
---

# kernels/macro.py branches on symbol names and timeframe names

## What

`kernels/macro.py` holds `SPY`, `TLT`, `CROSS_ASSET_SYMBOLS` (a six-symbol tuple), `is_spy` and
`is_tlt` (the self-regression exclusion in `build_symbol_beta_series`), and `cross_tf.py`'s
`_compute_cross_tf_divergence` branches on `tf == "5m"`, `"1h"`. The `asset_agnostic` invariant says
asset class is data, not a code branch, and CLAUDE.md's ITR rule says claims about what an
instrument is live in `instrument_tags`, never in hardcoded symbol lists.

## Options

1. Keep: the six proxies are a fixed macro basket and the TF pairs are fixed columns.
2. Read the basket and the factor proxies from `instrument_tags` (point in time), and the TF pair
   per divergence column from config.
3. Read them from an APR JSON list (`alpha.macro.*`) and config, without touching the tag registry.

## Recommendation

Option 2 for membership and the self-regression exclusion (a tag such as `factor_proxy:equity`
and `factor_proxy:rate`), and config keys for the TF pairs of `ret_div_*`. It needs the
point-in-time tag read at the builder edge, not inside the kernel, so the kernel stays a pure
function. Bit-identical for the current universe, since the tags equal today's lists.

## Steps

1. Seed the tags (human source) for SPY, TLT, SHY, TIP, HYG, LQD and the two factor roles.
2. Pass membership into the builders as arguments; delete the constants.
3. Move the TF pair of each `ret_div_*` column into `FeatureFactoryConfig` via APR.
