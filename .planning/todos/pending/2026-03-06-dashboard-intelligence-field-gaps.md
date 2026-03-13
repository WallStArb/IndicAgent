# Dashboard Intelligence Field Gaps

**Filed:** 2026-03-06
**Updated:** 2026-03-12 — Phase 28 complete (I4 GARCH/Kalman, SMC BSL/SSL detail, I7 Signal Scorecard)
**Context:** Audit after signal timing visibility work (v1.4 phase)

The backend computes far more than the dashboard currently surfaces.
All data is already in the `intelligence:SYMBOL:TF` SSE stream — no backend changes needed
for I3/I4/I5/SMC/I6 gaps. I7 enrichment done (Phase 28).

## ~~I1 — Missing from hook mapping~~ ✅ DONE
- ~~`adx_14` + `plus_di_14` / `minus_di_14` — trend strength + direction components~~ ✅
- ~~`volume_ratio` — current vs average volume~~ ✅
- ~~`roc_14` — rate of change momentum~~ ✅
- ~~`supertrend_dir` — supertrend direction signal~~ ✅
- ~~`sma_20_gt_50` — MA cross boolean~~ ✅
- ~~AO (Awesome Oscillator), AC (Accelerator Oscillator)~~ ✅

## I3 — Not surfaced (drill panel could show these)
- Fibonacci: `fib_236/382/500/618/786`, `nearest_fib_level`, `nearest_fib_dist_atr`, `fib_cluster_strength`, `in_fib_discount_zone`
- Value Area / Volume Profile: `poc_level`, `va_high/low`, `va_width_pct`, `price_in_va`, `poc_dist_atr`
- Session levels: `prior_session_high/low/close`, `overnight_high/low/range_pct`, `opening_gap_pct`
- Weekly pivots: `weekly_pivot`, `weekly_r1/r2/s1/s2`
- VWAP stack: `session_vwap`, `swing_vwap`, `weekly_vwap`, `vwap_alignment_score`, `above_*_vwap`

## ~~I4 — Not surfaced~~ ✅ DONE (Phase 28)
- ~~GARCH: `garch_sigma`, `garch_vol_ratio`, `garch_vol_regime`, `garch_shock`~~ ✅
- ~~Kalman: `kalman_trend`, `kalman_slope`, `kalman_price_position`, `kalman_uncertainty`~~ ✅
- ~~Session/killzone timing: `in_london_killzone`, `in_ny_killzone`, `minutes_to_ny_open`, `bars_since_session_start`, `is_monday/friday`~~ ✅ (via SMC drill panel)
- MTF vol: `mtf_vol_expansion_15m`, `mtf_vol_expansion_1h`, `vol_divergence_score` — deferred

## I5 — Not surfaced
- Chart patterns: `dt_db_pattern`, `hs_pattern`, `tri_pattern`, `flag_pattern`, `pennant_pattern`, `cup_handle_pattern`, `abcd_pattern_active/direction`
- Candlesticks: `engulfing_bull/bear`, `pin_bar_bull/bear`, `hammer_detected`, `shooting_star_detected`, `inside_bar`, `doji_detected`
- Confluence breakdown: `trend_confluence_score/n_signals`, `meanrev_confluence_score`

## ~~SMC — Not surfaced~~ ✅ DONE (drill panel)
- ~~Demand/supply zones: `nearest_demand_high/low`, `demand_freshness/strength/dist_atr`, `in_demand_zone` (and supply equivalents)~~ ✅
- ~~Killzones: `in_asia/london/ny_am/ny_pm_killzone`, `killzone_name`, `minutes_until_next_killzone`~~ ✅
- ~~AMD phase: `amd_phase` (accumulation/manipulation/distribution), `amd_manipulation_detected`~~ ✅
- ~~Breaker blocks: `breaker_block_active/type/top/bottom/dist_atr`~~ ✅
- ~~BSL/SSL details: `bsl_dist_atr/touches/significance`, `ssl_dist_atr/touches/significance`~~ ✅ (Phase 28)
- ~~Premium/discount: `price_in_premium`, `premium_discount_pct`, `equilibrium_level`~~ ✅ (Phase 28)

## I6 — Partial (only ctf_score shown)
- `i6_smc_bos_alignment`, `i6_fvg_tf_alignment`, `i6_ob_tf_alignment`, `i6_i2_event_score`
- `ctf_highest_aligned_tf`

## ~~I7 enrichment~~ ✅ DONE (Phase 28)
- ~~`intelligence_i7:SYMBOL:TF` stream not subscribed in SSE route~~ ✅
- ~~Plugin competition view: `all_ranked` list with `composite_rank`, `regime_eligible`, `suppression_reason` per plugin~~ ✅ (Signal Scorecard component)
- ~~New SSE domain + SymbolData field + new UI component~~ ✅

## Remaining (deferred)
- I3 Fib/Value Area/Session levels/Weekly pivots/VWAP stack — needs new collapsible section layout
- I5 Chart patterns + candlestick details — needs visual layout decisions
- I6 confluence breakdown (`i6_smc_bos_alignment`, `i6_fvg_tf_alignment`, etc.) — partial
- I4 MTF vol divergence scores — needs cross-TF data flow design
