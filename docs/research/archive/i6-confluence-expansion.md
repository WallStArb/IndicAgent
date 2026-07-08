# I6 Confluence Expansion — Cross-Timeframe + Cross-Asset + Macro Intelligence

**Version:** 2.0.0
**Last Updated:** 2026-04-08
**Status:** Research & Design — ready for prioritization
**Related:** `renaissance-i7-i8-refinement.md`, `regime-adaptive-trading.md`

---

## Context

I6 (Confluence) currently has one plugin: `CrossTimeframeConfluencePlugin`. It answers a single question:

> **"Do higher timeframes confirm this signal?"**

The platform now has 50+ instruments flowing through the pipeline — equity indices, FX pairs, rate futures, crypto, sector ETFs, factor ETFs, commodities, and international markets. The confluence layer should synthesize across **three orthogonal dimensions**:

1. **Time-scale confluence** — Do 5m/15m/1h/4h agree? Do regime changes cascade across TFs?
2. **Cross-asset confluence** — Do correlated assets agree? Is the macro backdrop supportive?
3. **Market-structure confluence** — Yield curve shape, credit spreads, USD strength, sector rotation — macro regime context for every signal.

Renaissance principles demand segmentation across orthogonal dimensions: *"A rule that works globally is weaker than one that works in a specific regime."*

**Architecture note (v2.2):** The pipeline is now a unified `intelligence_pipeline_agent` (Phase 57) with 4-wave sub-wave execution:
```
Wave 1: I2-A(8) + I3(8) + SMC-A(10)  — independent, I1 only
Wave 2: I2-B(2) + SMC-B(3) + I4-A(11) — I4 has I3 data
Wave 3: I4-B(1) + I5(16)              — kalman after garch
Wave 4: I6(1) + I7(36)                — confluence then signals
```

---

## Current I6 Implementation

### `CrossTimeframeConfluencePlugin` — Fully Implemented (16 fields)

Reads cached intelligence from other timeframes (`frames["intel_*"]`) and produces:

| Output | Range | Weight | Description |
|--------|-------|--------|-------------|
| `ctf_score` | [-1, +1] | — | Weighted composite of all components |
| `ctf_trend_alignment` | [-1, +1] | 0.4 | Trend direction + strength agreement across TFs |
| `ctf_structure_alignment` | [-1, +1] | 0.3 | Swing pattern agreement across TFs |
| `ctf_regime_agreement` | [0, +1] | 0.2 | Vol/momentum regime consistency |
| `ctf_timeframes_aligned` | count | — | Number of aligned TFs |
| `ctf_highest_aligned_tf` | minutes | — | Highest TF that agrees |
| `i6_smc_bos_alignment` | [-1, +1] | — | BOS direction vs higher-TF trend |
| `i6_fvg_tf_alignment` / `ctf_fvg_alignment` | [-1, +1] | — | FVG overlap across TFs |
| `i6_ob_tf_alignment` / `ctf_ob_alignment` | [-1, +1] | — | Order Block proximity across TFs |
| `i6_i2_event_score` | [-1, +1] | — | I2 event confluence across TFs |
| `i6_fvg_tf_{1m,5m,15m,1h,4h,1d}` | float | — | Per-TF FVG alignment scores |
| `i6_ob_tf_{1m,5m,15m,1h,4h,1d}` | float | — | Per-TF OB alignment scores |

**Recency weighting:** Stale intel contributes less via `weight = 1.0 / (bars_since + 1)`.

**File:** `src/intelligence/confluence/cross_timeframe.py`
**Schema:** `I6Confluence` in `src/intelligence/schemas.py`

---

## Completed Work

The original v1.0 doc listed several items as "TODO stubs" or "planned." These are now done:

| Item | Status | Details |
|------|--------|---------|
| FVG cross-TF alignment | **Done** | `score_fvg_alignment()` — higher-TF authority weights, proximity decay |
| OB cross-TF alignment | **Done** | `score_ob_alignment()` — per-TF contributions, proximity scoring |
| Per-TF FVG/OB scores | **Done** | 12 flat fields (`i6_fvg_tf_1m`..`i6_ob_tf_1d`) for ML feature matrix |
| Cross-asset service | **Done** | `services/cross_asset_service.py` — ES/NQ/RTY/YM spread features |
| Cross-asset I4 context | **Done** | `ctx_CrossAssetContext` — `eq_spread_z`, `eq_pairs_confirming` |
| Cross-asset I7 signal | **Done** | `trad_CrossAssetDivergence` — regime-biased spread divergence setup |
| VIX regime (I4) | **Done** | `ctx_VIXRegime` — VIX level + z-score per bar |
| Unified pipeline | **Done** | Phase 57 merged `feature_compute_agent` + `signal_generator_agent` |
| Wave-based execution | **Done** | 4-wave sub-wave structure with accumulating merge |

---

## New Ideas: Cross-TF Confluence

All data is already available via `frames["intel_{other_tf}"]` — zero new subscriptions needed.

### 1. Multi-TF S/R Level Confluence

**What:** Score support/resistance levels by how many timeframes agree. I3 produces per-TF S/R (nearest_support, nearest_resistance); this cross-references them.

**Logic sketch:**
```
For each TF's S/R levels:
  Count how many other TFs have a level within 0.5 ATR
  confluence_score = agreeing_TFs / total_TFs
  Higher confluence → structurally stronger level
```

**New outputs:** `ctf_sr_confluence`, `ctf_strongest_level_type` (support/resistance/none)

**Why it matters:** A level that's S/R on 15m, 1h, and 4h is structurally stronger than one visible on a single TF. I7 plugins trading near high-confluence levels should have higher confidence.

**Complexity:** Low. Read `intel_*` S/R fields, compare proximity, count agreements.

---

### 2. TF Cascade Detection

**What:** Detect when regime changes propagate across timeframes and measure cascade velocity.

**Logic sketch:**
```
Track per-TF HMM regime state changes.
When regime changes:
  cascade = list of (TF, bar_number) where regime changed
  velocity = (max_TF_minutes - min_TF_minutes) / (bar_span * current_TF_seconds)
  direction = "htf_first" (4h→1h→15m) vs "ltf_first" (1m→5m→15m)

htf_first cascade = institutional regime shift (high conviction)
ltf_first cascade = retail noise (low conviction)
no cascade = isolated event
```

**New outputs:** `ctf_cascade_score` [-1, +1], `ctf_cascade_direction` (htf_first/ltf_first/none), `ctf_cascade_velocity`

**Why it matters:** A regime change that starts on 4h and cascades down is fundamentally different from one that starts on 1m. The former is institutional; the latter is noise. This is regime-change quality scoring.

**Complexity:** Medium. Requires per-TF regime state tracking (stateful plugin).

---

### 3. Cross-TF Volume Profile Confluence

**What:** Score POC (Point of Control) clustering across timeframes. I4 produces per-TF VP (poc_price, vah, val).

**Logic sketch:**
```
Collect POCs from all available TFs.
Compute ATR-normalized spread of POC cluster.
If spread < 0.5 ATR → strong confluence (all TFs agree on value)
If spread > 2.0 ATR → no agreement

Weight by TF authority (4h POC > 5m POC for structural significance)
```

**New outputs:** `ctf_vp_poc_cluster_score` [0, 1], `ctf_vp_cluster_center` (price level)

**Why it matters:** When multiple TFs agree on the "fair value" (POC), that price level becomes a magnet. Price远离 from a multi-TF POC cluster is more likely to revert than price 远离 from a single-TF POC.

**Complexity:** Low. Read I4 VP fields from `intel_*`, compute spread.

---

### 4. Cross-TF Momentum Divergence

**What:** Capture direction divergence across timeframes — HTF bullish + LTF bearish signals different conditions than aligned momentum.

**Logic sketch:**
```
Extract momentum bias from each TF (from I2 events, RSI, MACD direction).
htf_bias = weighted average of 1h + 4h momentum
ltf_bias = weighted average of 1m + 5m momentum

divergence = htf_bias - ltf_bias
positive divergence (HTF up, LTF down) = pullback in uptrend → continuation setup
negative divergence (HTF down, LTF up) = bounce in downtrend → continuation setup
no divergence = aligned momentum → trend strength confirmation
```

**New outputs:** `ctf_momentum_divergence` [-1, +1], `ctf_momentum_regime` (aligned_htf_bull/aligned_htf_bear/pullback/bounce/mixed)

**Why it matters:** The existing `ctf_trend_alignment` is binary (agree/disagree). This captures the *shape* of the disagreement — pullback vs reversal have completely different trading implications.

**Complexity:** Low. Uses existing I2 event + I1 RSI/MACD outputs from `intel_*`.

---

### 5. Multi-TF HMM Regime Agreement

**What:** Score consistency of HMM regime classification across timeframes. The combination of regimes is itself a regime.

**Logic sketch:**
```
Collect hmm_regime from each TF.
Enumerate the combination:
  all_trending  = strong trend regime
  all_ranging   = strong range regime
  htf_trend + ltf_range = "trend-with-pullbacks" (range within trend)
  htf_range + ltf_trend = "trend-exhaustion" (trend losing steam)
  mixed         = transitional regime

Score: agreement_fraction + specific_combo_weight
```

**New outputs:** `ctf_regime_combo` (categorical), `ctf_regime_agreement_detail` [0, 1]

**Why it matters:** "Trending on 4h + ranging on 15m" is a specific, tradeable regime (pullback setups). The current `ctf_regime_agreement` is a single float that loses this granularity. Renaissance: *segment relentlessly*.

**Complexity:** Low. Uses existing `smc_HMMRegime` output from `intel_*`.

---

### 6. Cross-TF Order Flow Alignment

**What:** OFI (Order Flow Imbalance) and CVD direction agreement across timeframes.

**Logic sketch:**
```
Collect OFI/CVD direction from I1 outputs across TFs.
aligned_buying = all TFs show positive OFI + positive CVD
aligned_selling = all TFs show negative OFI + negative CVD
divergent = some TFs buying, others selling

Weight by volume (higher TF volume = more institutional)
```

**New outputs:** `ctf_orderflow_alignment` [-1, +1], `ctf_orderflow_conviction` [0, 1]

**Why it matters:** Institutional activity shows as aligned order flow across multiple timeframes. Divergent flow across TFs suggests retail noise or distribution. This is orthogonal to price-based momentum — pure order flow confirmation.

**Complexity:** Low. Uses existing I1 OFI/CVD outputs from `intel_*`.

---

### 7. Squeeze-Within-Expansion Divergence

**What:** Detect coiled-spring setups where one TF is compressed while others show volatility expansion.

**Logic sketch:**
```
squeeze_1m = BollingerSqueeze active on 1m
expansion_htf = vol_expansion on 4h + 1h

squeeze_1m + expansion_htf = "coiled spring" → breakout imminent
expansion_1m + squeeze_htf = "blow-off top" → exhaustion signal
all_squeezed = low vol across board → range-bound
all_expanded = high vol across board → trending
```

**New outputs:** `ctf_squeeze_expansion_divergence` [-1, +1], `ctf_vol_regime` (coiled_spring/blow_off/aligned_squeeze/aligned_expansion/mixed)

**Why it matters:** Timing precision from LTF (when will the move start?) + directional conviction from HTF (which way will it go?). This is a multi-TF timing signal.

**Complexity:** Low. Uses existing `BollingerSqueeze` + `vol_expansion` from `intel_*`.

---

## New Ideas: Cross-Asset Confluence

The platform has 50+ instruments across 6 asset classes, all subscribed and flowing through the pipeline. The confluence layer should leverage this.

### Data Availability

Already flowing through pipeline (zero new subscriptions needed):

| Asset Class | Instruments | Sectors |
|-------------|------------|---------|
| **Equity Index Futures** | ES, NQ, RTY, YM | equity_index |
| **FX** | EURUSD, GBPUSD, USDJPY, USDCHF | fx |
| **Crypto** | BTC, ETH | crypto |
| **Rate Futures** | ZN (10yr), ZF (5yr), ZB (30yr), ZT (2yr) | interest_rates |
| **VIX** | VX | volatility |
| **Energy** | CL (crude), NG (natgas), USO, XLE, OIH | energy |
| **Metals** | GC (gold), SI (silver), HG (copper) | metals |
| **Agriculture** | ZC (corn), ZS (soy), ZW (wheat) | agriculture |
| **Sector ETFs (11 GICS)** | XLK, XLE, XLF, XLI, XLU, XLRE, XLP, XLB, XLC, XLY, XLV | technology/energy/financials/... |
| **Factor ETFs** | MTUM, USMV, QUAL, VLUE | factor |
| **Broad Market** | SPY, QQQ, IWM, DIA | broad_market |
| **Credit** | HYG (high yield), LQD (investment grade) | credit |
| **Rates ETFs** | TLT (20yr), IEF (7-10yr), SHY (1-3yr) | rates |
| **International** | EFA (DM ex-US), VWO (EM), EEM (EM), FXI (China) | international/emerging_markets |
| **Specialty** | IBB (biotech), GDX (gold miners), SIL (silver miners), XHB (homebuilders) | biotech/gold_miners/homebuilders |

Potentially needed:
- VIX9D / VIX3M for term structure (not currently subscribed)
- DXY index (can synthesize from FX pairs: EURUSD, GBPUSD, USDJPY, USDCHF)

---

### 8. USD Strength Proxy (FX)

**What:** Composite USD strength from all FX pairs. Strong USD = risk-off for commodities, negative for EM, positive for rates.

**Logic sketch:**
```
usd_strength = normalize(
  1/EURUSD_change + 1/GBPUSD_change + USDJPY_change + USDCHF_change
) / 4

Interpretation:
  usd_strength > +1σ → risk-off regime (flight to USD)
  usd_strength < -1σ → risk-on regime (USD selling)
```

**New outputs:** `caf_usd_strength` [-1, +1], `caf_usd_regime` (risk_on/risk_off/neutral)

**Why it matters:** USD is the ultimate risk barometer. Strong USD coincides with equity selling, commodity weakness, EM stress. Every I7 plugin should know the USD regime.

**Complexity:** Low. Read FX OHLCV from bar history, compute normalized returns.

---

### 9. Yield Curve Shape (Rates)

**What:** Track the yield curve using rate futures. Steepening = growth expectations; flattening/inverting = recession risk.

**Logic sketch:**
```
spread_2y_10y = ZT_price_change - ZN_price_change  # inverted: price down = yield up
spread_2y_30y = ZT_price_change - ZB_price_change

curve_steepening = spread increasing over N bars
curve_flattening = spread decreasing over N bars
curve_inverted = short rates > long rates (ZT yield > ZB yield)
```

**New outputs:** `caf_yield_curve_slope` [-1, +1], `caf_yield_curve_regime` (steepening/flat/inverting)

**Why it matters:** The yield curve is the single best recession predictor. Curve inversion within the last 12 months should suppress trend-following confidence in equity indices.

**Complexity:** Low. Read rate futures OHLCV from bar history, compute spreads.

---

### 10. Flight-to-Quality Detection

**What:** Detect classic risk-off rotation: TLT up + SPY down + VIX up simultaneously.

**Logic sketch:**
```
tlt_return = TLT close change (bonds rising)
spy_return = SPY close change (equities falling)
vix_change = VX close change (volatility rising)

flight_score = (sign(tlt_return) + sign(-spy_return) + sign(vix_change)) / 3
If all 3 agree → strong flight-to-quality signal
```

**New outputs:** `caf_flight_to_quality` [-1, +1]

**Why it matters:** Flight-to-quality is the clearest risk-off signal. When bonds rally, equities sell, and VIX spikes simultaneously, the market is rotating defensively. I7 trend-following plugins should reduce exposure.

**Complexity:** Low. Read ETF/futures prices from bar history.

---

### 11. Credit Spreads (Stress Detection)

**What:** HYG vs LQD spread widening indicates credit stress, which precedes equity risk-off.

**Logic sketch:**
```
hyg_return = HYG close change (high yield bonds)
lqd_return = LQD close change (investment grade)
credit_spread_change = lqd_return - hyg_return

If credit_spread widening > 1.5σ → credit stress regime
```

**New outputs:** `caf_credit_stress` [-1, +1]

**Why it matters:** Credit markets lead equity markets. HY spread widening is an early warning signal for equity drawdowns. This is institutional-quality risk management.

**Complexity:** Low. Read ETF prices from bar history.

---

### 12. Risk-On / Risk-Off Sector Rotation

**What:** Detect defensive vs cyclical sector leadership. XLK/XLI leading = risk-on; XLU/XLRE/XLP leading = risk-off.

**Logic sketch:**
```
cyclical_momentum = avg(XLK, XLI, XLY, XLF) momentum_score
defensive_momentum = avg(XLU, XLRE, XLP, XLV) momentum_score
rotation_score = (cyclical_momentum - defensive_momentum) / normalize_factor

rotation > +1σ → risk-on (cyclical leadership)
rotation < -1σ → risk-off (defensive leadership)
```

**New outputs:** `caf_sector_rotation` [-1, +1], `caf_leading_sector` (cyclical/defensive/mixed)

**Why it matters:** Sector rotation reveals institutional positioning better than price alone. When institutions rotate into utilities and staples, they're positioning for a drawdown — regardless of what the equity index shows.

**Complexity:** Low. Read sector ETF prices from bar history, compute relative momentum.

---

### 13. Sector Momentum Rank

**What:** Rank all 11 GICS sectors by momentum. The leading sector reveals the market regime.

**Logic sketch:**
```
For each of {XLK, XLE, XLF, XLI, XLU, XLRE, XLP, XLB, XLC, XLY, XLV}:
  compute momentum_score (e.g., 20-bar return)

rank = sorted sectors by momentum
leader = rank[0]

If leader in {XLK, XLY} → aggressive risk-on
If leader in {XLU, XLP} → defensive risk-off
If leader in {XLE, XLF} → commodity/cyclical rotation
```

**New outputs:** `caf_sector_leader` (string), `caf_sector_breadth` [0, 1] (fraction of sectors positive)

**Why it matters:** Renaissance: *segment relentlessly*. The identity of the leading sector is a regime classifier. Different I7 plugins should be active depending on which sector leads.

**Complexity:** Medium. Requires reading 11 ETF prices + computing momentum per ETF.

---

### 14. Factor Rotation

**What:** MTUM (momentum) vs USMV (min vol) vs VLUE (value) leadership. Reveals whether the market rewards trending or mean-reversion.

**Logic sketch:**
```
momentum_factor = MTUM relative performance
value_factor = VLUE relative performance
minvol_factor = USMV relative performance

If momentum_factor > value_factor AND momentum_factor > minvol_factor:
  → trend regime (momentum strategies outperform)
If value_factor > momentum_factor:
  → mean-reversion regime (value strategies outperform)
If minvol_factor leading:
  → defensive regime (low vol outperforming)
```

**New outputs:** `caf_factor_regime` (trend/reversion/defensive/mixed)

**Why it matters:** When momentum factor outperforms, trend-following I7 plugins should get a confidence boost. When value/min-vol outperforms, mean-reversion plugins should be favored. This is a direct I7 confidence modifier.

**Complexity:** Low. Read 3 ETF prices from bar history.

---

### 15. Crypto Risk Sentiment

**What:** BTC/ETH as leading risk indicators. Crypto often leads equity moves at session open.

**Logic sketch:**
```
btc_momentum = BTC short-term momentum (e.g., 6 bars)
eth_momentum = ETH short-term momentum

crypto_risk = (btc_momentum + eth_momentum) / 2

If crypto_risk < -1σ → risk-off signal for equities at session open
If crypto_risk > +1σ → risk-on signal
```

**New outputs:** `caf_crypto_sentiment` [-1, +1]

**Why it matters:** Crypto trades 24/7. Overnight crypto moves are the first risk signal available before equity markets open. BTC dropping 2% overnight is a negative signal for ES at the open.

**Complexity:** Low. Read crypto OHLCV from bar history. Only useful as a leading indicator for equity index signals.

---

### 16. EM vs DM Divergence

**What:** EEM/EFA vs SPY relative performance. EM underperformance signals global risk-off.

**Logic sketch:**
```
em_vs_spy = EEM relative return vs SPY over N bars
dm_ex_us_vs_spy = EFA relative return vs SPY over N bars

If em_vs_spy < -1σ → global risk-off (capital fleeing EM)
If dm_ex_us_vs_spy < -1σ → US outperformance (safe haven rotation)
```

**New outputs:** `caf_em_divergence` [-1, +1]

**Why it matters:** EM is the "canary in the coal mine." EM selling before DM selling indicates global risk reduction, not idiosyncratic equity weakness.

**Complexity:** Low. Read ETF prices from bar history.

---

### 17. Correlation Stress Index

**What:** Rolling correlation between ES, GC, ZN, EURUSD, BTC. Correlation breakdown = regime shift.

**Logic sketch:**
```
Compute rolling 60-bar correlation matrix between:
  ES, GC (gold), ZN (10yr), EURUSD, BTC

baseline_correlation = 20-day average correlation
current_correlation = 60-bar window

stress = baseline_correlation - current_correlation
If stress > 2σ → correlation breakdown → regime shift in progress
```

**New outputs:** `caf_correlation_stress` [0, 1]

**Why it matters:** Normally uncorrelated assets becoming correlated is a stress signal (everything sells off together). Correlation breakdown precedes many market dislocations.

**Complexity:** Medium. Requires cross-asset price alignment + rolling correlation computation.

---

### 18. Commodity-Currency Feedback

**What:** GC + EURUSD correlation pattern. Gold up + euro up = USD weakness + risk-off hedge seeking.

**Logic sketch:**
```
gold_return = GC close change
eur_return = EURUSD close change

If both positive → USD weakness regime (commodities + FX aligned against USD)
If gold up + EUR down → safe-haven demand (flight to gold, not FX)
If gold down + EUR up → USD weakness without commodity support
```

**New outputs:** `caf_commodity_fx_regime` (usd_weak/usd_strong/safe_haven/neutral)

**Why it matters:** The interplay between commodities and FX reveals the *reason* behind USD moves. Weak USD + strong gold = structural USD selling. Strong gold + strong USD = panic buying.

**Complexity:** Low. Read GC + EURUSD from bar history.

---

### 19. Cross-Asset Lead-Lag Detection

**What:** Which asset leads moves? If ES moves first and NQ follows 2-3 bars later, ES is the leader.

**Logic sketch:**
```
For pair (ES, NQ):
  Compute cross-correlation at lags 0-5
  peak_lag = lag with highest correlation

If ES leads NQ by 2 bars → ES is the leader
If NQ leads ES → NQ is the leader

Track lead-lag ratio over rolling window:
  Direction changes in leadership = market structure shift
```

**New outputs:** `caf_equity_leader` (ES/NQ/RTY/none), `caf_lead_lag_bars` (int)

**Why it matters:** The leading index reveals market structure. If small caps (RTY) start leading large caps (ES), it signals broadening participation. If NQ leads, tech is driving.

**Complexity:** Medium. Requires cross-correlation computation at multiple lags.

---

### 20. VIX Term Structure (Data Dependency)

**What:** VX9D vs VIX spread. Short-term vol premium vs longer-term = near-term fear.

**Logic sketch:**
```
vix9d_vix_spread = VIX9D - VIX

If spread > 0 → near-term fear elevated (term inversion)
If spread < 0 → calm near-term, elevated longer-term (typical)
Extreme positive spread → event risk / earnings / Fed meeting
```

**New outputs:** `caf_vix_term_structure` [-1, +1]

**Data requirement:** VIX9D subscription (not currently available). Can approximate using short-term VIX futures vs VX.

**Complexity:** Medium (new data source needed).

---

### 21. Intraday Liquidity Regime

**What:** Proxy market liquidity from volume patterns + spread width. Thin liquidity = wider stops needed, lower confidence.

**Logic sketch:**
```
volume_percentile = current bar volume vs 20-day volume profile
time_of_day_factor = RTH first/last hour vs midday

If volume_percentile < 20th + midday → thin liquidity regime
If volume_percentile > 80th + first hour → high liquidity regime
```

**New outputs:** `caf_liquidity_regime` (thin/normal/high)

**Why it matters:** Thin liquidity means wider spreads, worse fills, less reliable signals. I7 plugins should reduce position sizing in thin liquidity and increase in high liquidity.

**Complexity:** Low. Uses existing volume data + session context.

---

## Unified Multi-Dimensional Scoring

### I6 Output Structure (Proposed Full Expansion)

```python
{
    # ---- Cross-TF Confluence (existing + new) ----
    "ctf_score": float,                        # Composite TF alignment
    "ctf_trend_alignment": float,              # Trend direction agreement
    "ctf_structure_alignment": float,          # Swing pattern agreement
    "ctf_regime_agreement": float,             # Regime consistency
    "ctf_timeframes_aligned": float,           # Count of aligned TFs
    "ctf_highest_aligned_tf": float,           # Highest aligned TF (minutes)
    "ctf_momentum_divergence": float,          # NEW: HTF vs LTF momentum shape
    "ctf_momentum_regime": str,                # NEW: aligned/pullback/bounce/mixed
    "ctf_squeeze_expansion_divergence": float, # NEW: Coiled-spring vs blow-off
    "ctf_vol_regime": str,                     # NEW: coiled_spring/blow_off/...
    "ctf_orderflow_alignment": float,          # NEW: OFI/CVD TF agreement
    "ctf_orderflow_conviction": float,         # NEW: Volume-weighted OFI strength
    "ctf_sr_confluence": float,                # NEW: Multi-TF S/R agreement
    "ctf_regime_combo": str,                   # NEW: Specific regime combination

    # SMC cross-TF (existing)
    "i6_smc_bos_alignment": float,
    "i6_fvg_tf_alignment": float,
    "i6_ob_tf_alignment": float,
    "i6_i2_event_score": float,
    # Per-TF scores (existing)
    "i6_fvg_tf_{1m..1d}": float,
    "i6_ob_tf_{1m..1d}": float,

    # ---- Cross-Asset Confluence (all new) ----
    "caf_usd_strength": float,                 # USD composite strength
    "caf_usd_regime": str,                     # risk_on/risk_off/neutral
    "caf_yield_curve_slope": float,            # Curve steepening/flattening
    "caf_flight_to_quality": float,            # Bond up + equity down + VIX up
    "caf_credit_stress": float,                # HYG vs LQD spread
    "caf_sector_rotation": float,              # Cyclical vs defensive leadership
    "caf_sector_leader": str,                  # Leading sector name
    "caf_sector_breadth": float,               # Fraction of sectors positive
    "caf_factor_regime": str,                  # trend/reversion/defensive
    "caf_crypto_sentiment": float,             # BTC/ETH leading indicator
    "caf_em_divergence": float,                # EM vs DM relative performance
    "caf_correlation_stress": float,           # Cross-asset correlation breakdown
    "caf_commodity_fx_regime": str,            # USD/Gold/FX interaction
    "caf_equity_leader": str,                  # Which index leads
    "caf_liquidity_regime": str,               # thin/normal/high
}
```

### How I7 Should Consume

Each I7 plugin should read the I6 dimensions relevant to its regime type:

| I7 Type | Key I6 Inputs | Usage |
|---------|---------------|-------|
| Trend-following | `ctf_trend_alignment`, `caf_factor_regime`, `caf_sector_rotation` | Confidence boost when TFs agree + momentum factor leading + cyclical sector leading |
| Mean-reversion | `ctf_momentum_divergence` (pullback), `caf_credit_stress`, `caf_flight_to_quality` | Fire during pullbacks in uptrends; suppress during credit stress |
| SMC-based | `i6_fvg_tf_alignment`, `i6_ob_tf_alignment`, `caf_usd_strength` | Higher confidence when FVG/OB aligned across TFs + USD regime supportive |
| Breakout | `ctf_squeeze_expansion_divergence`, `caf_liquidity_regime`, `caf_sector_breadth` | Fire on coiled-spring + high liquidity + broad participation |
| Volatility | `caf_vix_term_structure`, `ctf_vol_regime`, `caf_yield_curve_slope` | Vol expansion setups timed to VIX regime + curve shape |

---

## Implementation Roadmap

Prioritized by signal leverage × data availability × complexity.

### Tier 1: Zero new data, high leverage, low complexity

These plugins only read data already flowing through the pipeline and produce immediate I7 value.

| # | Plugin | Idea | New Fields | Est. |
|---|--------|------|------------|------|
| 1 | CrossTFMomentumDivergence | #4 | 2 | 1-2d |
| 2 | CrossTFSRConfluence | #1 | 2 | 1d |
| 3 | CrossTFRegimeAgreement | #5 | 2 | 1d |
| 4 | SqueezeExpansionDivergence | #7 | 2 | 1d |
| 5 | CrossTFOrderFlowAlignment | #6 | 2 | 1d |

**Validation:** Build one, track to `signal_ledger`, wait 7-30 days, analyze. If p < 0.05, keep. Build next.

### Tier 2: Cross-asset from existing data, medium complexity

These read prices from bar history for non-signal instruments (sector ETFs, FX, rate futures, etc.)

| # | Plugin | Idea | New Fields | Est. |
|---|--------|------|------------|------|
| 6 | CrossAssetUSDStrength | #8 | 2 | 1-2d |
| 7 | CrossAssetFlightToQuality | #10 | 1 | 1d |
| 8 | CrossAssetSectorRotation | #12, #13 | 3 | 2d |
| 9 | CrossAssetFactorRegime | #14 | 1 | 1d |
| 10 | CrossAssetCreditStress | #11 | 1 | 1d |
| 11 | CrossAssetCryptoSentiment | #15 | 1 | 1d |

**Dependency:** Requires pipeline to subscribe to non-signal instruments (sector ETFs, FX, rates) AND run intelligence pipeline on them (not just the primary signal symbol). Currently `intelligence_pipeline_agent` only processes bars for subscribed contracts. Need to either: (a) subscribe all instruments to the pipeline, or (b) create a lightweight cross-asset context service that computes simplified metrics.

### Tier 3: Higher complexity or new data

| # | Plugin | Idea | New Fields | Est. |
|---|--------|------|------------|------|
| 12 | CrossTFVolumeProfileConfluence | #3 | 2 | 2d |
| 13 | CrossTFCascadeDetection | #2 | 3 | 2-3d |
| 14 | CrossAssetCorrelationStress | #17 | 1 | 2d |
| 15 | CrossAssetLeadLag | #19 | 2 | 2-3d |
| 16 | CrossAssetYieldCurve | #9 | 2 | 1-2d |
| 17 | CrossAssetCommodityFX | #18 | 1 | 1d |
| 18 | CrossAssetEMDivergence | #16 | 1 | 1d |
| 19 | CrossAssetVIXTermStructure | #20 | 1 | 2d + new data |
| 20 | IntradayLiquidityRegime | #21 | 1 | 1d |

### Key Architecture Decision: Cross-Asset Data Flow

Currently, `intelligence_pipeline_agent` processes bars per-symbol and caches intelligence for cross-TF injection (`frames["intel_*"]`). Cross-asset confluence needs intelligence from *other symbols*, not just other timeframes.

**Option A: Expand `frames["intel_*"]` to include cross-symbol data**
- Cache intelligence from all running symbols (not just current symbol's TFs)
- I6 plugins read `frames["intel_ES"]`, `frames["intel_XLK"]`, etc.
- Simple but increases memory and frame dict size

**Option B: Dedicated cross-asset context injection (current pattern)**
- Extend the existing `frames["cross_asset"]` pattern (used by `ctx_CrossAssetContext`)
- A service computes cross-asset metrics and publishes to a Kafka topic
- Pipeline agent injects into frames
- Decoupled but requires new service/topic per metric

**Option C: Read directly from bar history**
- I6 plugins access `self._bar_history` for other symbols
- No Kafka intermediary, compute on-demand
- Simplest but couples I6 to bar history internals

**Recommendation:** Start with Option C for Tier 1 (cross-TF, already has `intel_*`). For Tier 2 cross-asset, use Option A — extend the intelligence cache to include cross-symbol data. This is the natural evolution of the existing `intel_*` pattern.

---

## Design Principle: Gradient-First Scoring

**Never binarize a continuous signal.** (Related todo: `028-switch-ic-from-binary-to-continuous-pnl-r.md`)

All I6 confluence outputs must be continuous gradients in [-1, +1] or [0, 1]. Never use step functions or hard thresholds.

**Bad (binary):**
```python
if spread_z > 2.0:
    return 1.0
return 0.0
```

**Good (gradient):**
```python
# Continuous z-score scaling with soft saturation
return np.tanh(spread_z / 2.0)
```

**Why:** Binary scoring discards magnitude information (the same Renaissance principle as "never drop data that could contain signal"). A credit spread at 3σ is *much* more stressed than one at 2.1σ, but binary scoring treats them identically. This also causes zero-variance failures in downstream IC computation when all values are the same.

**Gradient techniques for I6 plugins:**
- **Z-score scaling:** `tanh(z / threshold)` — soft saturation, continuous
- **Proximity decay:** `1.0 / (distance + 1)` — the existing I6 plugin already uses this
- **Weighted agreement fraction:** `sum(weights * signs) / sum(weights)` — not count of agreements
- **Rank-based:** `(rank - median_rank) / (max_rank - median_rank)` — for sector/factor rotation
- **Percentile-based:** `(value - rolling_min) / (rolling_max - rolling_min)` — normalizes any range to [0, 1]

The existing `CrossTimeframeConfluencePlugin` already follows this pattern (weighted composites, proximity decay). New plugins should match.

---

## Renaissance Principle Alignment

| Principle | How I6 Expansion Satisfies |
|-----------|-----------------------------|
| **Instrument everything** | Every confluence dimension captured as measurable field |
| **Let the system run** | Confluence scores feed signal aggregator without manual override |
| **Earn the right through proof** | Build 1 at a time, track, validate with p < 0.05 before promoting |
| **Segment relentlessly** | Confluence across TF, USD regime, yield curve, sectors, credit = 5-way segmentation |
| **Data quality over model complexity** | Simple, interpretable scoring (agreement fractions, z-scores) |
| **Degrade gracefully** | Missing data → partial confluence, not zero. FX-only instruments skip equity-specific metrics |
| **Never drop data that could contain signal** | Every confluence score is a labeled training feature for future ML |

---

## Open Questions

1. **Cross-symbol intelligence caching:** Should we extend `frames["intel_*"]` to include other symbols, or use a separate injection pattern?
2. **ETF intelligence pipeline:** Should sector ETFs and FX pairs run through the full I1-I7 pipeline, or just I1-I4 (no signals needed)?
3. **Memory budget:** Caching intelligence for 50+ instruments × 6 TFs = 300+ intelligence dicts. What's the memory impact?
4. **Correlation computation frequency:** Per-bar (expensive) or every N bars? Rolling window size?
5. **Dashboard visualization:** How to show multi-dimensional confluence? Radar chart? Heatmap? Separate panels per dimension?
6. **Schema growth:** I6Confluence could grow from 16 to 40+ fields. Should we split into sub-schemas (I6TFConfluence, I6AssetConfluence)?

---

## Related Documents

- `renaissance-i7-i8-refinement.md` — Source of many original ideas
- `regime-adaptive-trading.md` — Cross-TF synchronization, regime-specific models

- `src/intelligence/confluence/cross_timeframe.py` — Current I6 implementation
- `src/intelligence/schemas.py` — I6Confluence schema (16 fields)
- `services/cross_asset_service.py` — Cross-asset spread computation
- `services/intelligence_pipeline_agent.py` — Unified pipeline with 4-wave execution
- `src/config/settings.py` — All instrument definitions (50+ instruments)
