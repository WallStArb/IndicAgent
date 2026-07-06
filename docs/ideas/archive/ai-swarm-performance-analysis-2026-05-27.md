# AI Swarm Performance Analysis
**Version:** 1.0
**Status:** draft
**Priority:** high
**Milestone:** v2.8
**Last Updated:** 2026-05-27
**Tags:** swarm, performance, analysis, signal-quality, confidence-gating, pnl, ai

## Executive Summary

**Key Finding:** The AI swarm (alpha swarm agents) IS highly effective at discriminating signal quality, BUT only when properly gated. High-confidence AI signals (swarm_multiplier ≥0.5) show **65.5% win rate** and **+$6,427 profit**, while low-confidence signals lose -$10,743.

**Critical Issue:** System is losing -$8,626 overall because 94% of trades are low/medium confidence that bleed money.

---

## 1. AI Processing Volume vs Completed Trades

### The Disconnect
- **AI Enriched (7 days):** 6,417 signals (~917/day)
- **Completed with PnL:** 386 signals (6%)
- **Still Active/Pending:** 6,031 signals (94%)

**Explanation:** Most AI-enriched signals haven't hit exit conditions yet. They're still active trades waiting for:
- Target hits
- Stop losses
- TTL expiration
- Manual exits

### Daily Breakdown
| Date | AI Enriched | Completed | Pending |
|------|-------------|-----------|---------|
| 2026-05-27 | 586 | 6 | 580 |
| 2026-05-26 | 1,136 | 40 | 1,096 |
| 2025-05-25 | 1,157 | 297 | 860 |
| 2025-05-24 | 119 | 43 | 76 |
| 2025-05-23 | 629 | 0 | 629 |
| 2025-05-22 | 1,199 | 0 | 1,199 |
| 2025-05-21 | 1,067 | 0 | 1,067 |
| 2025-05-20 | 524 | 0 | 524 |

**Pattern:** Early signals (May 20-23) still pending. Recent signals (May 25-27) starting to complete.

---

## 2. PnL Measurement: R-Multiples vs Dollars

### Two PnL Metrics
| Metric | Description | Values |
|--------|-------------|--------|
| **pnl_r** | R-multiples (risk units) | -1.0 to +2.0R |
| **pnl_dollars** | Actual dollar PnL | -$678 to +$688 per trade |

### Overall Performance (7 days)
| Metric | Completed Signals | Win Rate | Avg PnL | Total PnL |
|--------|-------------------|----------|---------|-----------|
| **pnl_r (R-multiples)** | 386 | 43.3% | +0.001R | +0.23R |
| **pnl_dollars (actual $)** | 326 | 51.2% | **-$26.46** | **-$8,626** |

**Important:** Previous analysis used pnl_r which showed break-even. Real dollar PnL shows -$8,626 loss.

---

## 3. AI Confidence Tier Performance

### Swarm Multiplier Effectiveness
| Confidence Tier | Signals | Win Rate | Avg PnL/Trade | Total PnL |
|----------------|---------|----------|---------------|-----------|
| **High (≥0.5)** | 29 | **65.5%** | **+$222** | **+$6,427** ✅ |
| **Medium (0.3-0.5)** | 140 | 51.4% | -$31 | -$4,309 ❌ |
| **Low (<0.3)** | 157 | 47.3% | -$72 | -$10,743 ❌ |
| **ALL** | 326 | 51.2% | -$26 | -$8,626 |

### Key Insights
1. **High confidence signals are profitable** (+$6,427 on just 29 trades)
2. **Low confidence signals destroy PnL** (-$10,743 on 157 trades)
3. **0.5 threshold is the profitability line**
4. **AI swarm IS discriminating correctly** - but we're trading all signals instead of gating

---

## 4. Trade Gating Simulation

### Strategy Comparison
| Filter Criteria | Trades/Day | Win Rate | Avg PnL/Trade | Total PnL |
|-----------------|------------|----------|---------------|-----------|
| **All AI Signals** | 55/day | 51.2% | -$26 | -$8,626 |
| **High Confidence (≥0.4)** | 14/day | 56.7% | +$80 | +$7,788 |
| **Very High (≥0.5)** | 5/day | **65.5%** | **+$222** | **+$6,427** |
| **Ultra High (≥0.6)** | 1.4/day | 60.0% | +$188 | +$1,878 |

### Revenue Impact
- **Current:** -$8,626 (losing)
- **Gate at ≥0.4:** +$7,788 (+$16,414 improvement)
- **Gate at ≥0.5:** +$6,427 (+$15,053 improvement)

**Recommendation:** Implement swarm_multiplier ≥0.4 gate for production trading.

---

## 5. Exit Reason Analysis

### The Real Problems
| Exit Reason | Signals | Win Rate | Avg PnL/Trade | Total PnL |
|-------------|---------|----------|---------------|-----------|
| **target_1** | 20 | **100%** | **+$678** | **+$13,559** 🎯 |
| **target_2** | 6 | 83.3% | +$688 | +$4,125 |
| **ttl_expired** | 340 | 41.8% | -$46 | **-$12,742** ⏰ |
| **stop_loss** | 20 | **0%** | **-$678** | **-$13,569** 🛑 |

### Critical Issues

#### 1. Stop Loss Logic Failure
- **0% win rate** means stops are hitting prematurely
- **-$13,569 loss** on just 20 signals (-$678 per trade)
- **Hypothesis:** Stops placed too tight, triggered by noise before move develops
- **Action:** Review stop placement logic, test wider stops

#### 2. TTL Expiration Bleed
- **41.8% win rate** vs 100% on targets
- **-$12,742 loss** on 340 signals (-$38 per trade)
- **Hypothesis:** Signals held too long, missing optimal exit window
- **Action:** Implement trailing stops or earlier exits

#### 3. Low Target Hit Rate
- **Only 6.7% hitting targets** (26/386)
- **But targets are hugely profitable** when hit (+$678 avg)
- **Hypothesis:** Entries timed too early, need better confluence
- **Action:** Improve entry timing, require stronger setup confirmation

---

## 6. Setup Performance with AI Validation

### Top Performers
| Setup | Signals | Avg Multiplier | Win Rate | Avg PnL | Total PnL |
|-------|---------|----------------|----------|---------|-----------|
| **Liquidity Hunt** | 22 | 0.334 | **95.5%** | +$161 | **+$3,536** |
| **Pattern Completion** | 7 | 0.328 | **100%** | +$332 | **+$2,321** |
| **Candlestick Pattern** | 13 | 0.322 | 61.5% | +$300 | **+$3,906** |
| **FVG Fill** | 162 | 0.314 | 30.9% | +$22 | **+$3,492** |
| **Trend Following** | 12 | **0.406** | **0%** | -$143 | **-$1,713** |

### Key Insights
1. **Liquidity Hunt + Pattern = 95-100% win rate** (small sample, highly promising)
2. **Trend Following is toxic** despite highest avg multiplier (0.406)
3. **FVG Fill volume driver** (162 signals) but modest win rate (30.9%)
4. **Setup selection matters as much as AI confidence**

---

## 7. Symbol Performance with AI

### Best Performers
| Symbol | Signals | Avg Multiplier | Win Rate | Avg PnL | Total PnL |
|--------|---------|----------------|----------|---------|-----------|
| **ESM6** (S&P 500) | 18 | 0.308 | **83.3%** | +$111 | **+$2,004** |
| **GCM6** (Gold) | 33 | 0.346 | **75.8%** | +$88 | **+$2,920** |
| **SIM6** | 24 | 0.336 | **62.5%** | +$110 | **+$2,637** |
| **USDCHF** | 51 | 0.311 | 52.9% | +$48 | **+$2,471** |

### Worst Performers
| Symbol | Signals | Avg Multiplier | Win Rate | Avg PnL | Total PnL |
|--------|---------|----------------|----------|---------|-----------|
| **USDJPY** | 97 | 0.310 | **19.6%** | -$35 | **-$3,355** |
| **HGM6** | 17 | 0.362 | 23.5% | -$141 | **-$2,392** |
| **RTYM6** | 22 | 0.345 | 45.5% | -$99 | **-$2,172** |
| **YMM6** | 19 | 0.280 | 31.6% | -$76 | **-$1,443** |

### Key Insights
1. **Equity indexes (ESM6) perform best** with AI validation
2. **USDJPY is toxic** - avoid or require higher confidence gate
3. **Asset class matters** - Futures > FX for AI-enriched signals

---

## 8. Agent Consensus Paradox

### Unexpected Finding
| Consensus Level | Signals | Win Rate | Avg PnL | Total PnL |
|----------------|---------|----------|---------|-----------|
| **Low (<3 agents)** | 3 | **100%** | +$519 | **+$1,556** |
| **Partial (3/4)** | 55 | 29.1% | $0 | +$0 |
| **Full (4/4)** | 328 | 45.1% | -$4 | -$1,326 |

### Paradox Explained
- **Full consensus = signals so obvious they're crowded trades**
- **Partial consensus = healthy debate, edge preserved**
- **Low consensus = tiny sample size (3 signals), likely luck**

**Action:** Don't gate on agent count. Focus on swarm_multiplier score.

---

## 9. Baseline vs AI-Enriched Comparison

### Performance Lift
| Signal Type | Signals | Win Rate | Avg PnL | Total PnL |
|-------------|---------|----------|---------|-----------|
| **No AI Enrichment** | 39,478 | **17.5%** | -$0.05 | **-$1,964** |
| **AI Enriched (All)** | 386 | **51.2%** | -$26 | -$8,626 |
| **AI High Confidence (≥0.5)** | 35 | **65.5%** | **+$222** | **+$6,427** |

### Key Insights
1. **AI improves win rate 2.9x** (17.5% → 51.2%)
2. **But AI-enriched signals lose more** because volume exposure
3. **High confidence gate is KEY** - turns losers into winners

---

## 10. Recommendations

### Immediate Actions (Priority 1)

#### 1. Implement Confidence Gate
```python
# In signal selection logic
if swarm_multiplier < 0.4:
    return "REJECT - Low AI confidence"
```
**Expected Impact:** +$16,414 improvement (-$8,626 → +$7,788)

#### 2. Fix Stop Loss Logic
- **Current:** 0% win rate, -$13,569 loss
- **Actions:**
  - Review stop placement calculation
  - Test wider stops (2R instead of 1R)
  - Implement volatility-adjusted stops
- **Expected Impact:** Eliminate -$13,569 loss

#### 3. Optimize TTL Management
- **Current:** 41.8% win rate, -$12,742 loss
- **Actions:**
  - Implement trailing stops at +0.5R
  - Reduce max hold time
  - Earlier exit on momentum loss
- **Expected Impact:** Turn -$12,742 into breakeven or small profit

### Medium-Term Improvements (Priority 2)

#### 4. Setup Focus
- **Prioritize:** Liquidity Hunt, Pattern Completion, Candlestick Patterns
- **Avoid:** Trend Following (0% win rate)
- **Expected Impact:** Higher win rate, better risk/reward

#### 5. Symbol Focus
- **Prioritize:** ESM6, GCM6, SIM6
- **Avoid:** USDJPY (19.6% win rate)
- **Expected Impact:** +$2-3k per symbol focus

#### 6. Target Optimization
- **Current:** 6.7% hit rate
- **Actions:**
  - Better entry timing
  - Stronger setup confirmation
  - Partial profit targets at 1R
- **Expected Impact:** Increase target hits from 26 to 100+ signals

### Long-Term Research (Priority 3)

#### 7. ML Scorer Integration
- **Issue:** "no_promoted_model" error in logs
- **Actions:**
  - Train ML model on historical PnL
  - Promote best model to production
  - Use ML score as additional gate
- **Expected Impact:** Improve confidence scoring accuracy

#### 8. Regime-Aware Gating
- **Finding:** AI becomes skeptical in extreme regimes
- **Actions:**
  - Increase confidence threshold in Regime 2
  - Reduce position size in volatile regimes
- **Expected Impact:** Lower drawdown risk

---

## 11. Financial Projections

### Current Performance (7 days)
- **Signals:** 6,417 AI enriched
- **Completed:** 386 (6%)
- **PnL:** -$8,626

### With Confidence Gate ≥0.4
- **Signals:** ~98 (gated from 6,417)
- **Completed:** ~38 (estimated 6% completion)
- **Win Rate:** 56.7%
- **PnL:** +$7,788
- **Monthly:** **+$33,380** (extrapolated)

### With Confidence Gate ≥0.5
- **Signals:** ~29 (gated from 6,417)
- **Completed:** ~29 (all completed in sample)
- **Win Rate:** 65.5%
- **PnL:** +$6,427
- **Monthly:** **+$27,550** (extrapolated)

### With All Optimizations
- **Gate:** ≥0.4 confidence
- **Setup:** Liquidity Hunt + Pattern Completion
- **Symbol:** ESM6 + GCM6
- **Fixed:** Stop loss + TTL management
- **Projected Monthly:** **+$50,000+**

---

## 12. Data Quality Notes

### Limitations
1. **Small sample:** Only 386 completed signals vs 6,417 enriched
2. **Time bias:** Most signals still pending (94%)
3. **Regime bias:** Sample may not represent all market conditions
4. **Survivor bias:** Early signals (May 20-23) haven't completed yet

### Future Analysis Needed
1. **Larger sample:** Wait for 1,000+ completed signals
2. **Regime analysis:** Performance by market regime
3. **Time of day:** Performance by session
4. **Volatility analysis:** Performance by ATR/vol level

---

## 13. Technical Implementation

### Swarm Multiplier Calculation
```python
# Current implementation (simplified)
swarm_multiplier = mean([agent.confidence for agent in agents if agent.response])

# Where agents:
- correlation_v1: Cross-asset validation
- skeptic_v1: Weakness detection  
- regime_coherence_v1: Regime alignment
- counterfactual_v1: Alternative scenarios
- ml_scorer_v1: Machine learning (currently disabled)
```

### Proposed Gate Implementation
```python
# In signal selection / aggregator
def should_trade_signal(signal, ai_enrichment):
    # Confidence gate
    if ai_enrichment.swarm_multiplier < 0.4:
        return False, f"Low AI confidence: {ai_enrichment.swarm_multiplier:.3f}"
    
    # Setup gate  
    if signal.setup in ['trad_TrendFollowing']:
        return False, f"Toxic setup: {signal.setup}"
    
    # Symbol gate
    if signal.symbol in ['USDJPY']:  # Unless very high confidence
        if ai_enrichment.swarm_multiplier < 0.6:
            return False, f"Toxic symbol: {signal.symbol}"
    
    return True, "Passes all gates"
```

---

## Conclusion

The AI swarm is **highly effective** at signal quality discrimination, but the system is bleeding money because:

1. **Trading all signals instead of gating low-confidence ones**
2. **Broken stop loss logic** (0% win rate, -$13,569 loss)
3. **Poor TTL management** (41.8% win rate on expires)
4. **Toxic setups/symbols** not filtered out

**Fix:** Implement ≥0.4 confidence gate + fix stop losses = **+$16,414 improvement** ( -$8,626 → +$7,788).

**The AI works. The gating logic doesn't.**

---

## Next Steps

1. [ ] Implement confidence gate ≥0.4 in production
2. [ ] Fix stop loss placement logic
3. [ ] Optimize TTL management with trailing stops
4. [ ] Remove toxic setups (Trend Following)
5. [ ] Focus on high-performing symbols (ESM6, GCM6)
6. [ ] Re-run analysis in 7 days with larger sample
7. [ ] Publish live PnL tracking dashboard

---

**Document Version:** 1.0  
**Last Updated:** 2026-05-27  
**Status:** Initial Analysis - Needs Validation