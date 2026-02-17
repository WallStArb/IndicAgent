# IndicAgent Master Roadmap

> **Last Updated:** 2026-02-17
> **Current Version:** 4.2.0
> **Current Status:** I7 Phase 1.5 Complete — Foundation ready for live trading integration

---

## Current State (What's Working)

### Intelligence Pipeline (Fully Operational)
```
IBKR TWS → I1 Indicators (16 plugins) → I3 Structure (3) → I4 Context (3) →
I5 Patterns (4) → I6 Smart Money (6) → I6 Confluence (1) →
I7 Trading Setups (5) → Redis Streams → SSE → Dashboard
```

### I7 Signal Aggregation (Phase 1.5 — Components Built, Not Wired)
- ✅ Signal Ledger (TimescaleDB hypertable with lifecycle tracking)
- ✅ Rules-Based Aggregator (priority-based conflict resolution)
- ✅ Lifecycle Tracker (state machine with P&L calculations)
- ✅ Position Sizer (risk-based contract calculator)
- ❌ Signal Orchestrator Service (NOT BUILT — critical gap)
- ❌ Position Manager Service (NOT BUILT — critical gap)
- ❌ Dashboard Signal Panel (NOT BUILT)

**Data Collection Status:** ⚠️ **NOT COLLECTING** — orchestrator service doesn't exist

---

## Phase Priorities

### **PHASE 1: Live Trading Infrastructure (CRITICAL — Do This First)**

**Goal:** Start collecting real signal data for ML calibration

**Why This First?** Everything else is blocked on having real signal outcome data. The ML scoring model needs 500+ signals with P&L. We can't get that without the orchestrator running.

#### Task 1.1: Signal Orchestrator Service
**File:** `services/signal_orchestrator_service.py`
**Config:** `config/signal_orchestrator.json`

```python
# Responsibilities:
# 1. Subscribe to indicators:*:* and intelligence:*:*
# 2. On each bar: call all 5 setup plugins
# 3. Aggregate signals via aggregator.aggregate()
# 4. Insert ALL signals to signal_ledger (winners + losers)
# 5. Publish winner to signals:*:*:aggregated
# 6. Health: :9111/health, :9111/metrics
```

**Symbols:** ES, NQ, RTY (start with 3)
**Timeframes:** 5m, 15m (start with 2)
**Expected signal rate:** ~30 signals/day → 500 signals in ~17 days

#### Task 1.2: Position Manager Service
**File:** `services/position_manager_service.py`
**Config:** `config/position_manager.json`

```python
# Responsibilities:
# 1. Query active signals from database every bar
# 2. Evaluate lifecycle transitions via lifecycle_tracker
# 3. Update signal_ledger with new statuses/P&L
# 4. Track partial fills (scale out at targets)
# 5. Health: :9112/health, :9112/metrics
```

#### Task 1.3: Systemd Service Units
- `indicagent-signal-orchestrator.service`
- `indicagent-position-manager.service`
- Add to monitoring (health checks, metrics, journalctl)

#### Task 1.4: Dashboard Signal Panel (Optional for Phase 1)
**Component:** `dashboard/src/components/SignalPanel.tsx`
- Connect to `signals:*:*:aggregated` SSE stream
- Display active/pending/exited signals
- Show P&L tracking, aggregation metadata

**Estimated Duration:** 3-5 days (orchestrator is the hard part)
**Success Criteria:** 30+ signals/day flowing into signal_ledger with lifecycle updates

---

### **PHASE 2: Data Collection & Monitoring (2-4 Weeks)**

**Goal:** Run Phase 1 services to accumulate 500+ signals with outcomes

**Activities:**
1. Monitor signal generation rate (target: 30/day)
2. Monitor lifecycle transitions (pending→active→exit)
3. Verify P&L calculations match expectations
4. Check for bugs in lifecycle logic (e.g., both stop and target hit on same bar)
5. Monitor database growth (signal_ledger compression working?)
6. Validate aggregation resolution methods (sole/priority/majority/regime_tiebreak)

**Analytics Queries:**
```sql
-- Signal counts by setup plugin
SELECT setup_plugin, COUNT(*),
       SUM(CASE WHEN was_selected THEN 1 ELSE 0 END) as wins
FROM signal_ledger GROUP BY setup_plugin;

-- Win rate by resolution method
SELECT resolution_method, COUNT(*),
       AVG(CASE WHEN pnl_r > 0 THEN 1 ELSE 0 END) as win_rate,
       AVG(pnl_r) as avg_r_multiple
FROM signal_ledger WHERE was_selected = TRUE AND status != 'pending'
GROUP BY resolution_method;

-- Runner-up performance (what if we'd taken #2?)
SELECT AVG(pnl_r) as avg_r_if_selected
FROM signal_ledger WHERE composite_rank = 2 AND pnl_r IS NOT NULL;
```

**Checkpoints:**
- Day 7: ~200 signals → validate data quality, fix bugs
- Day 14: ~400 signals → early trend analysis
- Day 21: ~600 signals → ready for ML calibration

**Success Criteria:** Clean signal_ledger data with 500+ signals across all lifecycle states

---

### **PHASE 3: ML Scoring Model Calibration (After 500+ Signals)**

**Goal:** Replace rules-based aggregator with calibrated scoring model

#### Task 3.1: Feature Engineering
**File:** `src/intelligence/trading/feature_engineering.py`

Extract training features from signal_ledger:
```python
# Features (from existing columns):
- confidence (float)
- confluence_score (float)
- regime_context (categorical → one-hot: bullish/bearish/ranging)
- market_context JSONB fields:
  - trend_regime (float)
  - vol_regime (float)
  - atr (float)
  - volume_ratio (float)
  - swing_structure (categorical)
- setup_plugin (categorical → one-hot: 5 plugins)
- num_signals_bar (int)
- num_agreeing (int)
- num_conflicting (int)
- supporting_factors count (len of list)

# Target:
- pnl_r (R-multiple, continuous regression target)
```

#### Task 3.2: Model Training
**File:** `src/intelligence/trading/calibrate_model.py`

```python
# Train XGBoost/LightGBM on features → pnl_r
# Use was_selected = TRUE signals only (actual outcomes)
# Cross-validation: time-series split (train on weeks 1-2, validate on week 3)
# Hyperparameter tuning: grid search on learning_rate, max_depth, n_estimators
# Output: model weights, feature importances
```

#### Task 3.3: Scored Aggregator
**File:** `src/intelligence/trading/scored_aggregator.py`

```python
# Interface matches rules-based aggregator:
# aggregate(signals, trend_regime) -> AggregatedResult

# Implementation:
# 1. Extract features from each signal
# 2. Score each signal via trained model
# 3. Pick highest-scoring signal
# 4. Return AggregatedResult with scores instead of priority ranks
```

#### Task 3.4: A/B Test (Rules vs Scored)
Run both aggregators in parallel:
- Rules-based publishes to `signals:*:*:aggregated:rules`
- Scored publishes to `signals:*:*:aggregated:scored`
- Both log to signal_ledger with different `resolution_method` tags
- Compare performance over 7-14 days

**Success Criteria:** Scored model outperforms rules-based on avg R-multiple

#### Task 3.5: Model Retraining Pipeline
**Cadence:** Monthly or after every 500 new signals
**Process:**
1. Extract new signal_ledger rows
2. Retrain model with expanded dataset
3. Validate on holdout period
4. Deploy if performance improves

**Estimated Duration:** 1-2 weeks (depends on data quality)

---

### **PHASE 4: Expand Setup Plugins (Phase 2 — 9 More Plugins)**

**Goal:** Increase signal diversity and coverage

**Current:** 5 setup plugins (TrendFollowing, MeanReversion, LiquiditySweepReclaim, MTFAlignment, SqueezeExpansion)

**Target:** 14 total plugins (+9)

#### High-Priority Plugins (Add These Next)

1. **VWAP Deviation Setup**
   - Directory: `src/intelligence/trading/vwap_deviation.py`
   - Logic: Price deviates >2σ from VWAP → reversion signal
   - Best for: Mean reversion on high-volume instruments (ES, NQ)

2. **Momentum Breakout Setup**
   - Directory: `src/intelligence/trading/momentum_breakout.py`
   - Logic: ROC spike + volume confirmation + structure break
   - Best for: Trending moves after consolidation

3. **Supply/Demand Zone Setup**
   - Directory: `src/intelligence/trading/supply_demand_zones.py`
   - Logic: Price tests fresh zone (untouched level) + confluence
   - Best for: Structural reversal trades

4. **Gap Analysis Setup**
   - Directory: `src/intelligence/trading/gap_analysis.py`
   - Logic: Opening gap >X ticks → fade or continuation
   - Best for: Session open trades (ES/NQ at 9:30 AM ET)

5. **Chart Pattern Setup**
   - Directory: `src/intelligence/trading/chart_patterns.py`
   - Logic: Detect head & shoulders, double top/bottom, triangles
   - Best for: Swing trades on daily/4h timeframes

6. **Candlestick Pattern Setup**
   - Directory: `src/intelligence/trading/candlestick_patterns.py`
   - Logic: Doji/hammer/engulfing + confluence
   - Best for: Reversal signals at key levels

7. **Session Extremes Setup**
   - Directory: `src/intelligence/trading/session_extremes.py`
   - Logic: Asian session high/low holds during London/NY → fade
   - Best for: Time-based reversion trades

8. **Delta Divergence Setup** (requires orderflow data)
   - Directory: `src/intelligence/trading/delta_divergence.py`
   - Logic: Price makes new high but delta (buy vol - sell vol) diverges
   - Best for: Orderflow reversal signals
   - **Dependency:** Need IBKR tick-by-tick data with bid/ask flagging

9. **Imbalance Continuation Setup** (requires orderflow data)
   - Directory: `src/intelligence/trading/imbalance_continuation.py`
   - Logic: Strong delta imbalance (>70% one-sided) → continuation
   - Best for: Momentum follow-through
   - **Dependency:** Need IBKR orderflow data

**Estimated Duration:** 2-3 weeks (1-2 days per plugin with tests)

---

### **PHASE 5: Advanced Regime Models (I4 Expansion)**

**Goal:** Better regime classification for signal filtering

**Current I4 Plugins:** vol_regime, trend_regime, momentum_context (3 total)

#### High-Priority Regime Models

1. **GARCH Volatility Forecasting**
   - **File:** `src/intelligence/context/garch_volatility.py`
   - **Why:** Current vol tools measure *realized* vol (what happened). GARCH forecasts *conditional* vol (what's coming). Critical for position sizing and knowing when to avoid trading.
   - **Algorithm:** GARCH(1,1) — O(1) incremental updates
   - **Outputs:** `garch_sigma`, `garch_vol_ratio`, `garch_vol_regime`
   - **Reference:** Full spec in `docs/plans/future-indicators-backlog.md` lines 10-95

2. **Kalman Filter Trend Estimation**
   - **File:** `src/intelligence/context/kalman_trend.py`
   - **Why:** Current trend tools (EMA, ADX) lag. Kalman filter estimates true trend with uncertainty bounds in real-time.
   - **Algorithm:** Linear Kalman filter with state=[trend, velocity]
   - **Outputs:** `kalman_trend`, `kalman_velocity`, `kalman_confidence`
   - **Reference:** Full spec in `docs/plans/future-indicators-backlog.md` lines 97-185

3. **HMM Multi-Regime Classifier** (DONE — already implemented)
   - ✅ Already exists: `src/intelligence/smart_money/hmm_regime.py`
   - Uses multivariate Gaussian emissions on 5 features
   - Detects ranging/trending-up/trending-down with probabilities

**Estimated Duration:** 1 week per model (GARCH + Kalman)

---

### **PHASE 6: Orderflow Integration (Data Dependency)**

**Goal:** Add orderflow-based signals (requires IBKR tick data)

**Current Data:** reqHistoricalData (1m OHLCV bars) + reqMktData (live ticks with price/bid/ask)

**Needed:** reqTickByTickData with bid/ask flags to compute delta (buy volume - sell volume)

#### Prerequisites
1. Upgrade `hf_tws_daemon` to collect tick-by-tick data
2. Store ticks in new Redis stream: `orderflow:SYMBOL:live`
3. Aggregate ticks into bar-level delta metrics
4. Add to market_context JSONB for signal plugins

#### Orderflow Metrics
```python
# Per-bar aggregations from tick data:
- total_buy_volume (ticks at ask)
- total_sell_volume (ticks at bid)
- delta = buy_volume - sell_volume
- cumulative_delta (running sum)
- delta_percent = delta / (buy_volume + sell_volume)
- imbalance_bars (count of bars with >70% one-sided delta)
```

#### Orderflow Plugins (Depends on Above)
1. Delta Divergence Setup
2. Imbalance Continuation Setup
3. Absorption Detection (large volume at level with no price movement)
4. Iceberg Order Detection (repeated large trades at same price)

**Estimated Duration:** 2-3 weeks (daemon upgrade + 4 plugins)

---

### **PHASE 7: Multi-Instrument Portfolio Management**

**Goal:** Manage signals across 14 instruments with correlation awareness

**Current:** Each symbol/timeframe processes independently

**Needed:**
1. **Correlation Matrix Service**
   - Compute rolling correlations between instruments
   - Flag correlated pairs (ES/NQ, GC/SI, etc.)
   - Prevent over-allocation to correlated positions

2. **Portfolio Risk Manager**
   - Track total portfolio delta exposure
   - Limit max contracts per sector (indices, metals, energy, rates)
   - Dynamic position sizing based on account equity

3. **Symbol Rotation Logic**
   - Prioritize instruments with best recent signal performance
   - Reduce allocation to underperforming setups

**Estimated Duration:** 2-3 weeks

---

### **PHASE 8: Backtesting & Validation**

**Goal:** Validate live signal performance matches backtested expectations

**Approach:**
1. Replay historical bars through signal orchestrator
2. Compare backtested outcomes vs live signal_ledger data
3. Identify drift/degradation in signal quality
4. Tune models to maintain performance

**Tools:**
- Use existing signal_ledger data as starting point
- Build backtest engine that feeds historical bars to orchestrator
- Generate synthetic "what if" scenarios

**Estimated Duration:** 2-4 weeks

---

### **PHASE 9: I8 AI Intelligence Tier**

**Goal:** LLM-powered analysis and synthesis

**Current:** Ollama infrastructure ready (5 models available at :11434)

**Use Cases:**
1. **Signal Commentary**
   - LLM reads aggregated signal + market context
   - Generates plain-English explanation
   - "ES 5m LONG signal from TrendFollowing setup. Entry at 5100 because EMA crossed bullish while trend regime is +0.8 (strong bullish). Stop at 5085 (15 ticks = 1 ATR). Targets at 5115/5130/5145. Confidence 75% boosted from SqueezeExpansion agreement."

2. **Pattern Recognition**
   - LLM analyzes chart patterns from OHLC data
   - Detects head & shoulders, wedges, flags
   - Complements rule-based chart pattern plugin

3. **News Sentiment Integration**
   - Fetch news headlines for instrument (via RSS/API)
   - LLM classifies bullish/bearish/neutral sentiment
   - Factor into signal confidence scoring

4. **Trade Journal Auto-Documentation**
   - LLM generates daily trade summaries
   - Identifies learning opportunities from losing trades
   - Tracks performance by setup/regime/timeframe

**Cost Controls:**
- Use local Ollama models for bulk analysis (free, GPU-accelerated)
- Reserve OpenRouter for critical decisions or complex multi-turn reasoning
- Cache LLM outputs (commentary for same signal shouldn't change)

**Estimated Duration:** 3-4 weeks (iterative experimentation)

---

## Dependencies & Blockers

### Critical Path (Must Do In Order)
```
Phase 1 (Orchestrator) → Phase 2 (Data Collection) → Phase 3 (ML Calibration)
```

Everything else can run in parallel or be deferred.

### External Dependencies
- **Orderflow data (Phase 6):** Requires IBKR tick-by-tick subscription
- **News sentiment (Phase 9):** Requires news API (Bloomberg, Reuters, or free RSS)

### Resource Constraints
- **Development time:** Solo developer → prioritize high-ROI features
- **Infrastructure:** Single machine → orchestrator and position manager can run on same host
- **Data costs:** IBKR market data is free for paper trading

---

## Decision Framework (What to Build Next?)

Use this framework to prioritize when multiple options exist:

1. **Does it unblock data collection?** → Do it first (Phase 1)
2. **Does it improve signal quality measurably?** → Validate with A/B test before committing
3. **Is it required for live trading?** → High priority (orchestrator, position manager)
4. **Is it a nice-to-have?** → Defer until core is solid (I8 AI commentary)
5. **Does it require external data we don't have?** → Defer until data available (orderflow)

**Current Answer:** Build Phase 1 (Signal Orchestrator + Position Manager) immediately. Everything else waits.

---

## Success Metrics

### Short-Term (1 Month)
- [ ] Signal orchestrator running 24/7
- [ ] 500+ signals collected in signal_ledger
- [ ] Clean lifecycle transitions (pending→active→exit)
- [ ] Dashboard shows live signals

### Medium-Term (3 Months)
- [ ] ML scoring model deployed and outperforming rules-based
- [ ] 14 total setup plugins (9 new ones added)
- [ ] GARCH + Kalman regime models operational
- [ ] Portfolio risk manager limiting correlated exposure

### Long-Term (6 Months)
- [ ] Orderflow integration complete (delta, imbalance signals)
- [ ] Backtesting engine validates live performance
- [ ] I8 AI commentary generating insights
- [ ] 2000+ signals in ledger, model retraining monthly

---

## Archive References

**Completed Plans (Moved to `docs/plans/archive/`):**
- All `-implementation.md` files for completed features
- Individual plugin design docs (smart money, BOCPD, HMM already built)

**Active Design Docs (Keep in `docs/plans/`):**
- `future-indicators-backlog.md` — Full specs for GARCH, Kalman, chart patterns
- `2026-02-17-signal-aggregation-design.md` — Reference for aggregation architecture
- `2026-02-17-i7-phase1.5-completion-status.md` — Session summary with file inventory

**This Roadmap:**
- Single source of truth for what to build next
- Update after each completed phase
- Reference this first before creating new plans
