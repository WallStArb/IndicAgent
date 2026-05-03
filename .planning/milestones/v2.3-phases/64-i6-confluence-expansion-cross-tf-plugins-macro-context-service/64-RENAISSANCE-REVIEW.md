# Phase 64: Renaissance-Style Architecture Review

**Reviewed:** 2026-04-26
**Question:** "What would Jim Simons demand?" — Balance modularity, reuse, separation of concerns, DAG discipline, efficiency, simplicity, compute costs, maintenance.

---

## The Renaissance Mindset

**What made Renaissance special:**
1. **Data-first obsession** — Collect everything, test everything, keep what works
2. **Scientific rigor** — No model trades without statistical proof (p < 0.05, sufficient N)
3. **Efficiency through simplicity** — Fancy models lose to simple, robust signals
4. **Parallelism + automation** — Systems run autonomously; humans supervise
5. **Separate concerns, couple loosely** — Data collection → signal generation → execution

**Our Renaissance Principles (CLAUDE.md):**
- "Instrument everything. No data point left uncaptured."
- "Earn the right through proof. No model, strategy, or feature gets promoted without statistically significant evidence."
- "Never drop data that could contain signal. Storage is cheapest thing we own."
- "Segment relentlessly. A rule that works globally is weaker than one that works in a specific regime."
- "Degrade gracefully, adapt automatically."

---

## Jim Simons' Review of Phase 64

### 🔴 **CRITICAL ISSUE: Validation Gate has No Data**

**What Phase 64 assumes:**
> "Plan 01 must ship, accumulate N>=30 signals, and validate IC > 0.05 AND p < 0.05 before Plan 02 execution begins."

**Simons would ask:** *"Where will the 30 signals come from?"*

**Reality check:**
- Phase 64-01: CrossTFMomentumDivergence plugin doesn't exist yet
- No historical backtest data exists
- No shadow mode recording exists
- We have to ship to production, wait for N>=30 bars with signals, THEN validate

**This is wrong.** Renaissance would NEVER ship unvalidated code to production just to collect validation data.

**What Renaissance actually does:**
1. **Historical backtest first** — Run on 6-12 months of historical data
2. **Measure IC** — If IC < 0.05 or p >= 0.05: **KILL IT** before production
3. **Regime segmentation** — Test separately in trending, ranging, volatile regimes
4. **Out-of-sample validation** — Hold out most recent 20% of data, verify IC holds
5. **ONLY THEN: shadow mode** — Deploy in shadow, validate IC matches backtest
6. **THEN: live trading** — Gradual position sizing

**Phase 64's current process:** Ship blind → wait 30 bars → validate → proceed?

**Simons would reject this.**

---

### 🟡 **ARCHITECTURAL TENSION: In-Process Plugins vs DAG Discipline**

**Our DAG principle (CLAUDE.md):**
> "ComputeAgents (I1-I7) are DB-ignorant, publish to tiered topics (intelligence.i{N}), DataWriterAgents manage persistence."

**Phase 64 design:**
> "Cross-TF plugins run in-process within IntelligencePipelineComputeAgent, reading frames["intel_*"]. Zero new Kafka topics."

**Conflict:** I6 plugins bypass Kafka entirely. They run in-process, return dicts.

**Is this wrong?** Not necessarily. Let's analyze:

**The efficiency argument:**
- Kafka round-trip latency: ~1-3ms per message
- I6 plugins need to read I1-I5 outputs (already in memory)
- Launching separate process per I6 plugin: wasteful
- In-process plugins: zero serialization, zero network I/O

**The modularity argument:**
- In-process: Can't backtest I6 independently without running full pipeline
- In-process: Can't update I6 without restarting I1-I7 pipeline
- In-process: Tight coupling between I6 and pipeline internals

**What would Renaissance do?**

Simons would ask: *"What's the cost of coupling? What's the benefit of separation?"*

**Answer:**
- **Benefit of separation:** Independent testing, deployment, scaling of I6
- **Cost of separation:** Kafka latency (1-3ms), serialization overhead
- **Benefit of in-process:** Speed, simplicity, access to cached data
- **Cost of in-process:** Coupling, harder to test/evolve

**Renaissance decision:** **In-process is RIGHT for I6 plugins.**

**Why?**
1. I6 plugins are **pure transformations** — no external I/O, no DB writes
2. They read data already in memory (frames["intel_*"])
3. Launching 5 separate services for 5 I6 plugins: overhead >> benefit
4. Backtesting can still run full pipeline with I6 enabled/disabled
5. The DAG discipline applies at **service boundaries**, not internal function calls

**BUT:** This means I6 plugins are a **tier within** IntelligencePipelineComputeAgent, not independent services. The documentation should reflect this.

---

### 🟡 **CROSS-ARCHITECTURAL QUESTION: Macro Factors in CrossAssetComputeAgent**

**Phase 64 design:**
> "Macro factors computed within existing CrossAssetComputeAgent. One service for all cross-market intelligence."

**What CrossAssetComputeAgent currently does:**
- Subscribes to `topic_intelligence`
- Computes EQ_INDEX spread features (ES vs NQ, RTY, YM)
- Publishes to `topic_cross_asset`

**What Phase 64 wants to add:**
- USD strength (FX pairs: EURUSD, GBPUSD, USDJPY, USDCHF)
- Yield curve slope (rate futures: ZT, ZN, ZB, ZF)
- Flight-to-quality (TLT, SPY, VX)

**Simons would ask:** *"Why mix equity index spreads with FX macro factors?"*

**Arguments for mixing:**
- Reuse existing service infrastructure
- Single `topic_cross_asset` for all cross-market signals
- Fewer services to monitor/maintain

**Arguments for separation:**
- **Different update frequencies:** EQ_INDEX spreads update every bar. FX spreads might update differently.
- **Different data sources:** EQ_INDEX from `topic_intelligence`, FX from `topic_market_bars` (if we add it)
- **Different failure modes:** If CrossAssetComputeAgent crashes, we lose both EQ_INDEX AND macro signals
- **Testing harder:** Can't backtest macro factors without running EQ_INDEX logic

**What would Renaissance do?**

Simons would ask: *"What's the marginal cost of a separate service? What's the marginal benefit?"*

**Answer:**
- **Marginal cost:** One more systemd unit, one more Kafka topic, one more DB writer
- **Marginal benefit:** Independent deployment, testing, scaling; clearer separation of concerns

**Renaissance decision:** **SEPARATE services, BUT share infrastructure.**

**Design:**
```
CrossAssetComputeAgent (existing)
  ├── EQ_INDEX spreads
  ├── topic: intelligence → cross_asset
  └── unchanged

MacroComputeAgent (new)
  ├── USD strength (FX pairs)
  ├── Yield curve slope (rate futures)
  ├── Flight-to-quality (bonds + ETFs)
  ├── topic: market_bars → macro_signals
  └── subscribes to market_bars for macro instruments
```

**Why?**
1. **Independent deployment:** Can add/modify macro factors without touching EQ_INDEX
2. **Independent testing:** Can backtest macro signals in isolation
3. **Independent scaling:** If macro computation gets heavy, scale only that service
4. **Clear failure domain:** If macro service crashes, EQ_INDEX still runs
5. **Shared patterns:** Both use BaseAgent, both follow same lifecycle

**But wait:** We're missing 5/11 macro instruments (FX pairs + VX). Should we build MacroComputeAgent before we have the data?

**Simons would say:** *"Don't build infrastructure for data you don't have."*

---

### 🔴 **DATA GAPS: Building Without Validation Data**

**Current macro instrument coverage:**
```
✅ SPY, TLT, ZB, ZF, ZN, ZT  (6 instruments)
❌ EURUSD, GBPUSD, USDJPY, USDCHF  (4 FX pairs)
❌ VX  (VIX futures)
```

**Phase 64 Plan 03 wants:**
- USD strength factor → **BLOCKED** (needs FX pairs)
- Yield curve factor → **READY** (ZT/ZN/ZB/ZF available)
- Flight-to-quality → **PARTIAL** (needs VX)

**What would Renaissance do?**

**Option A:** Add FX pairs + VX to data feed
- **Cost:** IBKR data subscriptions for FX futures, VX futures
- **Benefit:** Can build all 3 macro factors
- **Simons would ask:** *"Do we have evidence these factors have signal?"* No.

**Option B:** Build only what we have data for
- **Yield curve slope:** Ready to build
- **Flight-to-quality:** Build with TLT+SPY, add VX later when available
- **USD strength:** Defer until FX data added

**Option C:** Don't build macro factors at all until validation
- Build yield curve slope
- Backtest on 6 months historical data
- If IC > 0.05: proceed to other factors
- If IC < 0.05: **KILL IT**, don't invest in data feeds

**Renaissance decision:** **Option C — Validate before investing.**

**Process:**
1. **Build yield curve slope factor only** (we have the data)
2. **Backtest on 6 months historical data**
3. **Measure IC per regime** (trending, ranging, volatile)
4. **If IC > 0.05 AND p < 0.05:** Proceed to flight-to-quality (partial)
5. **If IC < 0.05:** Stop. Don't add FX pairs, don't build USD strength
6. **If IC validates:** Add FX pairs, build USD strength, validate again

**This is Renaissance discipline:** Earn the right through proof.

---

### 🟢 **WHAT PHASE 64 GOT RIGHT**

✅ **Gradient-first scoring** — Continuous signals in [-1, +1], no binary thresholds
- Renaissance loves this. Information loss is the enemy.

✅ **Validation gates with IC + p-value** — Statistical proof required
- But the gate should come **before** production, not after.

✅ **Regime-segmented validation** — Test separately in trending, ranging, volatile
- Critical. "Segment relentlessly."

✅ **Capture everything, use nothing until proven** — _shadow dict for ML
- "Never drop data that could contain signal."

✅ **Phased rollout** — Build one, validate, then batch
- But validate on **historical data first**, not production shadow.

---

## Renaissance-Style Revision of Phase 64

### **Plan 00: Historical Backtest Infrastructure (NEW)**

**What Renaissance would demand first:**

**Objective:** Build backtest framework to validate I6 plugins on historical data BEFORE production deployment.

**Deliverables:**
1. `tools/backtest_i6_plugin.py` — Backtest script for any I6 plugin
   - Input: plugin class, start_date, end_date
   - Load `market_data_ohlcv` + `intelligence_features` from DB
   - Run plugin on each bar (replay pipeline logic)
   - Output: CSV with `{ts, symbol, tf, i6_field_values, pnl_r}`
2. `tools/validate_i6_backtest.py` — Validation script
   - Input: backtest CSV
   - Compute IC, p-value per regime (hmm_regime 0/1/2)
   - Output: PASS/FAIL with statistics

**Validation criteria:**
- IC > 0.05 AND p < 0.05 (Bonferroni-corrected)
- Passes in at least 1 regime (trending OR ranging OR volatile)
- Out-of-sample IC >= 0.8 × in-sample IC (no overfitting)

**Estimated effort:** 1-2 days

**Why Renaissance would insist on this:**
- "Earn the right through proof" — prove it works on historical data before risking production
- Zero production risk
- Fast iteration: backtest → validate → revise → backtest again
- Can test 20 plugin variants in a day, pick the best

---

### **Plan 01: CrossTFMomentumDivergence — With Backtest (REVISED)**

**Revised process:**

1. **Implement plugin** (as planned)
   - `src/intelligence/confluence/cross_tf_momentum_divergence.py`
   - Extend I6Confluence schema
   - Register in TIER_I6

2. **Backtest on 6 months historical data** (NEW)
   - Run `tools/backtest_i6_plugin.py` (Plan 00)
   - Generate CSV with `{ts, symbol, tf, ctf_momentum_divergence, pnl_r}`

3. **Validate backtest results** (NEW)
   - Run `tools/validate_i6_backtest.py`
   - Check IC > 0.05, p < 0.05, regime segmentation

4. **IF VALIDATION PASSES:** Deploy to production shadow mode
   - Accumulate N>=30 live signals
   - Verify live IC matches backtest IC (within error margin)

5. **IF VALIDATION FAILS:** Kill plugin, iterate, or move to next plugin

**Estimated effort:** 1 day implementation + 0.5 day backtest = 1.5 days

**Renaissance discipline:** No production deployment without backtest validation.

---

### **Plan 02: Remaining 4 Cross-TF Plugins — Batched with Backtests (REVISED)**

**Same process as Plan 01, applied to all 4 plugins:**

1. **CrossTFSRConfluence** — Support/Resistance cross-TF alignment
2. **CrossTFRegimeAgreement** — Regime cross-TF agreement
3. **SqueezeExpansionDivergence** — Squeeze vs expansion divergence
4. **CrossTFOrderFlowAlignment** — Order flow cross-TF alignment

**Each plugin:**
- Implement (0.5 day)
- Backtest 6 months (0.5 day)
- Validate (0.1 day)
- **If IC > 0.05:** Deploy to shadow
- **If IC < 0.05:** Document as failed experiment, move on

**Estimated effort:** 4 plugins × 1.1 days = 4.4 days

**Renaissance discipline:** Fast iteration, fail fast, keep what works.

---

### **Plan 03: Macro Factors — Data-First Approach (REVISED)**

**Split into two phases:**

#### **Plan 03A: Yield Curve Slope (Data Available — Validate First)**

1. **Implement yield curve factor** (as planned)
   - `src/intelligence/macro/yield_curve.py`
   - Compute from ZT/ZN/ZB/ZF futures (we have the data)

2. **Backtest on 6 months historical data**
   - Load yield curve data from `market_data_ohlcv`
   - Load corresponding I7 signals + pnl_r from `signal_ledger`
   - Compute IC per regime

3. **Validate backtest results**
   - **If IC > 0.05:** Deploy to MacroComputeAgent (new service)
   - **If IC < 0.05:** Kill yield curve factor, don't build MacroComputeAgent

**Estimated effort:** 1 day

#### **Plan 03B: Remaining Macro Factors — Deferred Until Data Validation**

**Don't build until:**
1. Yield curve factor validates (IC > 0.05)
2. We add missing data sources (FX pairs, VX)
3. We validate flight-to-quality with TLT+SPY (partial data)

**If yield curve FAILS validation:**
- Don't add FX pairs (don't spend money on data feeds for unproven approach)
- Don't build USD strength factor
- Don't build flight-to-quality factor
- **Kill macro factor direction entirely**

**Renaissance discipline:** Invest in data only after proving signal value.

---

## Architectural Recommendations: Renaissance-Style

### **1. Backtest-First Development Process**

**What we need:**
```python
# tools/backtest_i6_plugin.py
def backtest_i6_plugin(
    plugin_class: type,
    start_date: datetime,
    end_date: datetime,
    symbols: list[str] | None = None,
) -> pd.DataFrame:
    """Backtest I6 plugin on historical data.

    Returns DataFrame with columns:
    - ts, symbol, tf
    - {output_field}_value for each plugin output
    - pnl_r (from signal_ledger JOIN)
    - hmm_regime (from intelligence_features)
    """
    # Load market_data_ohlcv for symbols/timeframe
    # Load intelligence_features for I1-I5 inputs
    # Replay plugin.compute_full() on each bar
    # Join to signal_ledger for pnl_r outcomes
    # Return combined DataFrame
```

**Why:** Never ship to production without historical validation.

---

### **2. Separate MacroComputeAgent Service**

**Architecture:**
```
CrossAssetComputeAgent (existing, unchanged)
  ├── EQ_INDEX spreads
  └── topic: intelligence → cross_asset

MacroComputeAgent (new, if yield curve validates)
  ├── Yield curve slope (ZT/ZN/ZB/ZF)
  ├── Flight-to-quality (TLT+SPY, add VX later)
  ├── USD strength (EURUSD etc, add FX data later)
  ├── topic: market_bars → macro_signals
  └── DataWriterAgent → macro_features (hypertable)
```

**Why:** Independent deployment, testing, scaling. Clear failure domain.

**Efficiency concern:** One more service = one more systemd unit, one more process.

**Counter-argument:** Process overhead is negligible. Modularity benefit is huge.

---

### **3. Plugin Protocol: Keep In-Process, Document Clearly**

**Current design:** I6 plugins run in-process in IntelligencePipelineComputeAgent.

**This is RIGHT** but needs clear documentation:

```python
# src/intelligence/confluence/README.md
"""
I6 Confluence Plugins — In-Process Transformations

I6 plugins are NOT independent services. They are transformer functions
that run inside IntelligencePipelineComputeAgent during Wave 4.

Why in-process?
- Zero serialization overhead (read from frames["intel_*"])
- Zero network I/O (no Kafka round-trip)
- Access to cached I1-I5 outputs

Trade-off:
- Tightly coupled to pipeline internals
- Can't deploy/update without restarting pipeline
- Can't backtest without running full pipeline

This trade-off is ACCEPTABLE because:
- I6 plugins are pure transformations (no external I/O)
- Backtest tool replays full pipeline anyway
- Modularity at service level is overkill for simple transforms
"""
```

**Why:** Clear documentation prevents future confusion about DAG discipline.

---

### **4. Validation Gate: Pre-Production, Not Post-Production**

**Current Phase 64:** Ship to production → accumulate N>=30 → validate

**Renaissance revision:** Backtest on historical data → validate → IF PASSED: ship to shadow → validate shadow matches backtest → THEN live

**Why:** Zero production risk. Faster iteration.

---

## Summary: What Would Jim Simons Demand?

### **🔴 CRITICAL CHANGES:**

1. **Add Plan 00: Backtest infrastructure** — MUST HAVE before any plugin development
2. **Move validation gate BEFORE production** — Backtest first, then shadow
3. **Split Plan 03 into data-first phases** — Validate yield curve before investing in FX data

### **🟡 ARCHITECTURAL CLARIFICATIONS:**

4. **Document I6 as in-process plugins** — Not independent services, but that's OK
5. **Create separate MacroComputeAgent** — If yield curve validates, don't mix with EQ_INDEX

### **🟢 KEEP AS-IS:**

6. **Gradient-first scoring** — Perfect
7. **Regime-segmented validation** — Perfect
8. **Capture everything in _shadow** — Perfect

---

## Estimated Timeline (Renaissance-Style)

- **Plan 00:** Backtest infrastructure (1-2 days)
- **Plan 01:** CrossTFMomentumDivergence + backtest (1.5 days)
- **Plan 02:** Remaining 4 plugins + backtests (4.4 days)
- **Plan 03A:** Yield curve + backtest (1 day)
- **Plan 03B:** Defer until validation

**Total: 8-9 days** to build + validate all I6 cross-TF plugins + yield curve

**vs. Phase 64 current: ~6 days** but with production risk and no historical validation

**Renaissance trade-off:** +2-3 days for backtest infrastructure → **zero production risk, scientific rigor, confidence in what we ship**

---

*Generated: 2026-04-26*
*Reviewed through Renaissance lens: Data-first, validate-first, separate concerns, balance efficiency with simplicity*
