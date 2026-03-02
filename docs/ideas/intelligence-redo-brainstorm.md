│ Intelligence Palette Expansion — Brainstorming Design                                                                               │
│                                                                                                                                     │
│ Status: Design approved — route to writing-plans                                                                                    │
│ Date: 2026-03-01                                                                                                                    │
│ Milestone: v1.1 (standalone milestone before market_context_service)                                                                │
│                                                                                                                                     │
│ ---                                                                                                                                 │
│ Context                                                                                                                             │
│                                                                                                                                     │
│ The intelligence pipeline (I1→I3→I4→I5→SMC→I6→I7→I8) is architecturally sound but lacks depth.                                      │
│ Known issues from past code reviews: incorrect parameters, hardcoded constants, math errors.                                        │
│ Current palette has 39 plugins across I3–I6 — not enough "colors" to reliably differentiate quality setups                          │
│ from noise. I7 signals fire but lack the contextual richness to self-filter. I8 narratives are shallow                              │
│ because the LLM sees only the aggregated winner signal, not the full technical picture.                                             │
│                                                                                                                                     │
│ This milestone focuses on two parallel tracks before building the cross-asset layer (deferred to v1.2):                             │
│                                                                                                                                     │
│ 1. Correctness Audit — Fine-tooth-comb review of all existing plugins, I1 through I6                                                │
│ 2. Palette Expansion — Add I2 tier (new) + deepen I3/I4/I5/SMC/I6                                                                   │
│                                                                                                                                     │
│ ---                                                                                                                                 │
│ Track 1: Correctness Audit                                                                                                          │
│                                                                                                                                     │
│ Systematic plugin-by-plugin review. Each plugin gets:                                                                               │
│ - Mathematical formula verified against reference implementations                                                                   │
│ - Parameter choices justified or corrected (no magic numbers without rationale)                                                     │
│ - Edge cases handled (insufficient data, NaN, division by zero, first-bar warmup)                                                   │
│ - Incremental calculation correctness (supports_incremental plugins)                                                                │
│ - Unit test asserting known-output for a crafted bar sequence                                                                       │
│                                                                                                                                     │
│ Priority Audit Order                                                                                                                │
│                                                                                                                                     │
│ I1 (Indicator Service — 23 plugins):                                                                                                │
│ - RSI: confirm Wilder's smoothing (EWM α=1/14, not simple MA)                                                                       │
│ - ATR: Wilder's method vs rolling mean — must be Wilder's for consistency with I7 targets                                           │
│ - MACD: histogram = MACD_line − signal_line (not absolute)                                                                          │
│ - ADX: confirm +DI/−DI directional movement index uses smoothed TR in denominator                                                   │
│ - VWAP: session-based reset (not cumulative all-day) — rolling vs anchored distinction                                              │
│ - Stochastic: %K and %D smoothing periods correct; raw vs fast vs slow variants                                                     │
│ - Bollinger Bands: 20-period SMA ± 2σ standard                                                                                      │
│ - OBV: on-balance volume direction logic correct                                                                                    │
│                                                                                                                                     │
│ I3 Structure (3 plugins):                                                                                                           │
│ - SwingDetector: neighbor=5 hardcoded — TF-adaptive? (5 bars = 5min on 1m, 25min on 5m)                                             │
│ - S/R clustering: 0.5% threshold — may be too tight for ES (needs ~0.25%) or too loose for cheap contracts                          │
│ - TrendStructure: "dominant leg" definition, structure_integrity metric validity                                                    │
│                                                                                                                                     │
│ I4 Context (5 plugins):                                                                                                             │
│ - GARCH(1,1): are ω/α/β hardcoded? correct recursion? log-space stability?                                                          │
│ - Kalman 1D: is local-level model (random walk) correct or should it be 2D (level+velocity)?                                        │
│ - Q/R process/measurement noise — are these tuned empirically or arbitrary?                                                         │
│ - TrendRegime: SMA 20/50 — are these 20/50 bars of the current TF (correct) or hardcoded to 1m?                                     │
│ - MomentumContext: RSI/MACD/Stoch/CCI scoring function calibration                                                                  │
│                                                                                                                                     │
│ I5 Patterns (8 plugins):                                                                                                            │
│ - Double Top/Bottom: peak detection symmetry tolerance (how close must the two peaks be in price?)                                  │
│ - Head & Shoulders: shoulder height tolerance, neckline slope handling                                                              │
│ - Triangle/Wedge: slope calculation correctness, apex estimation                                                                    │
│ - RSI Divergence: swing lag window appropriate?                                                                                     │
│ - BollingerSqueeze: correct Keltner comparison formula                                                                              │
│                                                                                                                                     │
│ SMC (8 plugins):                                                                                                                    │
│ - BOS/CHoCH: per ICT theory — BOS = swing high/low broken with close, CHoCH = first opposing structural break                       │
│ - FVG: 3-bar gap (bar[−2].low > bar[0].high for bullish) — confirm correct bar indexing                                             │
│ - Order Blocks: "last bearish candle before a bullish BOS" — confirm lookback and mitigation logic                                  │
│ - LiquiditySweeps: wick-based sweep detection — is reclaim condition correct?                                                       │
│ - BOCPD: Bayesian changepoint — is prior/posterior update correct?                                                                  │
│ - HMM: forward algorithm implementation; emission distribution training (fixed or adaptive?)                                        │
│ - LiquidityPools: BSL/SSL definition correct per SMC theory                                                                         │
│ - SupplyDemand: basing pattern definition, zone "freshness" decay logic                                                             │
│                                                                                                                                     │
│ I6 Confluence (1 plugin):                                                                                                           │
│ - Staleness bug: intel_* frames use previous bar's cached intelligence (up to 60 min stale for 1h)                                  │
│ - Fix: weight each intel_* frame by recency: weight = 1 / (bars_since_computed + 1)                                                 │
│ - Also add: SMC multi-TF coherence sub-score (is 1m BOS direction aligned with 15m structural trend?)                               │
│                                                                                                                                     │
│ ---                                                                                                                                 │
│ Track 2: Palette Expansion                                                                                                          │
│                                                                                                                                     │
│ NEW: I2 Tier — Indicator Events & Crossovers                                                                                        │
│                                                                                                                                     │
│ Key finding: I2 is already documented in docs/concepts/intelligence-tiers.md as "Composite                                          │
│ Indicators" with code location src/intelligence/composites/. MACompositePlugin already exists in                                    │
│ src/intelligence/composites/ma_composites.py but is NOT registered in the pipeline — no TIER_I2                                     │
│ in register_plugins.py and market_analysis_service doesn't call it. This milestone wires it up                                      │
│ and expands the tier.                                                                                                               │
│                                                                                                                                     │
│ What MACompositePlugin already computes: EMA 9/21 crossover, SMA 20/50 crossover, price vs SMA50                                    │
│ (above/touch/bounce), MA slopes for 20/50/100/200, distance % and z-score from SMA 20/50.                                           │
│                                                                                                                                     │
│ File location: src/intelligence/composites/ (already exists, add new files here)                                                    │
│ Schema: New i2: I2Composites field in IntelligenceEvent (add to schemas.py)                                                         │
│ Registration: New TIER_I2 in register_plugins.py, inserted between I1 and I3 in pipeline                                            │
│ Migration: New i2 JSONB column in intelligence_features hypertable                                                                  │
│                                                                                                                                     │
│ I2 Plugins (1 existing to wire + 5 new):                                                                                            │
│                                                                                                                                     │
│ 1. MA Crossover Events (MAComposite — src/intelligence/composites/ma_composites.py ALREADY EXISTS)                                  │
│   - Wire into pipeline; expand with: golden_cross_active (SMA50 > SMA200), death_cross_active,                                      │
│ golden_cross_bars_ago, price_above_sma200 (currently only sma50 tracked)                                                            │
│ 2. MACD Events (evt_MACDEvents)                                                                                                     │
│   - MACD line crosses signal line: macd_cross_bullish, macd_cross_bearish, macd_cross_bars_ago                                      │
│   - MACD histogram transitions zero: macd_hist_positive, macd_hist_turning_up (hist > hist[-1] and was negative)                    │
│   - MACD in negative territory but price retesting support: macd_negative_support_test (key confluence flag user mentioned)         │
│   - MACD divergence from price: macd_price_divergence_bullish/bearish (existing RSI divergence logic applied to MACD)               │
│ 3. RSI Events (evt_RSIEvents)                                                                                                       │
│   - RSI threshold crossings: rsi_crossed_30_up, rsi_crossed_70_down, rsi_crossed_50_up/down                                         │
│   - RSI extreme reversal: rsi_extreme_reversal (RSI was <30 and now rising, or >70 and now falling)                                 │
│   - RSI bars_in_extreme: count of bars RSI has been in overbought/oversold zone                                                     │
│ 4. Stochastic Events (evt_StochasticEvents)                                                                                         │
│   - K/D crossover: stoch_cross_bullish/bearish                                                                                      │
│   - K crossing 20/80: stoch_oversold_reversal, stoch_overbought_reversal                                                            │
│   - K/D alignment: stoch_both_oversold, stoch_both_overbought                                                                       │
│ 5. ADX/Trend Events (evt_ADXEvents)                                                                                                 │
│   - ADX crossing 25 up: adx_trend_confirmed (trending regime triggered)                                                             │
│   - ADX crossing 20 down: adx_ranging_confirmed                                                                                     │
│   - +DI/-DI crossover: di_cross_bullish/bearish, di_cross_bars_ago                                                                  │
│   - DI spread magnitude: di_spread (+DI − −DI), useful for trend strength                                                           │
│ 6. Volume & Bollinger Events (evt_VolumeEvents)                                                                                     │
│   - Volume spike: vol_spike (current vol > 2σ above 20-bar average)                                                                 │
│   - Volume drying up: vol_drying (current vol < 0.5× 20-bar average)                                                                │
│   - BB band touch: bb_upper_touch, bb_lower_touch (close within 10% of BB width from outer band)                                    │
│   - BB walking the band: bb_walking_upper/lower (3+ closes above/below BB midline)                                                  │
│                                                                                                                                     │
│ Pipeline placement: I2 runs after I1 features are available (they come in via indicator stream),                                    │
│ before I3. I2 plugins only consume I1 features from frames["features"].                                                             │
│                                                                                                                                     │
│ ---                                                                                                                                 │
│ I3 Structure Additions (4 new plugins)                                                                                              │
│                                                                                                                                     │
│ 4. Market Profile (struct_MarketProfile)                                                                                            │
│   - Intraday rolling TPO: poc_level (price with most time-at-price), va_high, va_low (70% volume value area)                        │
│   - VA width as % of range: va_width_pct                                                                                            │
│   - Price position relative to VA: price_in_va, price_above_va, price_below_va                                                      │
│   - POC distance from current price: poc_dist_pct, poc_dist_atr                                                                     │
│ 5. Session Levels (struct_SessionLevels)                                                                                            │
│   - Prior session high/low/close (NY session): prior_session_high, prior_session_low, prior_session_close                           │
│   - Overnight (Globex) range: overnight_high, overnight_low, overnight_range_pct                                                    │
│   - Opening gap: opening_gap_pct, opening_gap_type (gap-up/gap-down/flat)                                                           │
│   - Weekly pivot levels (standard floor trader pivots): weekly_pivot, weekly_r1/r2, weekly_s1/s2                                    │
│   - Distance to nearest level: nearest_session_level, nearest_level_dist_atr                                                        │
│ 6. Anchored VWAP Zones (struct_AnchoredVWAP)                                                                                        │
│   - Session VWAP (anchored to day open): session_vwap, session_vwap_dist_pct                                                        │
│   - Swing VWAP (anchored to most recent swing low for bullish, swing high for bearish): swing_vwap                                  │
│   - Weekly VWAP (anchored to Monday open): weekly_vwap                                                                              │
│   - Price position relative to each: above_session_vwap, above_swing_vwap, above_weekly_vwap                                        │
│   - VWAP alignment score: all three VWAPs above/below price → strong directional bias                                               │
│ 7. Fibonacci Cluster Zones (struct_FibonacciZones)                                                                                  │
│   - Fib levels from most recent major swing (high to low or low to high): 0.236, 0.382, 0.5, 0.618, 0.786                           │
│   - Cluster detection: levels within ATR/2 of each other → stronger zone                                                            │
│   - nearest_fib_level, nearest_fib_ratio, nearest_fib_dist_atr, fib_cluster_strength                                                │
│   - Directional bias: in_fib_discount_zone (0.5–0.786 retrace in uptrend = buy zone)                                                │
│                                                                                                                                     │
│ ---                                                                                                                                 │
│ I4 Context Additions (2 new plugins)                                                                                                │
│                                                                                                                                     │
│ 6. Session Context (ctx_SessionContext)                                                                                             │
│   - Current session flag: session_asia, session_london, session_ny, session_london_ny_overlap, session_after_hours                  │
│   - High-liquidity window (ICT Killzones): in_london_killzone (2–5am ET), in_ny_killzone (7–10am ET)                                │
│   - Time context: minutes_to_ny_open, minutes_to_london_open, bars_since_session_start                                              │
│   - Day of week: is_monday, is_friday (gap risk / fade tendencies)                                                                  │
│ 7. Multi-TF Volatility Context (ctx_MTFVolatility)                                                                                  │
│   - Compare vol regime across TFs using intel_* cache: is 1m compressed while 15m is expanding?                                     │
│   - mtf_vol_expansion_15m, mtf_vol_expansion_1h: bool — higher TF showing vol expansion                                             │
│   - squeeze_within_expansion: 1m squeeze while 15m+ vol expanding → high-probability breakout context                               │
│   - vol_divergence_score: −1 (all TFs contracting) to +1 (all expanding), sign = directional vote                                   │
│                                                                                                                                     │
│ ---                                                                                                                                 │
│ I5 Pattern Additions (6 new plugins)                                                                                                │
│                                                                                                                                     │
│ 9. Candlestick Patterns (pat_CandlestickPatterns)                                                                                   │
│   - Engulfing: engulfing_bull, engulfing_bear (current bar body engulfs prior bar body)                                             │
│   - Pin Bar: pin_bar_bull (lower wick ≥ 2× body, small upper wick), pin_bar_bear (inverse)                                          │
│   - Hammer / Shooting Star: hammer_detected, shooting_star_detected (with trend context from I3)                                    │
│   - Inside Bar: inside_bar (full range within prior bar) — potential squeeze/breakout setup                                         │
│   - Outside Bar: outside_bar (engulfs prior range) — potential momentum continuation or reversal                                    │
│   - Doji: doji_detected (open ≈ close, long wicks) — indecision / reversal at key level                                             │
│ 10. Flag / Pennant (pat_FlagPennant)                                                                                                │
│   - Identify impulse leg: sharp directional move with above-average volume and range                                                │
│   - Flag: parallel consolidation channel (2–15 bars) after impulse, lower vol                                                       │
│   - Pennant: symmetrical converging bounds after impulse                                                                            │
│   - flag_pattern, pennant_pattern (0=none, 1=bull, −1=bear)                                                                         │
│   - flag_breakout_target (entry + impulse length projected from consolidation)                                                      │
│   - consolidation_compression_ratio (range compression vs impulse range)                                                            │
│ 11. Cup and Handle (pat_CupHandle)                                                                                                  │
│   - Rounded bottom detection: U-shape via parabolic regression fit quality                                                          │
│   - Handle: tight pullback (≤50% of cup depth) after right cup rim                                                                  │
│   - cup_handle_pattern (0/1), cup_depth_pct, cup_handle_target                                                                      │
│ 12. Measured Move / ABCD (pat_MeasuredMove)                                                                                         │
│   - AB=CD harmonic: A swing → B correction (0.618 of AB) → C impulse → D target (AB projected from C)                               │
│   - abcd_pattern_active, abcd_direction, abcd_d_target, abcd_completion_pct                                                         │
│   - ABCD targets often align with Fibonacci clusters and SMC order blocks → natural confluence                                      │
│ 13. Volume Profile Pattern (pat_VolumeProfile)                                                                                      │
│   - Intraday volume histogram: identify HVN (High Volume Node) vs LVN (Low Volume Node)                                             │
│   - HVN: price tends to stall/reverse (S/R magnetic)                                                                                │
│   - LVN: price tends to accelerate through                                                                                          │
│   - nearest_hvn_level, nearest_hvn_dist_atr, nearest_lvn_level, in_lvn (fast-move context)                                          │
│ 14. Price Reaction at Key Level (pat_KeyLevelReaction)                                                                              │
│   - Detects how price behaves when touching S/R, order blocks, FVG, Fibonacci zones                                                 │
│   - Requires cross-tier reading (I3 S/R + SMC OB/FVG distances)                                                                     │
│   - key_level_reaction_type: 0=none, 1=sharp_reject (pin bar at level), 2=base (inside bars), 3=break_and_retest, 4=clean_break     │
│   - key_level_confluence_count: how many key levels overlap within ATR/2                                                            │
│                                                                                                                                     │
│ ---                                                                                                                                 │
│ SMC Additions (5 new plugins)                                                                                                       │
│                                                                                                                                     │
│ 9. ICT Killzones (smc_ICTKillzones)                                                                                                 │
│   - Flag current time in predefined liquidity windows: in_asia_killzone, in_london_killzone, in_ny_am_killzone, in_ny_pm_killzone   │
│   - Key context: most significant ICT setups initiate within killzones                                                              │
│   - killzone_name: "asia" / "london" / "ny_am" / "ny_pm" / ""                                                                       │
│   - minutes_in_killzone, minutes_until_next_killzone                                                                                │
│ 10. AMD Cycle Detection (smc_AMDCycle)                                                                                              │
│   - Classify current bar into daily AMD phase based on session + price behavior:                                                    │
│       - Accumulation: overnight range, tight consolidation, low vol (8pm–midnight ET)                                               │
│     - Manipulation: stop hunt beyond prior session range, spike + reversal (midnight–5am ET)                                        │
│     - Distribution: sustained directional move from manipulation level (5am–noon ET)                                                │
│   - amd_phase: "accumulation" / "manipulation" / "distribution" / "unknown"                                                         │
│   - amd_manipulation_detected: price spiked beyond overnight range and returned                                                     │
│   - amd_distribution_direction: expected directional bias from AMD analysis                                                         │
│ 11. Breaker Blocks (smc_BreakerBlocks)                                                                                              │
│   - A previously detected Order Block that was fully mitigated (price ran through it)                                               │
│   - Now acts as an opposing-direction OB (bullish OB that failed → now bearish breaker)                                             │
│   - breaker_block_active: 0/1                                                                                                       │
│   - breaker_block_type: −1 (bearish, was bullish OB), +1 (bullish, was bearish OB)                                                  │
│   - breaker_block_top, breaker_block_bottom, breaker_dist_atr                                                                       │
│   - Requires tracking OB history and mitigation state (builds on smc_OrderBlocks state)                                             │
│ 12. Mitigation Blocks (smc_MitigationBlocks)                                                                                        │
│   - Distinguish OB strength: fresh (no retest), mitigated (partial retest), void (fully swept)                                      │
│   - ob_mitigation_status: "fresh" / "partial" / "void"                                                                              │
│   - ob_mitigation_pct: % of OB range that has been revisited                                                                        │
│   - Fresh OBs carry full institutional weight; mitigated OBs are weakened; void OBs removed from tracking                           │
│   - Refines existing smc_OrderBlocks output rather than being fully separate                                                        │
│ 13. Premium / Discount Array (smc_PremiumDiscount)                                                                                  │
│   - Equilibrium = 50% of the current swing range (low to high of identified move)                                                   │
│   - Premium zone = price > 50% (above equilibrium) → ICT prefers shorts from premium                                                │
│   - Discount zone = price < 50% → ICT prefers longs from discount                                                                   │
│   - price_in_premium: 1.0 / 0.0 (already exists in smc_LiquidityPools — move/consolidate here)                                      │
│   - premium_discount_pct: −1.0 (deep discount) to +1.0 (deep premium)                                                               │
│   - equilibrium_level: the 50% price level of current structural swing                                                              │
│   - Note: smc_LiquidityPools already has price_in_premium — audit for duplication, consolidate                                      │
│                                                                                                                                     │
│ ---                                                                                                                                 │
│ I6 Confluence Refactor (existing plugin, significant improvements)                                                                  │
│                                                                                                                                     │
│ Recency weighting: Weight each intel_* frame contribution by:                                                                       │
│ bars_since = frames.get(f"intel_{tf}_bars_since", 999)                                                                              │
│ weight = 1.0 / (bars_since + 1)                                                                                                     │
│ A fresh 5m bar (1 bar ago) weights at 0.5; a 60-min-old 1h bar (60 bars ago) weights at 0.016.                                      │
│ This corrects the fundamental staleness bug in cross-TF confluence.                                                                 │
│                                                                                                                                     │
│ SMC cross-TF sub-score (new I6 output fields):                                                                                      │
│ - i6_smc_bos_alignment: is 1m BOS direction consistent with 15m structural trend_direction?                                         │
│ - i6_fvg_tf_alignment: is there an unfilled FVG on a higher TF in the same direction as 1m signal?                                  │
│ - i6_ob_tf_alignment: is the current bar within a higher-TF order block that aligns with expected direction?                        │
│                                                                                                                                     │
│ I2 event integration: I6 confluence now reads I2 events (crossovers, extremes) as additional                                        │
│ confluence signals — MACD bullish crossover + 15m uptrend in I6 = stronger confluence score.                                        │
│                                                                                                                                     │
│ ---                                                                                                                                 │
│ Section 3: Future Horizon (Not in This Milestone)                                                                                   │
│                                                                                                                                     │
│ v1.2 (or v1.1 Phase 7): I7 New Trading Setups                                                                                       │
│                                                                                                                                     │
│ These setups are designed now but can only be implemented after the I2/I3/I5/SMC plugins that they                                  │
│ depend on are built. Target: add as Phase 7 of v1.1 if timeline allows, else v1.2.                                                  │
│                                                                                                                                     │
│ 1. ICT Killzone Reversal (trad_KillzoneReversal)                                                                                    │
│ - Gate: in_london_killzone OR in_ny_am_killzone (from I4 session context)                                                           │
│ - Trigger: sweep_detected within the killzone + sweep_reclaimed (same as existing LiquiditySweepReclaim but time-gated)             │
│ - Confirmation: amd_phase == "manipulation" + FVG or OB in direction of expected distribution                                       │
│ - Direction: opposite of sweep direction (sweep highs → short, sweep lows → long)                                                   │
│ - Confidence: killzone_weight(0.3) + sweep_depth(0.25) + smc_alignment(0.25) + amd_phase_match(0.2)                                 │
│ - Target: prior session opposing extreme (e.g., swept prior high → target prior session low)                                        │
│ - Rationale: ICT's most reliable setup — institutional stop hunt within time-filtered high-liquidity window                         │
│                                                                                                                                     │
│ 2. ABCD Harmonic Completion (trad_ABCDCompletion)                                                                                   │
│ - Gate: abcd_pattern_active (from I5 MeasuredMove plugin) + abcd_completion_pct > 90% (at D point)                                  │
│ - Confirmation: D level coincides with: (a) OB/FVG or (b) Fibonacci cluster or (c) demand/supply zone                               │
│ - Volume gate: vol_drying at D (compression before reversal) from I2 volume events                                                  │
│ - Direction: abcd_direction (opposite — if pattern was downswing, long at D)                                                        │
│ - Targets: 38.2% retrace of CD leg, then 61.8%, then full AB length from D                                                          │
│ - Confidence: abcd_completion_quality(0.35) + structural_confluence_count(0.35) + volume_compression(0.30)                          │
│ - Rationale: Harmonic patterns with SMC level confluence have defined entry + measured targets                                      │
│                                                                                                                                     │
│ 3. AMD Distribution Setup (trad_AMDDistribution)                                                                                    │
│ - Gate: amd_manipulation_detected (price spiked beyond overnight range and returned) — I1 must be past midnight ET                  │
│ - Trigger: bos_detected in distribution direction (away from manipulation spike)                                                    │
│ - Volume: vol_spike at BOS bar (institutional distribution volume)                                                                  │
│ - Direction: amd_distribution_direction (from AMD cycle analysis)                                                                   │
│ - Confidence: manipulation_depth(0.35) + bos_strength(0.30) + volume_confirmation(0.20) + killzone(0.15)                            │
│ - Targets: 2R/3R based on overnight manipulation range                                                                              │
│ - Rationale: Follows the full AMD cycle — after manipulation (stop hunt), distribution is the highest-conviction directional move   │
│ of the day                                                                                                                          │
│                                                                                                                                     │
│ 4. Squeeze-Within-Expansion Breakout (trad_SqueezeInExpansion)                                                                      │
│ - Gate: squeeze_active (current TF BB squeeze) + mtf_vol_expansion_15m OR mtf_vol_expansion_1h (higher TF expanding)                │
│ - Trigger: squeeze_fired (momentum breakout from squeeze) OR bos_detected on squeeze bar                                            │
│ - Direction: sign of breakout momentum + must align with ctf_trend_alignment > 0.4                                                  │
│ - Confidence: squeeze_duration(0.25) + expansion_strength(0.30) + breakout_momentum(0.25) + ctf_alignment(0.20)                     │
│ - Targets: 1.5R/3R/5R (squeeze-expansion moves often trend far)                                                                     │
│ - Rationale: Compression nested inside expansion = coiled spring. Improves on existing SqueezeExpansion by requiring multi-TF       │
│ validation, eliminating false squeezes during contracting markets.                                                                  │
│                                                                                                                                     │
│ 5. MACD Negative Support Confluence (trad_MACDNegativeSupport)                                                                      │
│ - Gate: macd_hist_positive == 0 (MACD histogram negative) — exhausted downside momentum (from I2)                                   │
│ - Structural: price within 1 ATR of: nearest_demand_low OR nearest_support OR ssl_level (stop hunt zone)                            │
│ - Reversal confirmation: rsi_extreme_reversal (RSI recovering from oversold) from I2 RSI events                                     │
│ - Bonus: in_demand_zone, in_fib_discount_zone, liq_sweep_reclaimed each boost confidence                                            │
│ - Direction: long only (MACD negative = downside exhaustion, not continuation)                                                      │
│ - Confidence: macd_depth_below_zero(0.25) + sr_proximity(0.30) + rsi_recovery(0.25) + structural_confluence(0.20)                   │
│ - Targets: Kalman trend value (fair value reversion), BB midline, nearest resistance                                                │
│ - Rationale: MACD going negative means momentum exhausted on the downside — combined with structural support + RSI recovery =       │
│ counter-trend reversal at high-probability level. User specifically identified this as a key untracked signal.                      │
│                                                                                                                                     │
│ 6. Candlestick at SMC Confluence (trad_PriceActionAtLevel)                                                                          │
│ - Gate: pin_bar_bull OR engulfing_bull (long) or pin_bar_bear OR engulfing_bear (short) from I5 candlestick plugin                  │
│ - Structural: at least 2 of: in_demand_zone, ob_distance_pct < 0.5, fvg_bottom within ATR, in_fib_discount_zone,                    │
│ nearest_support_dist_pct < 0.3, ssl_level within ATR/2                                                                              │
│ - Session: in_london_killzone OR in_ny_am_killzone (optional but significant bonus)                                                 │
│ - Confidence: candle_quality(0.30) + confluence_count × 0.15 each (max 0.45) + killzone_bonus(0.10) + momentum_agreement(0.15)      │
│ - Targets: 1.5R/3R (precise entry = tight stop, wide targets)                                                                       │
│ - Rationale: Price action (candlestick patterns) at institutional levels is the highest-precision entry signal. Single candlestick  │
│ at a single level = noise; candlestick at 3+ confluent levels = institutional response.                                             │
│                                                                                                                                     │
│ 7. Fibonacci Premium/Discount Reversal (trad_FibDiscount)                                                                           │
│ - Gate: in_fib_discount_zone (price in 0.618–0.786 retrace from I3 Fibonacci plugin) + premium_discount_pct < -0.4 (ICT deep        │
│ discount)                                                                                                                           │
│ - Confirmation: higher TF trend aligned (ctf_trend_alignment > 0.5) + candlestick reversal pattern                                  │
│ - Bonus: OB or demand zone at same fib level                                                                                        │
│ - Direction: long from discount, short from premium                                                                                 │
│ - Confidence: fib_depth(0.30) + discount_pct(0.25) + htf_alignment(0.25) + candlestick(0.20)                                        │
│ - Targets: 50% (equilibrium), 61.8% retrace retrace, prior swing extreme                                                            │
│ - Rationale: Fibonacci premium/discount combined with ICT equilibrium framework identifies where institutions are positioned and    │
│ looking to fade.                                                                                                                    │
│                                                                                                                                     │
│ 8. Volume Profile Acceleration (trad_VolumeProfileAccel)                                                                            │
│ - Gate: in_lvn == True (price in Low Volume Node from I5 volume profile plugin)                                                     │
│ - Momentum: momentum_bias > 0.5 or < -0.5 + adx_trend_confirmed (from I2 ADX events)                                                │
│ - Structure: swing_pattern aligned with momentum direction                                                                          │
│ - Direction: sign of momentum_bias                                                                                                  │
│ - Confidence: lvn_depth(0.30) + momentum_strength(0.35) + structural_alignment(0.35)                                                │
│ - Targets: Next HVN above (for long) or next HVN below (for short) — measured move from LVN width                                   │
│ - Rationale: In LVN zones, price meets thin resistance. Momentum entering a LVN with trend + structure alignment = acceleration to  │
│ the next HVN anchor. Natural targets + defined risk at LVN entry.                                                                   │
│                                                                                                                                     │
│ v1.2: Market Context Service (Cross-Asset Layer)                                                                                    │
│                                                                                                                                     │
│ New market_context_service reading all intelligence:SYMBOL:TF streams:                                                              │
│ - Rolling cross-asset correlation matrix (ES/NQ/RTY leadership)                                                                     │
│ - VX regime (fear/complacency) from VX futures intelligence                                                                         │
│ - Rates direction (ZN/ZB trend) as equity macro filter                                                                              │
│ - Dollar proxy (GC/SI inverse) for commodity/FX context                                                                             │
│ - Sector alignment scores → published to market_context:global Redis hash                                                           │
│                                                                                                                                     │
│ v1.2: I8 Enrichment                                                                                                                 │
│                                                                                                                                     │
│ - Signal generator publishes full IntelligenceEvent alongside winner signal (or to a separate richer stream)                        │
│ - I8 prompt includes I1–I6 summary + market_context:global data                                                                     │
│ - LLM can reason: "MACD negative crossover, but RSI oversold + liquidity zone nearby + London killzone active + VX elevated         │
│ suggesting fear reversal → confluence supports cautious long"                                                                       │
│                                                                                                                                     │
│ ---                                                                                                                                 │
│ Architecture Notes                                                                                                                  │
│                                                                                                                                     │
│ - All v1.1 changes stay within existing market_analysis_service                                                                     │
│ - No new services in v1.1                                                                                                           │
│ - New plugins follow PatternPlugin protocol (compute(frames, features) → dict)                                                      │
│ - TIER_I2 added to register_plugins.py, inserted in pipeline after I1 features loaded                                               │
│ - Schema: I2Events added to IntelligenceEvent in schemas.py                                                                         │
│ - intelligence_features TimescaleDB table: new i2 JSONB column (migration)                                                          │
│ - Market_analysis_service runs I2 plugins between I1 feature consumption and I3 execution                                           │
│                                                                                                                                     │
│ Delivery Phases                                                                                                                     │
│                                                                                                                                     │
│ 1. Correctness audit — all existing plugins I1→I6 (bugs found = fix inline, document all changes)                                   │
│ 2. I2 tier — 6 new indicator event plugins + schema + migration                                                                     │
│ 3. I3 additions — 4 new structure plugins (market profile, session levels, anchored VWAP, Fibonacci)                                │
│ 4. I4 additions — 2 new context plugins (session context, MTF volatility)                                                           │
│ 5. I5 additions — 6 new pattern plugins (candlestick, flag/pennant, cup/handle, ABCD, volume profile, key level reaction)           │
│ 6. SMC additions — 5 new SMC plugins (killzones, AMD cycle, breaker blocks, mitigation blocks, premium/discount)                    │
│ 7. I6 refactor — recency weighting, SMC multi-TF alignment, I2 event integration                                                    │
│                                                                                                                                     │
│ Verification                                                                                                                        │
│                                                                                                                                     │
│ - .venv/bin/pytest tests/unit/ -v — all 803+ tests pass (new tests per plugin)                                                      │
│ - .venv/bin/ruff check . --fix — 0 errors                                                                                           │
│ - Full pipeline integration: feed 200 bars of real data through market_analysis_service, assert no NaN/exception in                 │
│ IntelligenceEvent                                                                                                                   │
│ - Per-plugin correctness tests: known-output bar sequence → expected output values                                                  │
│ - Signal quality check: after expansion, does CIS score distribution shift? Are high-confidence signals fewer but more precise?