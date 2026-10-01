---
status: pending
priority: P2
filed: 2026-10-01
source: interactive session, check of the curve_credit signal against stored FRED series
---

# Rates regime "curve" label tracks the 10-year yield change, not the curve slope, and its sign is inverted

## What

`src/intelligence/regime_signals/curve_credit.py` builds the curve tier from the TLT minus SHY
log-return spread and names the high end "steep" ("long-end outperforms, curve steepening / rates
falling"). Measured 2026-10-01 against `economic_series_observation` (DGS10, DGS2, T10Y2Y) on 2,275
common days, 2017-08 to 2026-09:

| Measure | Daily | 21-day |
|---|---|---|
| corr(TLT-SHY spread, change in 10-year yield) | -0.87 | -0.92 |
| corr(TLT-SHY spread, change in 2-year yield) | -0.49 | -0.60 |
| corr(TLT-SHY spread, change in 10s2s slope) | -0.53 | -0.44 |
| R2 of spread on 10-year change alone | 0.76 | 0.84 |
| R2 adding slope change | 0.84 | 0.91 |

So the spread mostly measures the direction of the long yield (TLT duration is about 17 against
about 2 for SHY), and what it says about slope has the opposite sign to the label: when long bonds
outperform short bonds the long yield fell more, so the 10s2s slope fell (a flattening), yet that
end is labeled "steep". Prices here are price-only (no carry), which does not change the sign.

## Options

1. Keep, rename the tiers to what is measured (a long-end rate-direction axis).
2. Replace the curve input with the measured slope (`T10Y2Y`, or a 10-year minus 3-month term
   spread) read as-of from `economic_series_observation`, keeping the steep/flat/inverted names.
3. Do both: a rate-direction axis from the bars and a slope axis from the series, two labels.

## Recommendation

Option 2 for the curve tier (the names then mean what they say), and keep the credit tier's
HYG-LQD return spread until credit spreads are compared the same way (HY OAS is only 3 years deep;
`BAA10Y` is long). Either way every `rates` label changes: it needs the full `market_regimes`
recompute the module's calibration note describes, so schedule it with the 186 regime rebuild, not
before. Any new label set is a regime candidate and must clear the scrambled-data null-arm
control before IC stratification uses it (ledger: regime-conditioned use is a poor prior).

## Related

- Todo 480 (the stored series this check used).
- `market_regimes` `rates` group last written 2026-08-11 (live path down), so nothing downstream
  currently moves with these labels.
