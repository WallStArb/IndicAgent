---
status: completed
priority: P2
filed: 2026-07-24
closed: 2026-07-24
source: ad hoc brainstorm session surveying all 135 live `tier=0_atomic` feature_registry rows
  to find genuinely non-overlapping OHLCV-only candidates before deciding the Phase 164/165
  ("invest in theory-laden features") vs. accept-no-edge strategic fork
---

**Closed 2026-07-24, same day it was filed — content fully captured in `/gsd-plan-phase 151`.**
All 11 candidates (7 original + naming fixes) are built in `151-03-PLAN.md` (Wave 2).
Remaining work (build + IC screen) tracked under Phase 151, not this todo.

# 4 new atomic primitive candidates for Phase 151 (event-recency, volatility clustering, rolling beta)

## Finding

Surveyed the full live `feature_registry` `tier=0_atomic` set (135 rows across calendar,
control, macro, momentum, oscillator, regime, structure, volatility, volume groups) looking for
real gaps before considering whether new theory-laden feature families (Phase 164/165) are
actually needed. Phase 151's current atomic-expansion scope is narrow — just todo 104's 3
calendar candidates (`quarter_cycle_sin/cos`, `tdom_sin/cos`, `minute_of_hour_sin/cos`), todo
066's cross-TF divergence, and todo 123's momentum-velocity/macro-spread trio. Found 4 more,
all pure OHLCV, all theory-free (deterministic statistical properties, no assumption that any
price level or pattern "means" something):

1. **`bars_since_high_fast/slow`, `bars_since_low_fast/slow`** — bars elapsed since the rolling
   N-bar high/low was last set. `dist_from_high_fast/slow` already covers the *magnitude* of
   distance from a rolling extreme; nothing covers *recency*. Genuinely new axis — a pure path
   statistic (time-since-event), same class as `streak_z` (signed streak length) but for a
   different event type.

2. **`abs_ret_autocorr_1`** (volatility clustering) — autocorrelation of `|return_t|` with
   `|return_t-1|`. `ret_autocorr_1` already exists but is computed on *signed* returns
   (captures momentum/mean-reversion); nothing measures autocorrelation of return *magnitude*
   (the "big moves cluster with big moves" stylized fact, distinct statistical property).

3. **`equity_beta_z`** (rolling regression beta vs. SPY, z-scored — renamed from `mkt_beta_z`,
   see Fable review below) — closes a real, already-named gap: the glossary's own canonical
   primitive examples (`docs/foundation/glossary.md:320`) are `equity_beta`/`rate_beta`, but
   neither is implemented as a live per-bar `FeatureVector` column — they only exist as
   slow-moving static tags in the separate tag-vocabulary system (`instrument_tags`). A rolling
   beta is a pure statistical measurement (covariance/variance ratio), same class as
   `hurst_exponent`. No new data needed — SPY OHLCV is already in `market_data_ohlcv_tradeable`.

4. **`bars_since_extreme_move_fast/slow`** — bars since `|return|` last exceeded a 2σ (or
   APR-configured) threshold. Distinct from #1: that's about price *level* extremes, this is
   about return-*magnitude* shocks (volatility event recency, not price event recency).

## Fable review (2026-07-24, same day, same pattern as todo 104)

Dispatched a Fable-model review before this goes to Phase 151 planning — same stress-test
todo 104 applied to `is_opex_day`/`opex_flag` (checking for smuggled theory, redundancy,
statistical-power pathologies). Verdict, per candidate:

1. **`bars_since_high/low_fast/slow` — KEEP.** Genuinely non-redundant with
   `dist_from_high_fast/slow` (recency vs. magnitude), no theory smuggled. **Design flag:**
   must be a bounded rolling-window statistic (`[0, N-1]`), not an expanding lookback — confirm
   at implementation. Distribution will be right-skewed (mass near 0); IC-screen via
   rank-transform, not naive z-score.
2. **`abs_ret_autocorr_1` — KEEP, no changes.** Cleanly distinct from `ret_autocorr_1` (magnitude
   vs. sign) and from `vol_of_vol`/`variance_ratio_fast/slow` (different statistics entirely).
3. **`mkt_beta_z` — REFRAME (naming only), not reject.** The metric itself is theory-free (an
   OLS slope is a raw transform, same standing as `hurst_exponent`) — but the *name* hits an
   explicit glossary ban: unqualified `beta` is disallowed; every beta must name its factor
   (`equity_beta`/`rate_beta`/`gold_beta`, glossary.md `beta` entry). **Renamed to
   `equity_beta_z`** (SPY as the stated equity-factor proxy) — this is also literally the
   primitive the glossary has been citing as a canonical example without a live column.
   **Implementation edge case:** regressing SPY against itself is degenerate (beta≡1, r²≡1) —
   needs an explicit null/special-case for the SPY row itself, not a silently-emitted constant.
4. **`bars_since_extreme_move_fast/slow` — KEEP, with an APR flag.** Distinct axis from #1
   (return-magnitude shock vs. price-level event). The "2σ" cutoff is a hardcoded threshold
   under the APR mandate — must ship as `feature.bars_since_extreme_move.sigma_threshold`
   (default 2.0, `[conventional]`), not a code literal. Same boundedness/skew caveat as #1.

**Redundancy check:** no exact duplicates or affine transforms found against the 135 live rows
(unlike `days_to_month_end`/`month_position`).

**2 additional candidates surfaced by the review** (same OHLCV-only, theory-free pattern):
5. **`bars_since_52w_high/low`** — recency complement to the existing `high_52w_dist`
   (magnitude-only today), same relationship as #1 has to `dist_from_high_fast/slow` at a
   longer horizon. Directly motivated by an existing sibling feature.
6. **`bars_since_vol_spike_fast/slow`** — event-recency in the volume domain (threshold on
   `rel_volume`/`dollar_vol_z`, also APR-backed). The volume group has 20+ magnitude/ratio
   features and zero recency features — same structural gap #1/#4 close for price/return,
   unaddressed for volume. **Naming-audit addendum (2026-07-24):** the Fable review flagged
   `bars_since_extreme_move`'s 2σ cutoff needing an APR key
   (`feature.bars_since_extreme_move.sigma_threshold`) but missed that `vol_spike` has the
   identical hardcoded-threshold problem — needs its own APR key
   (`feature.bars_since_vol_spike.threshold`, namespace/default TBD at implementation), not a
   code literal, same requirement as #4.

## Naming-compliance audit (2026-07-24, same day): a 7th candidate found

Checked all 6 candidates above against `docs/foundation/naming-system.md` §7 (gradient
vocabulary, numeric-embedding rule). All pass: `fast`/`slow` are approved gradient terms
consistent with sibling `dist_from_high_fast/slow`; `abs_ret_autocorr_1`'s `1` and
`bars_since_52w_high/low`'s `52w` both define the statistic itself (matching live
`ret_autocorr_1`/`ret_autocorr_5` and `high_52w_dist` precedent), not tunable calibration —
allowed per §7.

**Real gap found auditing `equity_beta_z` specifically:** the glossary's own `beta` entry names
THREE factor-specific betas as its canonical examples — `equity_beta`, `rate_beta`, `gold_beta`
— not one universal "beta." A single `equity_beta_z` (vs. SPY) computed identically across
every instrument, including `rates`/`commodity`/`fx`-tagged ones, is still informative on its
own (cross-asset equity-correlation signal), but is only half of what the convention implies —
same one-size-fits-all pattern todo 179 already caught once this session (equity-only regime
labels force-fit onto commodity/FX-tagged symbols XLE/XOP/PPLT).

7. **`rate_beta_z`** (rolling regression beta vs. TLT or a yield-curve factor, z-scored) — the
   natural pairing with `equity_beta_z`, since `equity`/`rates` are the only two currently
   *enabled* `cross_sectional_regime_model.py` groups (see
   [[project_todo092_breadth_regime_causal_rank_fix]]). `gold_beta_z`/commodity/FX-factor betas
   would pair with `commodity_momentum_ts`/`fx_dollar_carry`, which are disabled with zero live
   data — same reasoning those regime signals weren't fixed blind either; **deliberately
   deferred, not proposed here.**

## Not yet done

Nothing implemented — gap-flag only, not a design (no formula finalized, no IC pre-screen run).
Batch into Phase 151's Wave 1 (atomic-primitives expansion) alongside todo 066/104/123's
candidates rather than a standalone phase; none of these are urgent on their own, and all
should go through the same IC-screening pipeline before promotion. Now 7 candidates total
(4 original + 2 from Fable review + 1 from same-day naming audit), one renamed
(`mkt_beta_z` → `equity_beta_z`).

## References

Surveyed via direct `feature_registry` query (2026-07-24 session), not from memory/docs —
confirmed zero overlap with the 135 live atomic rows and zero hits for these names anywhere in
`src/`/`services/`.
