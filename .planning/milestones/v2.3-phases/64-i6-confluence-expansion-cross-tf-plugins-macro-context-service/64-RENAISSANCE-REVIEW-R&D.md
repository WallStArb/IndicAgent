# Phase 64: Renaissance-Style Review — R&D Mode (Not Production)

**Reviewed:** 2026-04-26
**Context:** Still building infrastructure, no live trading system yet
**Question:** "What would Jim Simons demand during R&D build-out?"

---

## The Renaissance Mindset for R&D

**What Renaissance did during build-out phase:**
1. **Parallel development** — Build infrastructure while testing signals
2. **Scientific discipline still matters** — But iteration speed > production safety
3. **Modularity prevents rewrites** — Design it right the first time
4. **Data collection continues** — Gather everything while building
5. **Separate concerns from day 1** — Avoid coupling that forces re-architecture

**Updated priorities for R&D mode:**
- ✅ **Iteration speed** — Build fast, test fast, revise fast
- ✅ **Clean architecture** — Don't paint ourselves into corners
- ✅ **Avoid technical debt** — Design for how we WILL use it, not just hack it together
- ⚠️ **Scientific rigor** — Important but can parallelize with development
- ❌ **Production safety** — Not applicable yet

---

## Jim Simons' Review of Phase 64 (R&D Edition)

### 🟢 **PLAN 01-02: Cross-TF Plugins — BUILD IN PARALLEL**

**Phase 64 current:** Build one plugin, validate with N>=30 signals, then build next

**Renaissance R&D approach:** **Build all 5 plugins in parallel, validate as a batch**

**Why:**
1. **I6 plugins are pure transformations** — No external I/O, no risk
2. **Shared infrastructure** — Schema extension, registration, shadow capture apply to all
3. **Fast iteration** — Develop all 5, test on historical data in parallel
4. **Avoid sequential bottlenecks** — Don't wait 30 bars × 5 times

**Revised Plan 01-02:**
```
Day 1-2: Build all 5 cross-TF plugins
  ├── CrossTFMomentumDivergence
  ├── CrossTFSRConfluence
  ├── CrossTFRegimeAgreement
  ├── SqueezeExpansionDivergence
  └── CrossTFOrderFlowAlignment

Day 3: Backtest all 5 on 6 months historical data (parallel)

Day 4: Validate batch
  ├── Keep: plugins with IC > 0.05
  ├── Revise: plugins with IC 0.02-0.05 (tweak parameters)
  └── Kill: plugins with IC < 0.02

Day 5: Deploy validated plugins to shadow mode
```

**Estimated effort:** 5 days total (vs. 6 days sequential) with better signal discovery.

---

### 🟡 **MACRO FACTORS: Build What We Have, Plan for What We Don't**

**Current macro coverage:**
```
✅ SPY, TLT, ZB, ZF, ZN, ZT  (6 instruments)
❌ EURUSD, GBPUSD, USDJPY, USDCHF  (4 FX pairs)
❌ VX  (VIX futures)
```

**Phase 64 Plan 03:** Merge all macro factors into CrossAssetComputeAgent

**Renaissance R&D approach:** **Build in phases, match data availability**

#### **Plan 03A: Yield Curve Slope (BUILD NOW — Data Available)**

**We have:** ZT, ZN, ZB, ZF rate futures

**Build:**
```python
# src/intelligence/macro/yield_curve.py
def compute_yield_curve_slope(bars: dict[str, deque]) -> dict:
    """Compute yield curve slope from rate futures.

    Returns:
        yield_curve_slope: float in [-1, +1]
        yield_curve_regime: str ("steepening", "flattening", "inverted", "normal")
    """
    # Price-based: ZT up = short rates down
    # Slope = (ZT - ZB) normalized
    # Regime from trend + z-score
```

**Deploy to:** New `MacroComputeAgent` service (clean separation)

**Backtest:** 6 months historical data (same backtest tool from cross-TF)

**If IC > 0.05:** Keep in shadow mode, accumulate live data

**If IC < 0.05:** Document as failed experiment, don't invest in FX data

**Effort:** 1 day

---

#### **Plan 03B: Flight-to-Quality (BUILD NOW — Partial Data)**

**We have:** TLT, SPY
**Missing:** VX (VIX futures)

**Build with available data:**
```python
# src/intelligence/macro/flight_to_quality.py
def compute_flight_to_quality(bars: dict[str, deque]) -> dict:
    """Compute flight-to-quality signal.

    Returns:
        ftq_score: float in [-1, +1]
        ftq_regime: str ("risk_on", "risk_off", "neutral")

    Current implementation: TLT+SPY
    Future enhancement: Add VX when available
    """
    # Risk-off = TLT up + SPY down
    # Score = sign-weighted agreement
    # Regime from magnitude + direction
```

**Deploy to:** `MacroComputeAgent` (same service)

**Backtest:** 6 months historical data

**Future enhancement:** When VX data is available, add to computation

**Effort:** 1 day

---

#### **Plan 03C: USD Strength (DEFER — No Data, No Validation Yet)**

**We need:** EURUSD, GBPUSD, USDJPY, USDCHF

**Don't build until:**
1. Yield curve OR flight-to-quality validates (IC > 0.05)
2. We add FX pairs to data feed
3. We validate macro approach has signal value

**Why:** Don't invest in data feeds for unproven signal class.

**Effort:** 0 days (deferred)

---

### 🟢 **ARCHITECTURE: Separate Services from Day 1**

**Phase 64:** Merge macro factors into `CrossAssetComputeAgent`

**Renaissance R&D approach:** **Separate services, reuse patterns**

**Architecture:**
```
CrossAssetComputeAgent (existing, unchanged)
  ├── EQ_INDEX spreads
  └── topic: intelligence → cross_asset

MacroComputeAgent (NEW)
  ├── Yield curve slope
  ├── Flight-to-quality
  ├── (USD strength — future)
  └── topic: market_bars → macro_signals
```

**Why separate services?**
1. **Clean separation of concerns** — EQ_INDEX vs macro factors are different domains
2. **Independent deployment** — Can update macro without touching EQ_INDEX
3. **Independent testing** — Can backtest macro in isolation
4. **Independent scaling** — If macro gets heavy, scale only that service
5. **Clear failure domains** — If macro crashes, EQ_INDEX still runs
6. **Future-proof** — Easy to add crypto, commodities, other macro classes

**Efficiency concern:** One more systemd unit, one more process

**Counter-argument:** Process overhead is negligible (~50MB RAM). Modularity benefit is huge.

**Renaissance decision:** **Separate services.**

---

### 🟢 **BACKTEST INFRASTRUCTURE: Build Fast, Use Often**

**Even in R&D mode, backtesting enables:**
1. **Scientific rigor** — Does this signal actually work?
2. **Fast iteration** — Test 20 parameter variations in an hour
3. **Regime discovery** — Does it work only in trending markets?
4. **Parameter tuning** — Find optimal lookback windows, thresholds
5. **Feature selection** — Keep plugins with IC > 0.05, kill the rest

**Build lightweight backtest tool (Plan 00):**
```python
# tools/backtest_i6_plugin.py
def backtest_i6_plugin(
    plugin_class: type,
    start_date: datetime,
    end_date: datetime,
) -> pd.DataFrame:
    """Backtest I6 plugin on historical data.

    Returns DataFrame with:
    - ts, symbol, tf
    - {output_field}_value for each plugin output
    - pnl_r (from signal_ledger)
    - hmm_regime (from intelligence_features)
    """
    # Load market_data_ohlcv
    # Load intelligence_features
    # Replay plugin on each bar
    # Join to signal_ledger
    # Return combined DataFrame
```

**Use cases:**
- **During development:** Test plugin on 6 months data, measure IC
- **Parameter tuning:** Try 5 different lookback windows, pick best
- **Regime analysis:** Does it work in trending but fail in ranging?
- **Feature selection:** Keep CrossTFMomentumDivergence (IC=0.08), kill CrossTFRegimeAgreement (IC=0.01)

**Effort:** 1 day to build

**Benefit:** Scientific rigor, fast iteration, avoid wasting time on dead-end features

---

### 🟡 **I6 PLUGIN PROTOCOL: Document, Don't Change**

**Current design:** I6 plugins run in-process in IntelligencePipelineComputeAgent

**This is CORRECT for R&D mode:**
- ✅ Fast iteration (no service restarts)
- ✅ Debugging (can add print() statements and see output)
- ✅ Access to cached data (frames["intel_*"])
- ✅ Zero serialization overhead

**Trade-off accepted:** Tight coupling to pipeline internals

**BUT:** Document this clearly so future developers understand:
```python
# src/intelligence/confluence/README.md
"""
I6 Confluence Plugins — In-Process Transformations

I6 plugins are NOT independent services. They run inside
IntelligencePipelineComputeAgent during Wave 4.

Why in-process?
- Fast iteration during R&D
- Zero serialization overhead
- Access to cached I1-I5 outputs

Trade-off:
- Tightly coupled to pipeline internals
- Can't deploy without restarting pipeline

This is ACCEPTABLE for R&D. If we need independent deployment
in production, refactor to microservices later.
"""
```

---

## Renaissance-Style Revised Plan

### **Plan 00: Backtest Infrastructure** (Day 1)

**Build:**
- `tools/backtest_i6_plugin.py` — Backtest any I6 plugin
- `tools/validate_i6_backtest.py` — Validate IC, p-value, regime segmentation

**Deliverable:** Can test any I6 plugin on 6 months historical data in ~5 minutes

---

### **Plan 01-02: All 5 Cross-TF Plugins (Batch)** (Days 2-5)

**Day 2-3:** Build all 5 plugins
- CrossTFMomentumDivergence
- CrossTFSRConfluence
- CrossTFRegimeAgreement
- SqueezeExpansionDivergence
- CrossTFOrderFlowAlignment

**Day 4:** Backtest all 5 in parallel
- Run backtest tool for each plugin
- Generate IC, p-value, regime-segmented results

**Day 5:** Review results
- **Keep (IC > 0.05):** Deploy to shadow mode
- **Tweak (IC 0.02-0.05):** Adjust parameters, retest
- **Kill (IC < 0.02):** Document as failed experiment

**Deliverable:** 3-5 validated I6 plugins in shadow mode

---

### **Plan 03A: Yield Curve Slope** (Day 6)

**Build:**
- `src/intelligence/macro/yield_curve.py`
- `services/macro_compute_agent.py` (new service)
- Extend schemas for `macro_features` table

**Backtest:** 6 months historical data

**Deploy:** MacroComputeAgent to shadow mode

**Deliverable:** Yield curve signal in shadow mode

---

### **Plan 03B: Flight-to-Quality** (Day 7)

**Build:**
- `src/intelligence/macro/flight_to_quality.py`
- Extend MacroComputeAgent with FTQ computation

**Backtest:** 6 months historical data

**Deploy:** Update MacroComputeAgent in shadow mode

**Deliverable:** FTQ signal in shadow mode

---

### **Plan 03C: USD Strength** (Deferred)

**Don't build until:**
1. Yield curve OR FTQ validates (IC > 0.05)
2. We add FX pairs to data feed
3. We validate macro approach has signal value

**Why:** Don't invest in data feeds for unproven signal class

---

## Summary: Renaissance-Style R&D Approach

### **🔴 CHANGES FROM PHASE 64:**

1. **Batch cross-TF plugin development** — Build all 5 in parallel, not sequential
2. **Add backtest infrastructure (Plan 00)** — Enables scientific rigor, fast iteration
3. **Separate MacroComputeAgent** — Clean architecture from day 1
4. **Split macro factors by data availability** — Build what we have, defer what we don't

### **🟢 KEEP AS-IS:**

5. **I6 in-process plugins** — Fast iteration, correct for R&D
6. **Gradient-first scoring** — Continuous signals, no binary thresholds
7. **Regime-segmented validation** — Test trending vs ranging separately

### **🟡 CLARIFY:**

8. **Document I6 as in-process** — Prevent future confusion about DAG discipline
9. **Validation is for feature selection** — Keep what works (IC > 0.05), kill what doesn't (IC < 0.02)

---

## Estimated Timeline (R&D Mode)

| Plan | Work | Days |
|------|------|------|
| **Plan 00** | Backtest infrastructure | 1 |
| **Plan 01-02** | 5 cross-TF plugins + backtests | 4 |
| **Plan 03A** | Yield curve + backtest | 1 |
| **Plan 03B** | Flight-to-quality + backtest | 1 |
| **Plan 03C** | USD strength (deferred) | — |
| **Total** | | **7 days** |

**vs. Phase 64 current:** ~6 days sequential but without scientific rigor

**Renaissance trade-off:** +1 day for backtest infrastructure → **scientific rigor, feature selection, confidence in what we build**

---

## Key Principles for R&D Mode

1. **Iteration speed > production safety** — But don't skip validation
2. **Clean architecture from day 1** — Avoid re-architecture later
3. **Separate services by domain** — EQ_INDEX vs macro are different
4. **Backtest everything** — Fast iteration, feature selection, parameter tuning
5. **Build for data you have, plan for data you don't** — Don't block on missing data
6. **Document design decisions** — Why in-process? Why separate services?

---

*Generated: 2026-04-26*
*Reviewed through Renaissance lens: R&D mode, iteration speed, clean architecture, scientific rigor*
