# Replay Patterns Investigation

**Created:** 2026-06-14
**Priority:** HIGH
**Context:** 1.49M signal outcomes analyzed from replay

## Patterns/Anomalies to Investigate

### 1. USDJPY Anomaly — HIGH PRIORITY
**Observation:** USDJPY performs like equities, not forex
- EURUSD: 63.60% win rate, +0.267 avg pnl_r
- USDCHF: 64.42% win rate, +0.237 avg pnl_r
- USDJPY: 14.39% win rate, -0.380 avg pnl_r (same as equities)

**Questions:**
- Why does USDJPY cluster with equities despite being a forex pair?
- Liquidity/spread differences?
- Volatility profile mismatch?
- Timezone/liquidity timing issues?
- Data quality issue for USDJPY bars?

**Investigation:**
- Compare USDJPY volatility characteristics to EURUSD/USDCHF
- Check USDJPY spread/fills data quality
- Analyze USDJPY by time of day (Asian session vs London/NY)
- Verify USDJPY bar data completeness/gaps

---

### 2. Asset Class Split Invariance — HIGH PRIORITY
**Observation:** Same setups have radically different performance on forex vs equities
- trad_DivergenceStack: 48.11% (forex) vs 13.20% (equity)
- trad_GapAnalysisSetup: 50.48% (forex) vs 13.28% (equity)
- trad_CVDDivergence: 47.39% (forex) vs 19.36% (equity)

**Questions:**
- Is this a fundamental incompatibility or parameter tuning?
- Are equity zones too narrow for the volatility?
- Are equity stops too tight relative to ATR?
- Is the entry logic incompatible with equity market structure (gaps, opens)?

**Investigation:**
- Compare zone width/ATR ratios between forex and equities
- Analyze stop distance as % of ATR by asset class
- Check if equity gaps cause immediate stop-outs
- Review entry placement relative to zone edges by asset class

---

### 3. trad_TrendFollowing Outlier — MEDIUM PRIORITY
**Observation:** Only profitable equity setup
- trad_TrendFollowing: 22.80% win rate, +0.055 avg pnl_r (equity)
- All other equity setups: 8-22% win rates, -0.05 to -0.65 pnl_r

**Questions:**
- What makes TrendFollowing different on equities?
- Does it have wider zones/better stops?
- Is it firing less frequently (selectivity)?
- Is the logic fundamentally different (momentum vs mean reversion)?

**Investigation:**
- Compare trad_TrendFollowing parameters to other equity setups
- Analyze trad_TrendFollowing zone width/stop distance
- Check trad_TrendFollowing fire rate vs other setups
- Review trad_TrendFollowing logic for structural differences

---

### 4. trad_FVGFill Catastrophic Failure — MEDIUM PRIORITY
**Observation:** Worst performing setup across both asset classes
- Equities: 8.93% win rate, -0.647 avg pnl_r
- Forex: 28.48% win rate (still worst forex setup)

**Questions:**
- Is FVG fill logic fundamentally broken?
- Are FVG zones being calculated incorrectly?
- Is the entry timing wrong (filling too early/late)?
- Should this setup be retired?

**Investigation:**
- Audit FVG zone calculation logic
- Compare FVG fill timing vs actual FVG fills in market data
- Check if FVG zones are being identified correctly
- Consider setup retirement if investigation confirms bug

---

### 5. CVDDivergence Relative Alpha — LOW PRIORITY
**Observation:** Best equity setup despite still losing money
- trad_CVDDivergence: 19.36% win rate, -0.054 avg pnl_r (equity)
- Next best equity: trad_LiquiditySweepReclaim at 17.58%, -0.205 pnl_r
- Nearly breakeven while others lose 30-40 cents per dollar

**Questions:**
- Why does CVD work better on equities?
- Structural difference in logic?
- Better zone/stop calculation?
- Worth investigating for equity setup improvements?

**Investigation:**
- Compare CVDDivergence logic to other equity setups
- Analyze CVDDivergence zone/stop characteristics
- Check if CVDDivergence patterns transfer to other setups

---

### 6. Stopped_at Entry Uniformity — SYSTEMATIC
**Observation:** 47-49% stopped_at_entry across all dimensions
- By timeframe: 47-49% (1m: 47%, 5m: 48%, 15m: 48%, 1h: 49%)
- By asset class: forex 40-50%, equities 45-50%
- By setup: 35-63% (trad_FVGFill worst, trad_CVDDivergence best)

**Root cause:** Tiny zones (1-6 cents) + entry at zone edge + stop from zone edge

**Status:** Already captured in todo: `2026-06-14-review-stop-zone-logic.md`

---

### 7. Ecosystem Missing Setups — SYSTEMATIC
**Observation:** 24 I7 setups (65% of 37 registered) NOT firing
- 13 setups produce ZERO signals
- trad_MeanReversion broken: only 27 signals total, 26 pending, 1 expired never_activated

**Root cause:** `register_plugins.py` line 631 comment:
```python
# I7 plugins not yet integrated with I6 - refactor them in a follow-up phase, then delete this set.
```

**Missing setups (13 zero-signal):**
- trad_BreakoutFailure
- trad_BreakoutPullback
- trad_ChiAdapted
- trad_ClimacticExhaustion
- trad_CompositeFailure
- trad_ContinuationGap
- trad_EWTSetup
- trad_FairValueGap
- trad_HarmonicPattern
- trad_HiddenDivergence
- trad_MicroTrend
- trad_MultiTimeframe
- trad_OrderBlockSetup

**Questions:**
- Are these 13 fundamentally incomplete/broken?
- Should they be removed from registry if not firing?
- Is trad_MeanReversion logic broken (why only 27 signals)?

**Investigation:**
- Audit each zero-signal setup for I6 integration blockers
- Fix trad_MeanReversion logic or deprecate
- Decide: integrate I6 → deprecate → keep as shadow-only

---

### 8. Frequency Anomalies — INVESTIGATE
**Observation:** Extreme frequency skew across setups
- trad_TrendFollowing: 0.41% of universe (2,355 signals) — but ONLY profitable equity setup
- GapAnalysisSetup + DivergenceStack: ~40% of universe combined (250K+ signals)

**Questions:**
- Why is TrendFollowing firing so rarely despite being the only profitable equity setup?
- Are Gap/Divergence firing TOO frequently (low selectivity = low quality)?
- Should frequency be a quality gate (minimum signals per day, maximum per day)?

**Investigation:**
- Analyze TrendFollowing fire rate constraints (is it over-gated?)
- Compare Gap/Divergence fire rates to forex success (are they too promiscuous?)
- Consider adding frequency bounds to emission gates

---

## Investigation Priority Order

1. **USDJPY anomaly** — could reveal data quality or structural issues
2. **Asset class split** — fundamental incompatibility vs tuning
3. **Ecosystem missing setups** — 65% not firing, MeanReversion broken
4. **trad_TrendFollowing outlier** — what works on equities + frequency anomaly
5. **trad_FVGFill failure** — setup retirement candidate
6. **Frequency anomalies** — Gap/Divergence over-firing, TrendFollowing under-firing

## Related Analysis

- Full replay data: `.planning/replay-analysis-2026-06-14.md`
- Stop/zone issue: `.planning/todos/pending/2026-06-14-review-stop-zone-logic.md`
