# Signal-to-Noise Crisis: Root Cause Analysis & Production Hardening Plan

**Date**: 2026-06-07
**Status**: in-progress
**Type**: Root Cause Analysis
**Last Updated:** 2026-06-10
**Authors**: Renaissance Council (Engineering + Architecture + Quant)
**Scope**: System-level root cause analysis of signal generation over-abundance

---

## THE GOAL

**Stop creating noise signals in the first place.**

We are NOT trying to filter noise better — CIS gates already do that (working correctly, as proven by selected signals having higher CIS scores).

We are NOT trying to reduce signal volume — that's a side effect.

**THE GOAL**: Improve signal-to-noise ratio at the source. If a setup fires 100,000 signals, we want 50,000+ to be real signals (50% SNR), not 200 (0.2% SNR).

**Current state** (BROKEN):
- trad_OFIContinuation fires 1.59M signals → 2.8K selected (0.18% SNR) → **99.82% NOISE**
- trad_PatternCompletion fires 795K signals → 1.2K selected (0.15% SNR) → **99.85% NOISE**
- trad_CVDDivergence fires 250K signals → 113 selected (0.05% SNR) → **99.95% NOISE**

**Target state** (RENAISSANCE):
- trad_TrendFollowing fires 654K signals → 654K selected (100% SNR) → **0% NOISE**
- trad_LiquiditySweepReclaim fires 333K signals → 229K selected (69% SNR) → **31% NOISE**
- trad_CHoCHReversal fires 232K signals → 139K selected (60% SNR) → **40% NOISE**

**Jim Simons would say**: "Why are we creating noise? If a signal isn't real, don't fire it in the first place. Filter at the source, not downstream."

---

## Executive Summary

**The crisis**: 7.85M signals generated across 30 I7 setups. 21 setups (70%) generate 57% of all signals but only 0.19% are selected. **This means 99.8% of signals from these setups are noise — created at the source, not filtered downstream.**

**The goal**: Stop creating noise. Improve signal-to-noise ratio (SNR) from 0.2% → 40%+ for setups firing 10s/100s of thousands of signals.

**Renaissance Council Verdict**: The **IDEAS are sound** (OFI continuation, pattern completion, gap analysis, CVD divergence) but the **IMPLEMENTATIONS CREATE NOISE**. We must fix the data pipeline to stop creating noise at the source, not delete the signal concepts.

**What This IS**:
- ✅ About STOPPING noise creation at the source (I7 signal generation logic)
- ✅ About improving signal-to-noise ratio from 0.2% → 40%+ for high-volume setups
- ✅ About fixing BAD INPUTS that cause setups to fire noise signals
- ✅ About enforcing Renaissance-grade design patterns (architectural rigor)
- ✅ About preserving all 30 signal concepts (ideas are sound, implementations broken)

**What This Is NOT**:
- ❌ NOT about filtering noise better (CIS gates already do this correctly — selected signals have higher CIS scores)
- ❌ NOT about reducing signal volume (that's a side effect of stopping noise creation)
- ❌ NOT about deleting signal concepts (all 30 ideas are sound — trad_OFIContinuation IS a valid concept)
- ❌ NOT about fixing the aggregator (aggregator works correctly — it filters low-confluence signals)
- ❌ NOT about improving CIS scoring (CIS scores work correctly — higher CIS → higher selection)

**The Goal in One Sentence**: Stop creating 4.46M noise signals (57% of total) by fixing the 21 broken implementations that fire 99.8% noise, while preserving all 30 sound trading concepts.

**How we achieve the goal**:
1. **Fix BAD INPUTS** — Upstream features (I1/I5) produce unvalidated data that I7 setups consume
2. **Enforce GOOD PATTERNS** — Multi-factor confidence, I6 confluence, strict gates, continuous regime weighting
3. **Add validation gates** — ParityAuditor catches data flow bugs before they create noise
4. **Earn promotion through proof** — Shadow mode validates setups don't create noise (p<0.05, N≥100)

**What this is NOT**:
- ❌ NOT about filtering noise better (CIS gates already do this correctly)
- ❌ NOT about reducing volume (that's a side effect of stopping noise creation)
- ❌ NOT about deleting signal concepts (all 30 ideas are sound)

---

## COUNCIL ANALYTICAL REVIEW (2026-06-08)

> A first-principles review by the Renaissance Council identified three analytical problems in this document that affect execution ordering. The setup-by-setup analysis and directional fixes remain valid. The specific threshold values and enforcement mechanisms require revision.

### Problem 1: "Noise" Is Measured by a Proxy, Not Ground Truth

**The circular reasoning trap:**

"Selection rate" measures "did the CIS aggregator pick this signal as the best available at that moment." It does NOT measure "would this have been a profitable trade." The aggregator is a winner-take-all ranker — when 50 signals fire simultaneously, 49 are "rejected" regardless of their absolute quality.

The analysis concludes 99.8% noise from selection rates. But we have **zero pnl_r data on unselected signals** — they never activated, so we cannot know if they had edge. We are inferring signal quality from the aggregator's opinion, and the aggregator's opinion is weighted on the same flawed confidence formulas we are criticizing. This is circular.

**What this means for the plan**: Specific threshold values (`MIN_OFI_MAGNITUDE=500`, `min_gap_atr_mult=0.3→0.8`, etc.) throughout this document are directionally reasonable guesses, not empirically derived constants. They must be derived from outcome data before being shipped to production.

### Problem 2: Two Distinct Problem Categories — Different Response Required

**Category A — Pipeline bugs (deterministic, fix immediately, no data needed):**

| Bug | Evidence | Why It's a Bug, Not a Calibration Issue |
|-----|----------|-----------------------------------------|
| PatternCompletion phantom data | `pattern_detections` JSONB = zero rows across 2.2M `intelligence_features` | DAG invariant violated — I5 output is not reaching DB |
| Stop losses inside entry zones | 793 `stopped_at_entry` signals | Deterministic: stop ≤ zone_low for longs is always wrong — **FIXED** (`validate_stop_against_zone()` in `plugin_utils.py`, called from `trade_framer.py:1018`) |
| `_CVD_DIV_THRESHOLD = 0.0` in `cvd_divergence.py` | Any nonzero float fires — `0.0001` and `100.0` treated identically | Deterministic: a threshold of zero is not a threshold; magnitude semantics entirely absent |
| I6 fetched but silently discarded in 4 plugins | `ofi_continuation`, `cvd_divergence`, `gap_analysis_setup`, `divergence_stack` all do `frames.get("i6") or {}` then never reference `ctf_score`, `ctf_structure`, or `ctf_trend` | Code already has the data — it is dropped on the floor every bar |
| `ofi_spike` / `cvd_spike` don't fetch I6 at all | No `frames.get("i6")` in either plugin | These two don't even pull the data |
| `hmm_regime` used for logging only, not weighting | All 6 plugins read `features.get("hmm_regime")` to build `regime_context` string, then stop — none call `hmm_regime_weight()` | Regime is recorded but has zero influence on whether the signal fires or what confidence it receives |

These are correctness defects. They fire before any of the v2.9 phase work begins.

**Category B — Calibration questions (need empirical data before fixing):**

| Question | Why Data Is Needed |
|----------|-------------------|
| What OFI magnitude separates signal from noise? | 500 is a guess — market-derived threshold could be 200 or 2000 |
| What gap ATR multiple filters constant firing? | 0.8 is a guess |
| Does I6 integration improve profitability or just selection rate? | The I6 correlation may be selection bias (see Problem 3) |
| What minimum consecutive bars makes OFI "sustained"? | 10 is a guess |

Category B fixes must be preceded by empirical data collection. See Phase 117.5 in the revised implementation roadmap below.

### Problem 3: I6 Confluence Correlation Is Likely Selection Bias

The analysis states: "I6 integration → 83% selection, No I6 → 0.19% selection. Correlation is PERFECT."

But the CIS aggregator is weighted on I6 confluence scores. Of course I6-integrated signals get selected more — they directly satisfy the selection criterion. This is not evidence that I6 integration improves trading profitability. It is evidence that I6-integrated signals score higher on an I6-weighted aggregator.

**The correct conclusion**: I6 integration should be added to all 21 setups because it provides cross-timeframe confirmation (sound architectural principle), NOT because selection rate correlation proves it improves profitability. The profitability case requires outcome data.

### Problem 4: Architectural Enforcement Must Be Empirically Grounded

The "Mandatory Pattern 1: Minimum 4 Confidence Factors" enforcement (base class `ArchitectureViolation`) is premature. GOOD setups happen to have 4+ factors. That does not mean 4 factors causes quality — it correlates with careful implementation. Mandating 4 factors in a base class without empirical backing is cargo-cult architecture that will be gamed (trivial dummy factors to satisfy the check).

**Revised position**: Enforce I6 integration (architectural — cross-timeframe confirmation is a sound principle). Do NOT enforce a specific factor count at the base class level. Let the empirical validation gate (shadow mode, p<0.05) enforce quality.

---

**What this IS**:
- ✅ About stopping noise creation at the source (I7 signal generation logic)
- ✅ About fixing data pipeline validation (upstream feature quality)
- ✅ About enforcing Renaissance-grade design patterns (architectural rigor)

| Finding | Evidence | Renaissance Violation |
|----------|----------|----------------------|
| Pattern detection data flow broken | 795K signals fired, but ZERO pattern fields persisted to DB | DAG invariant violated |
| OFI/CVD microstructure data noisy | 1.59M OFI signals, 0.18% selected — no magnitude threshold | Data quality over model complexity |
| Confidence formulas meaningless | OFI formula: `0.50 + abs(ofi) * 0.001` — scale has no meaning | Instrument everything |
| I6 confluence not integrated | 6 GOOD setups use I6 (83% selection), 21 NOISY ignore it (0.19% selection) | Separation of concerns |
| Regime filtering absent | PatternCompletion fires in ALL regimes | Segment relentlessly |
| **Stop losses inside entry zones** | **793 stopped_at_entry signals — stops hit IMMEDIATELY upon zone entry** | **Deterministic DAG — stop placement must respect zone boundaries** |

**The root cause**: Upstream feature calculation (I1/I5) → Pipeline persistence (intelligence_features) → Downstream consumption (I7 setups) — data flow has **ZERO validation gates**. Broken data propagates silently through the DAG.

---

## Part I: The Problem — Why CIS Gates Are NOT The Solution

**Common misconception**: "The aggregator is rejecting too many signals. Let's fix the CIS gates."

**Renaissance reality**: CIS gates are working CORRECTLY. They're filtering noise. The problem is that we're CREATING noise in the first place.

### Evidence: CIS Gates Work Correctly

**CIS score analysis** (from investigation docs):

| Setup | Total | Selected | Select % | Selected CIS | Rejected CIS | CIS Gap |
|-------|-------|----------|----------|--------------|-------------|---------|
| OFIContinuation | 182K | 36 | 0.02% | -0.032 | -0.046 | +0.014 |
| PatternCompletion | 77K | 66 | 0.09% | -0.013 | -0.039 | +0.026 |
| VWAPReversion | 50K | 46 | 0.09% | **+0.040** | -0.070 | **+0.110** |

**Key insight**: Selected signals have HIGHER CIS scores. The aggregator is working correctly — it's filtering low-confluence signals.

**The problem**: These setups generate mostly low-quality signals to begin with.

### The Real Problem: Creating Noise at Source

**trad_OFIContinuation example**:
```python
# Current (BROKEN):
# Fires when OFI maintains direction for 5 consecutive bars
# Any non-zero OFI qualifies (OFI=10 fires same as OFI=1000)
if ofi_ewma != 0.0:
    track_consecutive_bars()  # After 5 bars: FIRE!
# Result: 1.59M signals fired, 2.8K selected (99.82% NOISE)
```

**Why this creates noise**:
- No minimum OFI magnitude threshold (OFI=10 is meaningless)
- Meaningless confidence formula: `0.50 + abs(ofi) * 0.001`
- No I6 confluence integration (no cross-timeframe confirmation)
- No regime filtering (fires in all market conditions)

**Renaissance fix**:
```python
# Fixed (RENAISSANCE):
# Require meaningful OFI magnitude
if abs(ofi_ewma_20) < 500:  # Magnitude threshold
    return no_signal()  # Don't create noise signal

# Require cross-timeframe confirmation
ctf_score = features.get("ctf_score", 0.0)
if abs(ctf_score) < 0.3:  # I6 confluence gate
    return no_signal()  # Don't create noise signal

# Multi-factor confidence (not single meaningless formula)
raw_conf = (
    0.35 * min(1.0, abs(ofi_ewma_20) / 1000.0) +  # OFI magnitude
    0.25 * min(1.0, consecutive_bars / 10.0) +       # Persistence
    0.20 * hmm_regime_weight(features, "trend") +   # Regime alignment
    0.20 * min(1.0, abs(ctf_score))             # I6 confluence
)
# Result: Target ~200K signals fired, ~40K selected (20% SNR)
# Noise eliminated: 1.4M signals NEVER CREATED
```

**The goal**: Stop creating the 1.4M noise signals in the first place. Don't fire them hoping CIS gates will filter them. Fire fewer, higher-quality signals.

---

## Part I: The Problem — Data Flow Perspective

### DAG Topology: Where The Pipeline Breaks

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Intelligence Pipeline                             │
│                                                                              │
│  I1 (29 plugins) → I2 (11) → I3 (9) → I4 (13) → I5 (16) → SMC (16) →   │
│       │                  I6 (7) → I7 (30 setups → 7.85M signals)           │
│       │                                                                     │
│       └──> StreamMerger → intelligence.journal (tiered JSONB)              │
│                        ↓                                                    │
│                  FeatureWriter → intelligence_features (2.2M rows)          │
│                        ↓                                                    │
│                  SignalWriter → signal_ledger (7.85M signals)               │
└─────────────────────────────────────────────────────────────────────────┘
```

**The break**: FeatureWriter persists `intelligence_features` but **does not validate** that tier outputs match what plugins produced. Silent data corruption occurs between plugin output and DB persistence.

### Data Flow Validation: ZERO Gates

**Current state** (BROKEN):
```
I1 Plugin: produces ofi_ewma_20 = 100
  ↓ (no validation)
StreamMerger: merges into tiered JSONB
  ↓ (no validation)
FeatureWriter: writes to intelligence_features
  ↓ (no validation)
intelligence_features.ofi_ewma_20 = NULL (data lost!)
  ↓
I7 Plugin: reads NULL, fires signal anyway
```

**Renaissance state** (CORRECT):
```
I1 Plugin: produces ofi_ewma_20 = 100
  ↓
StreamMerger: validates tier structure → publishes parity event
  ↓
FeatureWriter: validates fields persisted → publishes parity event
  ↓
ParityAuditor: compares plugin output vs DB content → alerts on mismatch
  ↓
I7 Plugin: guaranteed to read what I1 produced
```

**The violation**: "What fails silently?" — Pattern detection data fields (dt_db_confidence, hs_confidence, tri_confidence) are produced by I5 detectors but never persisted to `pattern_detections` JSONB column. PatternCompletion fires 795K signals on **phantom data**.

---

### Critical Finding: Stop Losses Inside Entry Zones (793 Dead-on-Arrival Signals)

**Lifecycle mechanics** (Renaissance invariant):
```
1. Signal created with entry_zone_low/high (e.g., [100.00 - 100.50])
2. Price enters zone → ACTIVATION
3. Stop loss MUST be OUTSIDE zone:
   - Long: stop < zone_low (e.g., stop = 99.90)
   - Short: stop > zone_high (e.g., stop = 100.60)
```

**The violation**: 793 signals with outcome `stopped_at_entry` — stop losses placed INSIDE entry zones, causing immediate failure upon activation.

**Affected setups** (worst offenders):

| Setup | Failed Signals | Avg Stop Distance | Root Cause |
|-------|---------------|-------------------|-------------|
| **trad_OFIContinuation** | 324 | 0.35 ATR | Stop calc ignores zone width |
| **trad_PatternCompletion** | 132 | 0.58 ATR | Stop placed at zone edge |
| **trad_OFIDivergence** | 67 | 0.31 ATR | Stop inside zone |
| trad_FailedBreakout | 34 | 0.71 ATR | Marginal buffer |

**Why this happens**:

```python
# BROKEN (current):
stop_distance = atr * 0.35  # Fixed multiple
stop_loss = entry_price - stop_distance  # IGNORES zone width
# Result: stop_loss can be INSIDE [zone_low, zone_high]

# RENAISSANCE (correct):
# Pattern: Stop must be OUTSIDE zone
zone_width = zone_high - zone_low
min_buffer = max(atr * 0.5, zone_width * 0.2)  # 0.5 ATR OR 20% zone width
stop_loss = zone_low - min_buffer  # Always BELOW zone for longs
```

**The Renaissance principle**: Every signal must have a non-zero trading window. If stop ≤ zone_low (for longs), the window is zero — this is a deterministic bug, not a probabilistic loss.

**Impact**: 793 signals dead-on-arrival = 0.01% of total, but reveals fundamental stop placement logic flaw affecting ALL setups.

---

## Part II: Cluster Analysis — BAD INPUTS (#1 Priority)

### Cluster Breakdown: All 30 I7 Setups

| Cluster | Setups | Signals | Selected | Select % | Signal Share |
|---------|--------|---------|----------|----------|--------------|
| **GOOD** | 6 | 1.24M | 1.03M | **83.43%** | 15.74% |
| **MODERATE** | 3 | 2.15M | 837K | **38.94%** | 27.39% |
| **NEEDS_REFACTOR** | 21 | 4.47M | 8.6K | **0.19%** | **56.88%** |

**Key insight**: 21 setups (NEEDS_REFACTOR) have **SOUND TRADING IDEAS** but consume **BAD DOWNSTREAM DATA**. The problem is not the signal concepts — it's the data feeding them.

### Cluster A: GOOD Setups (6 setups, 83.43% selection)

**What makes them work**: They consume **VALIDATED downstream data** and follow Renaissance design patterns.

| Setup | Total | Selected | Select % | Pattern |
|-------|-------|----------|----------|---------|
| trad_TrendFollowing | 654K | 654K | **100.00%** | Multi-factor + I6 + strict gates |
| trad_MeanReversion | 14 | 13 | **92.86%** | HMM regime alignment |
| trad_LiquiditySweepReclaim | 333K | 229K | **68.81%** | Dual gates + I6 + continuous weights |
| trad_CHoCHReversal | 232K | 139K | **59.71%** | I6 confluence + zone penalties |
| trad_SqueezeExpansion | 7.8K | 4.6K | **58.95%** | Multi-factor confidence |
| trad_SupplyDemandSetup | 8.4K | 4.3K | **51.10%** | I6 confluence integration |

**Pattern analysis — GOOD setups consume GOOD data**:
1. **Multi-factor confidence** (4-6 weighted factors, not single formulas)
2. **I6 confluence mandatory** (ctf_score, ctf_structure, ctf_trend integrated)
3. **Strict dual gates** (multiple conditions, not single thresholds)
4. **Continuous regime weighting** (hmm_regime_weight, not binary gates)
5. **Early gate optimization** (cheap checks before expensive extraction)
6. **Zone friction penalties** (subtract confidence for bad entries)

**Renaissance principle**: "Data quality over model complexity." GOOD setups work because they consume **high-quality validated inputs** and apply **ensemble decision-making**.

### Cluster B: NEEDS_REFACTOR Setups (21 setups, 0.19% selection)

**What's broken**: They consume **BAD DOWNSTREAM DATA** (or ignore good data) and violate Renaissance design patterns.

#### Top 5 Setups by Signal Volume

| Setup | Signals | Select % | IDEA (Sound?) | BROKEN INPUTS (#1 Priority) |
|-------|---------|----------|---------------|----------------------------|
| **trad_OFIContinuation** | 1.59M | 0.18% | ✅ Sustained OFI = conviction | ❌ No OFI magnitude threshold, meaningless formula |
| **trad_PatternCompletion** | 795K | 0.15% | ✅ Pattern completion = signal | ❌ Pattern fields NOT persisted to DB (phantom data) |
| **trad_AnchoredVWAPReversion** | 394K | 0.20% | ✅ VWAP reversion | ✅ Logic sound, low selection = strict gates (correct) |
| **trad_GapAnalysisSetup** | 331K | 0.59% | ✅ Gaps = opportunities | ❌ 0.3 ATR threshold too loose |
| **trad_CVDDivergence** | 250K | 0.05% | ✅ CVD divergence | ❌ No CVD magnitude threshold |

#### Pattern Analysis — BAD INPUTS propagate through pipeline

**Pattern N1: Microstructure Features Have No Validation**

| Setup | Consumes | Problem | Fix |
|-------|----------|---------|-----|
| trad_OFIContinuation | `ofi_ewma_20` | No magnitude check (OFI=10 fires) | Add: `if abs(ofi_ewma_20) < 500: return no_signal()` |
| trad_OFIDivergence | `ofi_divergence` | No magnitude check (any value fires) | Add: `if abs(ofi_divergence) < 1.0: return no_signal()` |
| trad_OFISpike | `ofi_spike_z` | No magnitude check (spike definition unclear) | Add: `if abs(ofi_spike_z) < 2.0: return no_signal()` |
| trad_CVDDivergence | `cvd_divergence` | No magnitude check (any divergence fires) | Add: `if abs(cvd_divergence) < 0.5: return no_signal()` |
| trad_CVDSpike | `cvd_spike_z` | No magnitude check (spike definition unclear) | Add: `if abs(cvd_spike_z) < 2.0: return no_signal()` |

**Renaissance violation**: "Data quality over model complexity." Microstructure features (I1) produce raw values but I7 setups don't validate magnitude. **OFI=10 and OFI=1000 are treated the same** — both fire after 5 consecutive bars.

**Root cause**: I1 plugins produce unvalidated outputs. No data quality gate exists between microstructure calculation and signal consumption.

**Pattern N2: Pattern Detection Data Flow Completely Broken**

| Setup | Consumes | Problem | Root Cause |
|-------|----------|---------|------------|
| trad_PatternCompletion | `dt_db_confidence`, `hs_confidence`, `tri_confidence` | Fires on phantom data | I5 detectors produce output, but fields NOT persisted to DB |

**Evidence**:
- `intelligence_features` has 2.2M rows
- `pattern_detections` JSONB column exists in all rows
- **ZERO rows contain pattern fields** (dt_db_confidence, hs_confidence, tri_confidence)
- Yet `trad_PatternCompletion` generated 795K signals

**Investigation findings**:
1. I5 pattern detectors (DoubleTB, HS, Triangle) DO produce output (code is correct)
2. Pattern fields NOT persisted to `pattern_detections` JSONB column
3. PatternCompletion fires on **fallback logic or in-memory state** that doesn't reflect reality

**Renaissance violation**: DAG invariant broken. I5→I7 data flow has **zero validation**. Broken data propagates silently.

**Pattern N3: Confidence Formulas Have No Statistical Meaning**

| Setup | Formula | Problem | Fix |
|-------|---------|---------|-----|
| trad_OFIContinuation | `0.50 + abs(ofi_ewma_20) * 0.001` | OFI=10→conf=0.51, OFI=500→conf=1.0 | Replace with multi-factor: OFI magnitude + persistence + regime + I6 |
| trad_PatternCompletion | `best_confidence * 0.9` | If best=0.51, output=0.46 (near floor) | Raise threshold: 0.50→0.70, add I6 confluence |
| trad_GapAnalysisSetup | `min(1.0, gap_size_atr / 2.0)` | 0.3 ATR gap = 0.15 confidence (too low) | Tighten threshold: 0.3→0.8 ATR, add I6 confluence |

**Renaissance violation**: "Instrument everything." No metric tracks whether confidence correlates with selection. Formulas are invented, not validated.

**Pattern N4: I6 Confluence Completely Ignored**

| Setup | I6 Integration | Problem | Fix |
|-------|----------------|---------|-----|
| 21/21 NEEDS_REFACTOR setups | ❌ None | No cross-timeframe confirmation | Add: `ctf_score` mandatory, `ctf_structure`/`ctf_trend` recommended |
| 6/6 GOOD setups | ✅ Full integration | Cross-timeframe confirmation | Already correct |

**Correlation**: Setups WITH I6 integration = 83.43% selection. Setups WITHOUT I6 integration = 0.19% selection.

**Renaissance violation**: "Separation of concerns." I6 confluence is a **mandatory layer**, not optional. Cross-timeframe confirmation should be enforced at the architectural level, not left to individual setup discretion.

---

## Part III: Root Cause Analysis — Downstream Data Points

### Root Cause 1: No Data Quality Gates Between Pipeline Stages

**Problem**: Data flows from I1→I2→I3→I4→I5→SMC→I6→I7 with **ZERO validation** at each stage.

**Current DAG** (BROKEN):
```
I1 Plugin → produces output → no validation → StreamMerger
  ↓
StreamMerger → merges tiers → no validation → intelligence.journal
  ↓
FeatureWriter → writes to DB → no validation → intelligence_features
  ↓
SignalWriter → reads DB → no validation → signal_ledger
```

**Renaissance DAG** (CORRECT):
```
I1 Plugin → produces output → ParityAuditor validates → StreamMerger
  ↓
StreamMerger → merges tiers → ParityAuditor validates → intelligence.journal
  ↓
FeatureWriter → writes to DB → ParityAuditor validates → intelligence_features
  ↓
SignalWriter → guaranteed to read what I1 produced → signal_ledger
```

**Violation**: "What fails silently?" — PatternCompletion fires 795K signals on phantom data because NO validation gate caught that pattern fields weren't persisted.

### Root Cause 2: Microstructure Features Lack Magnitude Semantics

**Problem**: I1 microstructure plugins (OFI, CVD) produce raw values but I7 setups don't validate whether those values are **meaningful**.

**Example**: trad_OFIContinuation
```python
# I1 produces: ofi_ewma_20 = 10 (small imbalance)
# I7 consumes: ANY non-zero value fires after 5 consecutive bars
if ofi_ewma != 0.0:
    count_consecutive_bars()  # OFI=10 counts same as OFI=1000
```

**Renaissance violation**: "Data quality over model complexity." OFI=10 and OFI=1000 are treated identically. **Magnitude semantics are missing**.

**Fix**: Define magnitude thresholds based on instrument characteristics:
```python
# GOOD: Magnitude-aware filtering
MIN_OFI_MAGNITUDE = {
    "ES": 500,    # E-mini S&P: 500 contracts = meaningful imbalance
    "NQ": 200,    # Nasdaq: 200 contracts
    "CL": 1000,   # Crude: 1000 contracts
    "GC": 500,    # Gold: 500 contracts
}
```

### Root Cause 3: Confidence Formulas Not Calibrated to Outcomes

**Problem**: Confidence formulas are invented, not empirically validated.

**Example**: trad_OFIContinuation
```python
# Formula: 0.50 + abs(ofi_ewma_20) * 0.001
# OFI=10 → conf=0.51 (barely above floor)
# OFI=500 → conf=1.0 (maximum)
# Question: Does confidence correlate with win rate?
# Answer: UNKNOWN — no metric tracks this
```

**Renaissance violation**: "Instrument everything." No metric exists for `signal_confidence_calibration{setup_plugin}` — correlation between confidence and `was_selected`.

**Fix**: Add calibration metric and alert:
```python
# Metric: signal_confidence_calibration{setup_plugin}
# Query: CORR(confidence, was_selected) 
# Alert if: correlation < 0.3 (confidence not predictive)
```

### Root Cause 4: I6 Confluence Not Architecturally Mandated

**Problem**: I6 confluence (cross-timeframe confirmation) is **optional**, not enforced by architecture.

**Evidence**:
- 6 GOOD setups: All integrate I6 → 83.43% selection
- 21 NEEDS_REFACTOR setups: 0 integrate I6 → 0.19% selection
- Correlation is PERFECT: I6 integration ↔ high selection

**Renaissance violation**: "Separation of concerns." I6 confluence is a **layer**, not a feature. Should be architecturally mandatory, not setup-optional.

**Fix**: Enforce at base class level:
```python
@dataclass
class PatternPlugin:
    # NEW: Architectural enforcement
    requires_i6_confluence: bool = True  # Mandatory for all I7
    
    def compute_full(self, frames):
        # Validate I6 confluence present
        if self.requires_i6_confluence:
            ctf_score = features.get("ctf_score")
            if ctf_score is None:
                raise ArchitectureViolation(
                    f"{self.name} requires I6 confluence but ctf_score not provided"
                )
```

### Root Cause 5: Pattern Detection Data Flow Has No Parity Check

**Problem**: I5 pattern detectors produce output, but persistence to DB is **not validated**.

**Evidence**:
- I5 detectors: DoubleTB, HS, Triangle (code is correct)
- Expected: `pattern_detections` JSONB column contains dt_db_confidence, hs_confidence, tri_confidence
- Actual: ZERO rows contain these fields (2.2M rows checked)
- Result: PatternCompletion fires 795K signals on **phantom data**

**Renaissance violation**: DAG invariant broken. "What fails silently?" — PatternCompletion fires on non-existent pattern data for months, zero alert.

**Fix**: Add FeatureParityAuditor to validate plugin output vs DB content:
```python
class FeatureParityAuditor(BaseAgent):
    """Validates that plugin outputs are correctly persisted to DB."""
    
    def audit_i5_patterns(self):
        """Check I5 pattern fields in DB."""
        expected_fields = ["dt_db_confidence", "hs_confidence", "tri_confidence"]
        for field in expected_fields:
            count = db.query(f"""
                SELECT COUNT(*) FILTER (WHERE pattern_detections ? '{field}')
                FROM intelligence_features
            """)
            if count == 0:
                self.alert(f"Pattern field '{field}' not persisted to DB")
                # Alert: PatternCompletion firing on phantom data!
```

---

## Part IV: Renaissance Council Blueprint — Production Hardening

### Blueprint Principle: Fix The Data Pipeline, Not The Signal Ideas

**Renaissance approach**: The 21 NEEDS_REFACTOR setups have **SOUND TRADING IDEAS** but consume **BAD DATA**. We fix the pipeline, not delete the concepts.

**Council decision**: 
- ✅ KEEP all 30 signal concepts (ideas are sound)
- ❌ REJECT broken data flow (pipeline is broken)
- ✅ ENFORCE 6 GOOD patterns (architectural mandate)
- ✅ ADD parity validation (catch silent failures)
- ✅ EARN promotion through proof (shadow mode, p<0.05, sufficient N)

### Blueprint Architecture: Production-Grade Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Production Intelligence Pipeline                      │
│                                                                              │
│  I1 Plugin (29) ──┬──> StreamMerger ──┬─> FeatureWriter ──┬──> DB         │
│  I2 Plugin (11) ──┤      (merges)       │    (persists)      │   (validated) │
│  I3 Plugin (9)  ───┤                   │                   │               │
│  I4 Plugin (13) ──┤                   └─> ParityAuditor ◀──┴─> Alerts      │
│  I5 Plugin (16) ──┤                         (validates)                     │
│  SMC Plugin (16)───┤                                                         │
│  I6 Plugin (7)  ───┤                                                         │
│                   ┌┴──────────────────────────────────────────────┐    │
│                   │  I7 Plugin (30) ← All consume VALIDATED data    │    │
│                   │  - Multi-factor confidence (mandatory)          │    │
│                   │  - I6 confluence (architecturally enforced)      │    │
│                   │  - Strict dual gates (mandatory)                │    │
│                   │  - Continuous regime weighting (mandatory)       │    │
│                   │  - Early gate optimization (mandatory)           │    │
│                   │  - Zone friction penalties (mandatory)           │    │
│                   └────────────────────┬───────────────────────────────┘    │
│                                        ↓                                 │
│                              SignalWriter (validated inputs)             │
│                                        ↓                                 │
│                              signal_ledger (high quality)              │
└─────────────────────────────────────────────────────────────────────────┘
```

**Key invariants**:
1. **ParityAuditor validates every pipeline stage** (I1→merger→DB)
2. **All I7 setups consume validated data** (no phantom inputs)
3. **I6 confluence architecturally enforced** (base class validation)
4. **Confidence formulas calibrated** (correlation metric tracked)
5. **Microstructure features have magnitude semantics** (thresholds defined)

### Blueprint Part 1: Refactor Top 5 Setups (Fix Implementation, Keep Ideas)

#### 1. trad_OFIContinuation (1.59M signals, 0.18% selected)

**IDEA**: ✅ Sustained OFI direction = conviction (sound concept)

**BROKEN INPUTS**:
- No OFI magnitude threshold (OFI=10 fires same as OFI=1000)
- Meaningless confidence formula: `0.50 + abs(ofi_ewma_20) * 0.001`
- No I6 confluence integration
- No regime filtering (relies on aggregator)

**RENAISSANCE FIX**:
```python
# BEFORE (broken):
raw_conf = 0.50 + abs(ofi_ewma_20) * 0.001  # Meaningless scale
if count < _MIN_CONSECUTIVE_BARS:  # Any magnitude fires
    return no_signal()

# AFTER (fixed — Phase 118 intrinsic-only):
# Extrinsic factors (ctf_score, hmm_regime_weight, zone friction) are captured
# in the ML feature path but NOT used in confidence. Confidence = intrinsic quality only.
raw_conf = (
    0.45 * min(1.0, abs(ofi_ewma_20) / 1000.0) +  # OFI magnitude (capped)
    0.35 * min(1.0, consecutive_bars / 10.0) +       # Persistence
    0.20 * ofi_direction_consistency,               # Signal consistency (intrinsic)
)

# Pattern G3: Strict dual gates
MIN_OFI_MAGNITUDE = 500  # Magnitude threshold (empirically derived)
MIN_CONSECUTIVE_BARS = 10  # Tighten from 5
if abs(ofi_ewma_20) < MIN_OFI_MAGNITUDE:
    return no_signal()  # Magnitude gate
if consecutive_bars < MIN_CONSECUTIVE_BARS:
    return no_signal()  # Persistence gate

# Extrinsic features captured for ML training (not confidence):
capture_signal_features(features, direction, "microstructure", confidence)
```

**Shadow mode validation**: Run with `IS_SHADOW=True` until p<0.05, N≥100, win rate>50%.

#### 2. trad_PatternCompletion (795K signals, 0.15% selected)

**IDEA**: ✅ Chart pattern completion = signal (sound concept)

**BROKEN INPUTS**:
- Pattern fields NOT persisted to DB (phantom data)
- Confidence threshold 0.50 is noise floor
- No I6 confluence integration
- No regime filtering (`regime_type="any"`)

**RENAISSANCE FIX**:

**Step 1: Fix data flow bug** (ParityAuditor catches this)
```python
class FeatureParityAuditor:
    def audit_pattern_fields(self):
        """Validate I5 pattern outputs are persisted."""
        query = """
            SELECT COUNT(*) FILTER (WHERE pattern_detections ? 'dt_db_confidence')
            FROM intelligence_features
        """
        count = db.execute(query)
        if count == 0:
            self.alert("CRITICAL: Pattern fields not persisted to DB!")
            # PatternCompletion firing on phantom data
```

**Step 2: Refactor PatternCompletion**
```python
# BEFORE (broken):
confidence_threshold: float = 0.5  # Noise floor
regime_type: str = "any"  # Fires in all regimes

# AFTER (fixed — Phase 118 intrinsic-only):
# hmm_regime_weight, ctf_score, ctf_structure captured in ML features; NOT in confidence.
confidence_threshold: float = 0.70  # Require high confidence
regime_type: str = "trend"  # Only fire in trending regimes

# Confidence = intrinsic pattern quality only
raw_conf = (
    0.50 * best_confidence +  # Primary pattern quality (intrinsic)
    0.30 * pattern_completion_strength +  # How far pattern extended (intrinsic)
    0.20 * min(1.0, pattern_age_bars / 20.0),  # Pattern maturity (intrinsic)
)
# Extrinsic features captured for ML (not confidence):
capture_signal_features(features, direction, "pattern", confidence)
```

#### 3. trad_AnchoredVWAPReversion (394K signals, 0.20% selected)

**IDEA**: ✅ VWAP reversion in ranging regimes (sound concept)

**ASSESSMENT**: ✅ Setup logic is SOUND. Low selection (0.20%) reflects strict gating, NOT broken logic.

**Evidence from docs**: Selected signals have CIS score +0.040 (positive). Setup works when conditions align.

**RENAISSANCE DECISION**: KEEP AS-IS. No refactor needed. This is how Renaissance-grade setups behave — strict gates, low selection, high quality.

#### 4. trad_GapAnalysisSetup (331K signals, 0.59% selected)

**IDEA**: ✅ Gap openings = opportunities (sound concept)

**BROKEN INPUTS**:
- Threshold too loose: 0.3 ATR = 3 ticks on ES (fires constantly)
- No I6 confluence integration
- No regime filtering

**RENAISSANCE FIX**:
```python
# BEFORE (broken):
min_gap_atr_mult: float = 0.3  # Too loose

# AFTER (fixed — Phase 118 intrinsic-only):
# ctf_score captured in ML features; NOT added to confidence.
min_gap_atr_mult: float = 0.8  # Require meaningful gaps (0.8x ATR)

# Confidence = intrinsic 4-factor composite (geo + vol + timing + type)
raw_conf = (
    0.35 * geo_score +     # Gap magnitude quality (intrinsic)
    0.30 * vol_score +     # Volume confirmation (intrinsic)
    0.20 * timing_score +  # Session timing (intrinsic, floored at 0.2)
    0.15 * type_score,     # Gap type quality (intrinsic)
)
# Extrinsic features captured for ML (not confidence):
capture_signal_features(features, direction, "gap", confidence)
```

#### 5. trad_CVDDivergence (250K signals, 0.05% selected)

**IDEA**: ✅ CVD divergence = mean reversion (sound concept)

**BROKEN INPUTS**:
- No CVD magnitude threshold (any non-zero fires)
- No I6 confluence integration
- Confirmation threshold too loose (3 bars)

**RENAISSANCE FIX**:
```python
# BEFORE (broken):
if cvd_div == 0.0:  # Any non-zero qualifies
    return no_signal()

# AFTER (fixed — Phase 118 intrinsic-only):
# ctf_score captured in ML features; NOT added to confidence.
MIN_CVD_DIVERGENCE = 0.002  # Magnitude threshold (empirically derived from data)
if abs(cvd_div) < MIN_CVD_DIVERGENCE:
    return no_signal()

# Tighten confirmation
_CONFIRMATION_BARS: int = 5  # From 3

# Confidence = intrinsic quality only (divergence magnitude + confirmation strength)
raw_conf = (
    0.50 * min(1.0, abs(cvd_div) / CVD_SCALE) +  # Divergence magnitude (intrinsic)
    0.30 * min(1.0, confirmation_bars / 8.0) +    # Persistence (intrinsic)
    0.20 * price_confirmation_score,              # Price action alignment (intrinsic)
)
# Extrinsic features captured for ML (not confidence):
capture_signal_features(features, direction, "microstructure", confidence)
```

### Blueprint Part 2: Enforce Architectural Patterns (Mandatory for All I7)

**Renaissance principle**: "Component reuse over duplication." Create a shared template that enforces correctness.

#### Mandatory Pattern 1: Intrinsic-Only Confidence (Phase 118 Decision)

> **REVISED (2026-06-09, Phase 118)**: Factor-count enforcement at the base class level was dropped (see Council Review Problem 4 above — cargo-cult architecture, gameable with trivial dummy factors). The mandate is now architectural separation: confidence = intrinsic signal quality only. Extrinsic factors (ctf_score, hmm_regime_weight, zone friction, exhaustion guards) are CAPTURED in the ML feature path but must NOT appear in the confidence formula. Quality is enforced by shadow mode promotion gates (p<0.05, N≥100), not by factor counts.

**Enforcement**: Code review + contract test (test_i7_extrinsic_contract.py)
```python
class PatternPlugin:
    def compute_full(self, frames):
        # Confidence = weighted intrinsic factors only
        # All factors must be measurable from the signal geometry itself,
        # NOT from regime, confluence, or zone context.
        raw_conf = self._compute_intrinsic_confidence(frames)
        return compose_confidence(raw_conf)
        
        # Extrinsic features captured separately for ML training:
        capture_signal_features(features, direction, self._capture_domain, raw_conf)
```

#### Mandatory Pattern 2: I6 Confluence — Captured, Not Gated in Confidence

> **REVISED (2026-06-09, Phase 118)**: ctf_score and other I6 fields must be CAPTURED in the ML feature snapshot (via capture_signal_features) but must NOT appear in the confidence formula. The requires_i6_confluence ClassVar enforces that the plugin declares its stance; it does NOT mean ctf_score is a confidence factor. This was the pre-Phase-118 intent; the code examples in earlier sections of this doc incorrectly showed ctf_score additive in confidence formulas.

**Enforcement**: requires_i6_confluence ClassVar + pre-commit hook (check 9) + contract test
```python
class PatternPlugin:
    requires_i6_confluence: ClassVar[bool]  # MANDATORY declaration for all I7
    
    def compute_full(self, frames):
        # ctf_score is available in features — use it in capture, not confidence:
        features = {**(frames.get("i6") or {}), ...}
        capture_signal_features(features, direction, self._capture_domain, confidence)
        # DO NOT: confidence += 0.20 * abs(features.get("ctf_score", 0.0))
```

#### Mandatory Pattern 3: Strict Dual Gates (Minimum 2 Independent Conditions)

**Enforcement**: Code review gate
```python
# Template for all I7 setups
def compute_full(self, frames):
    # Gate 1: Regime check (cheap)
    if not self._check_regime_gate(features):
        return no_signal()
    
    # Gate 2: Magnitude check (cheap)
    if not self._check_magnitude_gate(features):
        return no_signal()
    
    # NOW extract OHLCV (expensive)
    result = extract_ohlcv(frames, self.min_lookback)
```

#### Mandatory Pattern 4: Continuous Regime Weighting (No Binary Gates)

**Enforcement**: Code review gate
```python
# GOOD: Continuous weighting
regime_w = hmm_regime_weight(features, self.regime_type)
confidence += 0.10 * regime_w

# BAD: Binary gate (REJECTED in code review)
if hmm_regime == 0:
    confidence += 0.10
```

#### Mandatory Pattern 5: Early Gate Optimization (Performance)

**Enforcement**: Code template
```python
def compute_full(self, frames):
    # Pattern: Check cheap gates BEFORE expensive OHLCV extraction
    features = {**(frames.get("i1") or {}), **(frames.get("i6") or {})}
    
    # Early exit (cheap dict lookups)
    if not self._check_early_gates(features):
        return no_signal()
    
    # NOW do expensive numpy conversion
    result = extract_ohlcv(frames, self.min_lookback)
```

#### Mandatory Pattern 6: Zone Friction Penalties (Guard Against Bad Entries)

**Enforcement**: Code review gate
```python
# GOOD: Subtract confidence for bad entries
if direction == 1 and features.get("in_supply_zone") == 1.0:
    raw_conf -= 0.12 * features.get("supply_strength", 0.0)

# BAD: Only confirm, never guard (REJECTED in code review)
if fvg_confirmed:
    confidence += 0.15  # No penalty for bad structure
```

### Blueprint Part 3: Add Pipeline Validation (Catch Silent Failures)

**Renaissance principle**: "What fails silently?" — Add parity auditors to validate every pipeline stage.

#### FeatureParityAuditor: Validate Plugin Output → DB Persistence

```python
class FeatureParityAuditor(BaseAgent):
    """Validates that plugin outputs are correctly persisted to DB."""
    
    def audit_i5_patterns(self):
        """Check I5 pattern fields in intelligence_features."""
        expected_fields = [
            "dt_db_confidence", "hs_confidence", "tri_confidence",
            "dt_db_pattern", "hs_pattern", "tri_breakout_bias"
        ]
        
        for field in expected_fields:
            result = db.query(f"""
                SELECT COUNT(*) FILTER (WHERE pattern_detections ? '{field}')
                FROM intelligence_features
                WHERE ts >= NOW() - INTERVAL '1 hour'
            """)
            
            if result == 0:
                self.alert_critical(
                    f"Pattern field '{field}' not persisted to DB. "
                    f"I5 detectors may be producing output but FeatureWriter is dropping it."
                )
                # Page on-call: Data integrity violation
    
    def audit_i1_microstructure(self):
        """Check I1 microstructure fields for NULL/invalid values."""
        micro_fields = ["ofi_ewma_20", "cvd_divergence", "ofi_spike_z", "cvd_spike_z"]
        
        for field in micro_fields:
            result = db.query(f"""
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE {field} IS NULL) as null_count
                FROM intelligence_features
                WHERE ts >= NOW() - INTERVAL '1 hour'
            """)
            
            if result["null_count"] == result["total"]:
                self.alert_warning(
                    f"Microstructure field '{field}' is 100% NULL. "
                    f"I1 detector may be failing or FeatureWriter not persisting."
                )
```

#### ConfidenceCalibrationMonitor: Validate Confidence → Selection Correlation

```python
class ConfidenceCalibrationMonitor(BaseAgent):
    """Validates that confidence formulas predict selection."""
    
    def compute_calibration(self):
        """Compute correlation: confidence ↔ was_selected."""
        for setup in self._all_i7_setups:
            result = db.query(f"""
                SELECT
                    CORR(confidence, was_selected)::float as calibration,
                    COUNT(*) as n
                FROM signal_ledger
                WHERE setup_plugin = '{setup}'
                  AND timestamp >= NOW() - INTERVAL '7 days'
                GROUP BY setup_plugin
            """)
            
            calibration = result["calibration"]
            n = result["n"]
            
            # Publish metric
            self.metrics.gauge(
                "signal_confidence_calibration",
                calibration,
                {"setup_plugin": setup}
            )
            
            # Alert if confidence not predictive
            if n >= 100 and calibration < 0.3:
                self.alert_warning(
                    f"Setup '{setup}' has confidence calibration {calibration:.2f} "
                    f"(below 0.3 threshold). Confidence formula not predictive."
                )
                # Flag for refactor: trad_OFIContinuation would be caught here
```

### Blueprint Part 4: Shadow Mode Validation (Earn Promotion Through Proof)

**Renaissance principle**: "Earn the right through proof." All refactored setups run in shadow mode until statistically validated.

#### Shadow Mode Protocol

```python
class PatternPlugin:
    # Shadow mode flag
    IS_SHADOW: bool = True  # Start in shadow mode
    
    def compute_full(self, frames):
        signal = self._generate_signal(frames)
        
        # Log to shadow table (not promoted to active)
        signal["_shadow"] = self.IS_SHADOW
        return signal
```

#### Promotion Criteria

```python
class ShadowModeValidator(BaseAgent):
    """Validates shadow signals and promotes to production when proven."""
    
    def validate_promotion(self, setup_plugin):
        """Check if setup earned promotion through proof."""
        result = db.query(f"""
            SELECT
                COUNT(*) FILTER (WHERE was_selected = true) as selected,
                COUNT(*) FILTER (WHERE was_selected = false) as rejected,
                COUNT(*) as total,
                AVG(outcome_pnl_r) as avg_pnl_r
            FROM signal_ledger_shadow
            WHERE setup_plugin = '{setup_plugin}'
              AND timestamp >= NOW() - INTERVAL '30 days'
        """)
        
        selected = result["selected"]
        rejected = result["rejected"]
        total = result["total"]
        
        # Criterion 1: Sufficient sample size
        if total < 100:
            return False, f"Insufficient sample size: {total} < 100"
        
        # Criterion 2: Selection rate
        selection_rate = selected / total
        if selection_rate < 0.05:
            return False, f"Selection rate too low: {selection_rate:.2%} < 5%"
        
        # Criterion 3: Statistical significance (binomial test)
        from scipy.stats import binom_test
        p_value = binom_test(selected, total, 0.5, alternative='greater')
        if p_value >= 0.05:
            return False, f"Not statistically significant: p={p_value:.3f} ≥ 0.05"
        
        # Criterion 4: Positive expectancy
        avg_pnl_r = result["avg_pnl_r"]
        if avg_pnl_r <= 0:
            return False, f"Negative expectancy: {avg_pnl_r:.3f} ≤ 0"
        
        # All criteria passed → promote
        self.promote_to_production(setup_plugin)
        return True, "Promoted: p<0.05, N≥100, positive expectancy"
```

---

## Part V: Implementation Roadmap

> **REVISED 2026-06-08**: Reordered to fix deterministic bugs first, collect empirical data before guessing at thresholds, and weave in the schema migration at the lifecycle replay junction.

### Phase 0: Immediate Hotfixes (Before v2.9 Phases Begin)

**Goal**: Fix Category A deterministic bugs. These are correctness defects, not calibration questions. They do not require empirical data or shadow validation.

1. ~~**Fix PatternCompletion phantom data**~~ — **DONE (Phase 117, plan 117-01)**. 3-way column swap in `services/feature_writer.py` `_record_to_insert_params` corrected: I5 patterns → `pattern_detections`, I3 structure → `regime_features`, I4 context → `confluence_scores`. 5-test regression suite pins the mapping. `FeatureParityAuditor` deployed as the long-term guard (5-minute timer, raises alert on NULL `pattern_detections` fields).

2. ~~**Fix stop losses inside entry zones**~~ — **DONE**. `validate_stop_against_zone()` added to `src/intelligence/trading/plugin_utils.py`, called from `trade_framer.py:1018` immediately after zone bounds are resolved. Auto-corrects violations using 2.0 ATR buffer; raises `ValueError` for extreme misconfiguration (>3x ATR inside zone). Logs every correction via structlog for ongoing monitoring.

3. ~~**Fix `_CVD_DIV_THRESHOLD = 0.0` in `cvd_divergence.py`**~~ — **DONE (Phase 117, plan 117-00)**. Set to `0.002` (conservative floor eliminating floating-point noise). Gate comparison changed from `if cvd_div == 0.0:` to `if abs(cvd_div) < _CVD_DIV_THRESHOLD:` so the constant is now actually enforced.

4. ~~**Wire I6 into the 6 high-volume broken plugins**~~ — **DONE (Phase 117, plan 117-00)**. `ctf_score` wired as additive confidence contributor (`+= 0.15 * min(1.0, abs(ctf_score)/0.7)` when `abs(ctf_score) > 0.3`) in `cvd_divergence`, `ofi_continuation`, `gap_analysis_setup`, `divergence_stack`. `ofi_spike` and `cvd_spike` inherit the wiring via `detect_spike_signal` in `microstructure_utils.py`.

5. ~~**Wire `hmm_regime_weight()` into confidence for all 6 plugins**~~ — **DONE (Phase 117, plan 117-00)**. `hmm_regime_weight(features, direction_str)` wired as centered confidence factor (`+= 0.10 * (regime_w - 0.5)`) in all 6 plugins. Regime now influences confidence at source, not just aggregator gating downstream.

---

### Phase 1 (v2.9 Phase 117): Pipeline Validation + SignalProbeAuditor — **COMPLETE**

**Goal**: Add validation gates AND collect ground truth outcome data on unselected signals.

1. ~~**Deploy FeatureParityAuditor**~~ — **DONE**. Validates I5 pattern fields persisted to `pattern_detections`; runs on 5-minute systemd timer (`indicagent-feature-parity-auditor.timer`); emits `FEATURE_PARITY_NULL_FIELDS_TOTAL` OTel counter + `job_completed_total{job=feature-parity-auditor}`.

2. ~~**Deploy ConfidenceCalibrationMonitor**~~ — **DONE**. Computes `CORR(cis_score, was_selected::int)` per setup over 7-day window (gated N≥100); publishes `signal_confidence_calibration{setup_plugin}` OTel gauge; alerts when correlation < 0.3; runs on 30-minute timer (`indicagent-confidence-calibration-monitor.timer`).

3. ~~**Deploy SignalProbeAuditor**~~ — **DONE**. Daily timer (`indicagent-signal-probe-auditor.timer`, 03:30 UTC); samples 1% of unselected NEEDS_REFACTOR signals from last 2 days; simulates activation+outcome from `market_data_ohlcv`; writes pnl_r/mae/mfe/bars_in_trade to `signal_probe_results` (migration 120); emits `job_completed_total{job=signal-probe-auditor}`. Ground truth accumulation has started.

4. ~~**Enforce I6 integration at base class**~~ — **DONE**. `requires_i6_confluence: ClassVar[bool]` added to `PatternPlugin`; `ArchitectureViolation` raised at startup validation if missing; all 36 TIER_I7 plugins backfilled.

5. ~~**Code review gate**~~ — **DONE**. Pre-commit check 9 (`check_i6_confluence_declaration`) rejects new/modified I7 plugins without the `requires_i6_confluence` declaration. Pytest sweep over all TIER_I7 plugins also enforces this.

**Data collection window**: Started 2026-06-08. SignalProbeAuditor needs ≥100 activations per NEEDS_REFACTOR setup before Phase 1.5 can proceed (~2-3 weeks of market time).

---

### Phase 1.5 (v2.9 Phase 117.5 — NEW): Empirical Threshold Derivation

**Goal**: Derive magnitude thresholds and gate conditions from probe outcome data, not intuition.

1. **Analyze SignalProbeAuditor results per setup:**
   - Plot win rate vs OFI magnitude quartile → derive `MIN_OFI_MAGNITUDE` from where win rate crosses 50%
   - Plot win rate vs gap size → derive `min_gap_atr_mult` from data
   - Plot win rate vs consecutive bar count → derive minimum bar threshold

2. **Publish derivation report** — one page per NEEDS_REFACTOR setup showing the empirically derived threshold vs the original guess, with N and confidence interval.

3. **Update threshold constants in this document** — replace guessed values (`MIN_OFI_MAGNITUDE=500`, `min_gap_atr_mult=0.8`, etc.) with data-derived values before Phase 2 begins.

**Gate**: Phase 2 (top 5 refactors) does not begin until each setup's threshold is derived from ≥100 probe activations OR the probe shows the setup has near-zero edge (in which case the setup is moved to shadow-only with zero modifications until more data accumulates).

---

### Phase 2 (v2.9 Phase 118): Top 5 Setup Refactoring

> **REVISED (2026-06-09, Phase 118 plans finalized)**: The primary work is the extrinsic strip (Wave 0) applied system-wide before any individual setup refactor. Setup-specific refactors then build on the clean base. AnchoredVWAPReversion was removed from this phase (logic already sound); DivergenceStack (181K signals) was added as the 5th setup.

**Wave 0 (Plans 00 + 00b — system-wide)**: Strip all extrinsic modifiers (hmm_regime_weight, apply_exhaustion_guard/boost, ctf_score in confidence, zone friction) from all I7 plugins that had them. Restructure 3 composite-formula plugins (momentum_breakout, squeeze_expansion, trend_following) onto intrinsic-only weights. Contract test (test_i7_extrinsic_contract.py) proves extrinsic perturbation leaves confidence unchanged across the full blast radius.

**Top 5 individual refactors (Plans 01-05 — intrinsic-only confidence, shadow_only=True)**:
1. **trad_OFIContinuation** — intrinsic 3-factor: OFI magnitude + persistence + direction consistency; `MIN_OFI_MAGNITUDE` gate
2. **trad_PatternCompletion** — intrinsic 3-factor: pattern quality + completion strength + maturity; raise confidence threshold 0.5→0.7; `regime_type="trend"`
3. **trad_GapAnalysisSetup** — intrinsic 4-factor: geo + vol + timing + type; raise `min_gap_atr_mult` 0.3→0.8
4. **trad_CVDDivergence** — intrinsic 3-factor: divergence magnitude + persistence + price confirmation; `_CVD_DIV_THRESHOLD` derived from distribution (not 0.0)
5. **trad_DivergenceStack** — intrinsic confidence composite; structural refactor of stacking logic

All 5 deploy `shadow_only=True`. Confidence formulas contain no extrinsic factors — ctf_score, regime weights, and zone context remain in ML feature capture only.

---

### Phase 3 (v2.9 Phase 119): Remaining 16 Setup Refactoring — **COMPLETE**

**Goal**: Apply the same empirical pattern to all 16 remaining NEEDS_REFACTOR setups.

~~Same protocol: use Phase 1.5 derived thresholds where available; where probe data is still accumulating, add I6 integration and structural fixes only, leave magnitude thresholds at conservative values until data arrives.~~

**DONE (Phase 119, 2026-06-10)**: All 16 remaining NEEDS_REFACTOR setups refactored across 4 plans. Dual HMM+CTF gate before OHLCV extraction, 4-factor intrinsic confidence composites (weights sum 1.0), `shadow_only=True`, `requires_i6_confluence=True` on every plugin. `ArchitectureViolation` enforcement added for `requires_i6_confluence` across 29 non-exempt I7 plugins; `_I7_I6_EXEMPT` (8 deferred) and `_PHASE_119_PLUGINS` (17) frozensets. ORB15 and ORB30 refactored. All 21 NEEDS_REFACTOR setups now in shadow mode.

---

### Phase 4 (v2.9 Phase 120): Shadow Mode Validation — **COMPLETE**

~~All 21 refactored setups run shadow_only=True. Promotion criteria: p<0.05, N≥100, win_rate>50%, calibration_correlation>0.3. Note: this now validates that the empirically-derived thresholds work in production, not that our guesses were right.~~

**DONE (Phase 120, 2026-06-10)**: `services/shadow_validator.py` (315-line weekly oneshot) implements 5-gate sequential promotion check: (1) N≥100, (2) win_rate≥50% via binomtest p<0.05 vs 50% baseline, (3) avg_pnl_r>0, (4) calibration_corr>0.3, (5) low-variance guard. `shadow_auditor.py` stripped to demotion-only (SoC split). Systemd timer weekly Mon 07:00 UTC (`Persistent=true`). Grafana dashboard with 6 per-setup metrics. `signal_ledger_shadow` DB view live (15,914 rows).

**Important correction from implementation**: Gate 2 is `win_rate >= 50%` (binomtest), NOT `selection_rate >= 5%`. Shadow signals have `was_selected` structurally always False — they never enter the active pool — so a selection_rate gate is permanently unpassable. The code example in Blueprint Part 4 below is stale on this point.

---

### Phase 4.1 (post-Phase 120): Extrinsic Confidence Composite Layer

**The idea:** Phase 118 stripped extrinsic factors (ctf_score, hmm_regime_weight, zone friction, exhaustion) from plugin confidence formulas. Those factors have genuine predictive value — they were just being applied in the wrong place, at the wrong time, with made-up weights. The correct architecture applies them as a single calibrated multiplier *after* intrinsic confidence is computed, at the aggregator layer.

**Design:**
```
effective_confidence = intrinsic_confidence * extrinsic_multiplier(features)

extrinsic_multiplier = softmax-normalized composite of:
  - ctf_score          (I6 cross-timeframe confluence)
  - hmm_regime_weight  (regime alignment probability)
  - zone_friction      (supply/demand zone context)
  - exhaustion_guard   (delta exhaustion penalty)
```

Weights are learned per plugin-family from `features_snapshot` + `signal_ledger` outcomes. `ConfluenceWeightProfile` in `confidence_utils.py` already has the placeholder structure (all 0.0 now — these are the Phase 49 weights).

**Why this is better than inline additive:**
- Intrinsic confidence is a clean, reproducible signal for ML training
- Extrinsic composite can be retrained independently as the regime/zone models improve
- A single application point (`aggregator.py` or a post-processing step before aggregator scoring) means one place to audit, test, and tune
- Multiplier semantics: extrinsic context scales quality, it doesn't replace it (a 0.90-confidence signal in a perfect regime context stays near 0.90; it doesn't jump to 0.95 from arbitrary additive noise)

**Phase dependency:** Requires Phase 120 shadow data (N≥100 per family, outcomes recorded) before `ConfluenceWeightProfile` weights can be trained. Connection to Phase 122 (production hardening) and the `ConfidenceCalibrationMonitor` CORR metric.

**Files to update:** `confidence_utils.py` (fill non-zero weights in `FAMILY_PROFILES`), `aggregator.py` (apply composite before scoring), `confidence_calibration_monitor.py` (track calibration of effective vs intrinsic).

---

### Phase 4.5 (v2.10 Phases 123-125, woven in before replay): Schema Migration

**Goal**: Migrate to 3-table schema before lifecycle replay so replay writes into the clean architecture.

- Phase 123: 3-table decision recorded (confirmed), cardinality defined (1:1 enforced at application layer, schema allows 1:many), numeric type standardization (`NUMERIC` for all prices/PnL)
- Phase 124: DB migration — drop `signal_ledger`, create `signal_events` + `trade_framing` + `trade_execution`
- Phase 125: Rewrite SignalWriter, lifecycle_writer, all queries

**Why here**: Lifecycle replay (Phase 121) regenerates all signal outcomes anyway. Migrating before the replay means we replay directly into the clean schema rather than migrating 4M+ rows after the fact.

---

### Phase 5 (v2.9 Phase 121): Lifecycle Replay

Replay signal ledger with corrected setups. Writes into 3-table schema. Compare before/after: total signals, SNR per setup, selection rate.

---

### Phase 6 (v2.9 Phase 122): Production Hardening

FeatureParityAuditor + ConfidenceCalibrationMonitor + SignalProbeAuditor running continuously. All 30 setups validated.

---

## Part VI: Success Metrics

### Before: System in Crisis (Creating Noise at Source)

| Metric | Value | Assessment |
|--------|-------|------------|
| Total signals | 7.85M | **Creating 5.97M NOISE signals** |
| Selected signals | 1.88M | 24% selection rate |
| **NEEDS_REFACTOR SNR** | **0.19%** | **99.81% NOISE** |
| **GOOD setups SNR** | **83.43%** | **16.57% NOISE** |
| Pattern detection bug | 795K phantom signals | Creating noise from broken data |
| trad_OFIContinuation | 1.59M signals, 0.18% selected | **Creating 1.59M NOISE signals** |
| trad_PatternCompletion | 795K signals, 0.15% selected | **Creating 795K NOISE signals** |
| Confidence calibration | NOT TRACKED | Formulas invented, not validated |
| I6 confluence | OPTIONAL | Setups ignore cross-timeframe confirmation |
| Data flow validation | NONE | Silent failures create noise downstream |

### After: Production-Hardened System (Not Creating Noise)

| Metric | Target | Assessment |
|--------|--------|------------|
| Total signals | 4.0M | **Stopped creating 3.85M NOISE signals** |
| Selected signals | 1.6M | 40% selection rate |
| **All setups SNR target** | **40%+** | **60% NOISE or less** |
| trad_OFIContinuation SNR | 15-25% target | **Stopped creating 1.4M NOISE signals** |
| trad_PatternCompletion SNR | 15-25% target | **Stopped creating 700K NOISE signals** |
| Pattern detection bug | 0 | Fixed, stopped creating phantom signals |
| Confidence calibration | TRACKED | Metric validates formulas don't create noise |
| I6 confluence | MANDATORY | All setups use cross-timeframe confirmation |
| Data flow validation | CONTINUOUS | ParityAuditor stops noise at source |
| Shadow mode validation | REQUIRED | Setups proven not to create noise before promotion |

### SNR Improvement by Setup (The Goal in Action)

| Setup | Before SNR | After SNR Target | Noise Eliminated |
|-------|------------|------------------|-------------------|
| trad_OFIContinuation | 0.18% | 15-25% | **1.34M noise signals stopped** (from 1.59M → ~250K target) |
| trad_PatternCompletion | 0.15% | 15-25% | **700K noise signals stopped** (from 795K → ~95K target) |
| trad_CVDDivergence | 0.05% | 10-20% | **240K noise signals stopped** (from 250K → ~10K target) |
| trad_GapAnalysisSetup | 0.59% | 25-35% | **290K noise signals stopped** (from 331K → ~40K target) |
| trad_DivergenceStack | 0.16% | 10-20% | **170K noise signals stopped** (from 181K → ~11K target) |

**Total noise signals eliminated**: ~4.46M noise signals stopped (from the 21 NEEDS_REFACTOR setups). These signals are NEVER CREATED instead of being created and filtered downstream.

**This is the goal**: Stop creating noise at the source. Don't fire 100K signals hoping 200 are good. Fire 20K signals knowing 15K are good.

### Renaissance Principles Enforced

| Principle | Before | After |
|-----------|--------|-------|
| Instrument everything | Confidence formulas unvalidated | Calibration metric tracks correlation |
| Earn promotion through proof | Setups deployed without validation | Shadow mode mandatory, p<0.05 required |
| Segment relentlessly | Regime filtering optional | Continuous hmm_regime_weight mandatory |
| Data quality over model complexity | OFI=10 treated same as OFI=1000 | Magnitude thresholds defined |
| Never drop data | 21 setups would be deleted | All 30 ideas preserved, implementations fixed |
| What fails silently | PatternCompletion bug undetected | ParityAuditor catches all data flow issues |
| Separation of concerns | I6 confluence optional | I6 architecturally mandatory |
| DAG invariants | No validation between stages | ParityAuditor validates each stage |

---

## Part VII: Appendix

### Appendix A: Complete NEEDS_REFACTOR Setup List (21 setups)

All setups have **SOUND TRADING IDEAS** but **FLAWED IMPLEMENTATIONS**. Fix the code, keep the concepts.

| Setup | IDEA (Sound?) | BROKEN INPUTS | Priority |
|-------|---------------|---------------|----------|
| trad_OFIContinuation | ✅ Sustained OFI = conviction | No magnitude threshold, meaningless formula | 🔴 CRITICAL |
| trad_PatternCompletion | ✅ Pattern completion = signal | Data flow bug (phantom data), threshold too low | 🔴 CRITICAL |
| trad_AnchoredVWAPReversion | ✅ VWAP reversion | Logic sound, low selection = strict gates (correct) | ✅ KEEP |
| trad_GapAnalysisSetup | ✅ Gaps = opportunities | Threshold 0.3 ATR too loose | 🟠 HIGH |
| trad_CVDDivergence | ✅ CVD divergence | No magnitude threshold | 🟠 HIGH |
| trad_DivergenceStack | ✅ Divergence stack | Confidence formula needs fixing | 🟡 MEDIUM |
| trad_CandlestickPatternSetup | ✅ Candlestick patterns | Threshold too low | 🟡 MEDIUM |
| trad_FailedBreakout | ✅ Failed breakouts | Gates too loose | 🟡 MEDIUM |
| trad_OFIDivergence | ✅ OFI divergence | No magnitude threshold | 🟡 MEDIUM |
| trad_LiquidityHunt | ✅ Liquidity hunt | Confidence formula needs fixing | 🟡 MEDIUM |
| trad_CVDSpike | ✅ CVD spikes | Magnitude definition unclear | 🟡 MEDIUM |
| trad_OFISpike | ✅ OFI spikes | Magnitude definition unclear | 🟡 MEDIUM |
| trad_DualDivergence | ✅ Dual divergence | Confidence formula needs fixing | 🟢 LOW |
| trad_VWAPReclaim | ✅ VWAP reclaim | Gates could be stricter | 🟢 LOW |
| trad_DeltaExhaustion | ✅ Delta exhaustion | Confidence formula needs fixing | 🟢 LOW |
| trad_SessionExtremesSetup | ✅ Session extremes | Gates could be stricter | 🟢 LOW |
| trad_LVNBreakout | ✅ LVN breakout | Magnitude threshold needed | 🟢 LOW |
| trad_ORB15 | ✅ ORB | Gates could be stricter | 🟢 LOW |
| trad_ORB30 | ✅ ORB | Gates could be stricter | 🟢 LOW |
| trad_SecondLegContinuation | ✅ Second leg | Confidence formula needs fixing | 🟢 LOW |
| trad_VCP | ✅ Volume composite | Confidence formula needs fixing | 🟢 LOW |

**Common refactors across all 21 setups**:
1. Replace single-factor confidence with multi-factor (minimum 4 weighted factors)
2. Integrate I6 confluence (ctf_score mandatory, ctf_structure/ctf_trend recommended)
3. Replace loose single gates with strict dual gates
4. Replace binary/no regime filtering with continuous hmm_regime_weight
5. Add early gate optimization (cheap regime before expensive OHLCV)
6. Add zone friction penalties (subtract confidence for bad entries)

### Appendix B: GOOD Setup Pattern Template (Mandatory for All I7)

```python
from dataclasses import dataclass
from typing import Any

from ..plugins import InputSpec
from ..utils.gradient_utils import hmm_regime_weight
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import capture_signal_features, compose_confidence
from .plugin_utils import extract_ohlcv, no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade


@dataclass
class RenaissanceSignalPlugin:
    """Mandatory template following all 6 GOOD patterns.
    
    Renaissance principles:
    - Multi-factor confidence (minimum 4 weighted factors)
    - I6 confluence integration (architecturally mandatory)
    - Strict dual gates (minimum 2 independent conditions)
    - Continuous regime weighting (use hmm_regime_weight, not binary)
    - Early gate optimization (cheap before expensive)
    - Zone friction penalties (subtract for bad entries)
    """
    
    name: str = "trad_<SetupName>"
    regime_type: str = "trend"  # or "mean_reversion"
    
    # Pattern P2: I6 confluence architecturally mandatory
    requires_i6_confluence: bool = True
    
    # Pattern P1: Intrinsic-only confidence (Phase 118 decision)
    # Confidence = signal geometry quality only. Extrinsic factors (regime, ctf_score,
    # zone friction) are captured in the ML feature path — NOT used in confidence.
    def _compute_confidence(self, features: dict, direction: int, atr: float) -> float:
        """Intrinsic confidence scoring — setup geometry only, no extrinsic factors."""
        
        # Factor 1: Primary signal metric (setup-specific, intrinsic)
        factor1 = self._compute_primary_factor(features, direction)
        
        # Factor 2: Signal strength / magnitude (setup-specific, intrinsic)
        factor2 = self._compute_magnitude_factor(features, direction)
        
        # Factor 3: Signal persistence / confirmation (setup-specific, intrinsic)
        factor3 = self._compute_persistence_factor(features, direction)
        
        # Factor 4: Setup geometry quality (optional, intrinsic)
        factor4 = self._compute_structure_quality(features, direction)
        
        raw_conf = (
            0.40 * min(1.0, max(0.0, factor1)) +
            0.25 * min(1.0, max(0.0, factor2)) +
            0.20 * min(1.0, max(0.0, factor3)) +
            0.15 * min(1.0, max(0.0, factor4))
        )
        
        # Zone friction, regime weighting, ctf_score: captured in ML features,
        # NOT subtracted/added here.
        return raw_conf
    
    # Pattern P5: Early gate optimization (cheap before expensive)
    def compute_full(self, frames: dict) -> dict:
        """Generate signal with Renaissance-grade validation."""
        
        # Extract features first (cheap dict lookups)
        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
            **(frames.get("i6") or {}),
        }
        
        # Pattern P2: Validate I6 confluence present
        if self.requires_i6_confluence:
            ctf_score = features.get("ctf_score")
            if ctf_score is None:
                raise ValueError(
                    f"{self.name} requires I6 confluence but ctf_score not provided"
                )
        
        # Pattern P3: Strict dual gates (cheap checks FIRST)
        gate1_passed = self._check_gate1(features)
        if not gate1_passed:
            return no_signal()  # Early exit before expensive OHLCV
        
        gate2_passed = self._check_gate2(features)
        if not gate2_passed:
            return no_signal()  # Early exit before expensive OHLCV
        
        # NOW extract OHLCV (expensive numpy conversion)
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        
        # Compute confidence with multi-factor formula
        direction = self._determine_direction(features, result)
        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()
        
        confidence = self._compute_confidence(features, direction, atr)
        confidence = compose_confidence(confidence)
        
        # Build signal
        signal = make_signal_from_frame(
            frame_trade(...),
            symbol=frames.get("symbol", ""),
            timeframe=features.get("timeframe", ""),
            timestamp=features.get("timestamp", ""),
            signal_type=self._get_signal_type(direction),
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context=self._get_regime_context(features),
            supporting_factors=self._get_supporting_factors(features, direction),
        )
        
        return signal
    
    # Setup-specific methods (must implement)
    def _compute_primary_factor(self, features: dict, direction: int) -> float:
        """Primary signal metric — setup-specific."""
        raise NotImplementedError("Subclasses must implement _compute_primary_factor")
    
    def _compute_structure_quality(self, features: dict, direction: int) -> float:
        """Structure quality score — optional but recommended."""
        return 0.5  # Default neutral
    
    def _check_gate1(self, features: dict) -> bool:
        """First validation gate — must be cheap (dict lookups only)."""
        raise NotImplementedError("Subclasses must implement _check_gate1")
    
    def _check_gate2(self, features: dict) -> bool:
        """Second validation gate — must be independent from gate1."""
        raise NotImplementedError("Subclasses must implement _check_gate2")
    
    def _determine_direction(self, features: dict, ohlcv) -> int:
        """Determine signal direction — setup-specific."""
        raise NotImplementedError("Subclasses must implement _determine_direction")
```

### Appendix C: Jim Simons Would Demand

**"What would Jim Simons demand?"**

1. **"Stop creating noise."** — We're creating 5.97M noise signals. This is the problem, not the solution.

2. **"Filter at the source, not downstream."** — CIS gates work correctly (selected signals have higher CIS scores). The problem is upstream: why fire 1.59M signals when only 2.8K are real?

3. **"Measure everything."** — We're not tracking confidence calibration. Add the metric.

4. **"Let the data speak."** — We're not validating shadow signals. Add promotion criteria: p<0.05, N≥100.

5. **"Ruthless simplicity."** — 21 setups have single-factor formulas. Replace with multi-factor ensembles.

6. **"No hidden assumptions."** — PatternCompletion fires on phantom data. Add parity auditor to catch this.

7. **"Fail fast."** — We're not detecting failures early. Add early gate optimization (cheap before expensive).

8. **"Clean data flow."** — Pipeline has no validation. Add parity checks between every stage.

9. **"Prove it works."** — Setups deployed without validation. Make shadow mode mandatory.

10. **"Fix the root cause."** — We considered deleting 21 setups. Fix the data pipeline instead.

11. **"Data integrity first."** — Microstructure features have no magnitude semantics. Define thresholds.

12. **"Signal-to-noise ratio matters."** — If you fire 100K signals, 50K should be real. Not 200.

**Renaissance Council Verdict**: REFACTOR all 21 setups (fix implementation, keep sound ideas), ENFORCE 6 GOOD patterns (architectural mandate), ADD pipeline validation (parity auditor), EARN promotion through proof (shadow mode, p<0.05). The system will preserve all trading concepts while enforcing Renaissance-grade execution.

---

**"The ideas are good. Fix the code. Let the data decide. Earn promotion through proof."** — Jim Simons
