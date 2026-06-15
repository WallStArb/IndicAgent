# Signal Replay Analysis — 2026-06-14

**Signals:** 1,446,148 | **Outcomes:** 1,490,114 | **Analyzed:** 765,051 (with pnl_r)

## Overall Performance

| Metric | Value |
|--------|-------|
| Win rate | 18.06% |
| Avg pnl_r | -0.2776 |
| Stopped at entry | 364K (47.6%) |
| Stopped in trade | 289K (37.8%) |
| Hit target | 112K (14.6%) |

## Critical Finding: Massive Asset Class Split

### Forex (EURUSD, USDCHF) — PROFITABLE ✓

| Setup | Win Rate | Avg pnl_r | Total |
|-------|----------|-----------|-------|
| trad_GapAnalysisSetup | 50.48% | +0.044 | 7,753 |
| trad_DivergenceStack | 48.11% | +0.078 | 37,657 |
| trad_CVDDivergence | 47.39% | +0.065 | 32,596 |
| trad_CHoCHReversal | 46.41% | +0.167 | 5,201 |
| trad_LiquiditySweepReclaim | 46.26% | +0.056 | 9,479 |

**Forex avg: 47-50% win rate, +0.04 to +0.17 pnl_r**

### Equities/ETFs — UNPROFITABLE ✗

| Setup | Win Rate | Avg pnl_r | Total |
|-------|----------|-----------|-------|
| trad_FVGFill | 8.93% | -0.647 | 31,337 |
| trad_SqueezeExpansion | 11.67% | -0.467 | 6,803 |
| trad_GapAnalysisSetup | 13.28% | -0.423 | 139,485 |
| trad_DivergenceStack | 13.20% | -0.422 | 112,211 |
| trad_CVDDivergence | 19.36% | -0.054 | 51,812 |
| trad_TrendFollowing | 22.80% | +0.055 | 2,355 |

**Equity avg: 8-22% win rate, -0.05 to -0.65 pnl_r**

## Instrument Breakdown

| Symbol | Type | Win Rate | Avg pnl_r |
|--------|------|----------|-----------|
| EURUSD | Forex | 63.60% | +0.267 |
| USDCHF | Forex | 64.42% | +0.237 |
| USDJPY | Forex | 14.39% | -0.380 |
| SPY | Equity | 12.09% | -0.410 |
| QQQ | Equity | 13.50% | -0.345 |
| IWM | Equity | 13.31% | -0.351 |
| DIA | Equity | 13.64% | -0.248 |

## Timeframe Breakdown

| TF | Win Rate | Avg pnl_r | Stopped Entry |
|----|----------|-----------|---------------|
| 1m | 20.14% | -0.255 | 47% |
| 5m | 15.39% | -0.281 | 48% |
| 15m | 18.03% | -0.296 | 48% |
| 1h | 16.00% | -0.345 | 49% |

All timeframes negative; 1m performs best.

## Root Cause Analysis

### 1. Asset Class Incompatibility
**Problem:** Setup logic optimized for forex (24/5, continuous, lower volatility) fails on equities (trading hours, gaps, higher volatility).

**Evidence:**
- Same setup has 48% win rate on forex, 13% on equities
- Zone/stop sizing that works for currency pairs is too tight for equity moves

### 2. Stopped at Entry Crisis
**Problem:** 47.6% of all signals stopped at entry due to:
- Tiny zones (1-6 cents for ETFs)
- Entry placement at zone edge
- Stop calculated from zone edge, not entry

**Impact:**
- 364K stopped_at_entry (47.6% of outcomes)
- Worse on equities (50%+) than forex (40%)

### 3. Setup-Specific Issues

**Worst performers:**
- trad_FVGFill: 8.93% win rate, -0.647 avg pnl_r
- trad_SqueezeExpansion: 11.67% win rate, -0.467 avg pnl_r

**Best performers:**
- trad_TrendFollowing (equity): 22.80% win rate, +0.055 avg pnl_r
- trad_CHoCHReversal (forex): 46.41% win rate, +0.167 avg pnl_r

## Recommendations

1. **Asset class separation:** Create forex-specific and equity-specific setup variants
2. **Zone sizing:** Implement minimum zone width based on ATR and asset class
3. **Stop calculation:** Calculate stop distance from ENTRY, not zone edge
4. **Setup retirement:** Consider retiring trad_FVGFill and trad_SqueezeExpansion on equities
5. **USDJPY investigation:** Why does USDJPY perform like equities (14% win rate) vs EURUSD/USDCHF (64%)?

## Next Steps

1. Review/fix stop and zone logic (todo: 2026-06-14-review-stop-zone-logic.md)
2. Investigate USDJPY anomaly
3. Consider asset-class-specific parameter tuning
4. Evaluate trad_TrendFollowing for broader deployment (only profitable equity setup)
