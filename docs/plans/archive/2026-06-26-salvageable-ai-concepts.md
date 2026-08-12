# Salvageable AI & Intelligence Concepts from v2.x

**Date:** 2026-06-26  
**Status:** EXTRACTED from archived docs  
**Purpose:** Preserve valuable AI/intelligence concepts applicable to v3.0 AlphaEngine
**2026-07-02 verification pass:** each concept below tagged BUILT / OPEN / SUPERSEDED against
current code. 6 of 13 are already built, several as richer implementations than proposed here
(Concept 2's panel became `alpha_swarm.py`'s 5 agents; Concept 1 became `narrative_swarm.py`).
Remaining OPEN concepts are all downstream enhancements gated on v3.1's own OOS IC proof
(Phase 142B/144) before any are worth building — none should be started early. No new
consolidated doc; this is a light pass, not a rewrite (see conversation context 2026-07-02).

---

## Overview

While cleaning up docs/plans/, I discovered several **innovative AI concepts** from v2.x that are **still applicable to v3.0**. These represent Renaissance-grade thinking about AI-augmented trading systems.

These concepts were tied to the v2.x signal pipeline (now archived), but the **core ideas are architecture-independent** and should inform v3.0 development.

---

## Concept 1: AI Narrative Service (I8)

**Status: BUILT.** `services/narrative_swarm.py` (`NarrativeSwarm`, extends `BaseGroupCoordinator`).
Not from `alpha_events` as speculated below — narrates I7 signals directly.

**Source:** `docs/plans/archive/2026-02-19-i8-ai-narrative-design.md`

### Core Idea
Use local LLMs to generate **human-readable market narratives** from aggregated trading signals. This creates observability: for the first time, humans can understand *what the system is thinking* and *why a setup fired*.

### Architecture Pattern
```
signals:aggregated (Kafka)
    ↓
AINarrativeService (consumer group)
    ↓
Prompt builder (pure function, unit-testable)
    ↓
Ollama /api/chat (qwen3:8b, /no_think, 15s timeout)
    ↓
narratives:SYMBOL:TIMEFRAME (stream, maxlen=100)
    ↓
SSE → Dashboard narrative panel
```

### Key Design Decisions
1. **Local LLM first** (Ollama, zero cost, full privacy)
2. **Failure-tolerant**: Ollama unavailable → log warning, continue without publishing
3. **Cost control**: Stream only fires when `selected_signal is not None`
4. **Model choice**: `qwen3:8b` for quality, `phi4-mini:3.8b` for speed

### Applicability to v3.0
**AlphaEvents** need the same observability layer. Instead of just emitting `alpha_score`, generate a narrative explaining *why* the ensemble fired:

> "SPY 5m alpha_event triggered by strong momentum_z_fast (IC=0.043, regime=trending) + informed_flow (IC=0.038). Ensemble weight: 0.72. Expected return: 12 bips over 20 bars."

**Implementation:** Reuse the I8 pattern with `alpha_events:SYMBOL:TIMEFRAME` as input stream.

---

## Concept 2: Multi-Agent AI Expert Panel

**Status: BUILT, richer than proposed.** `services/alpha_swarm.py` runs 5 specialized agents
against `alpha_events`: correlation, counterfactual, ml_scorer, regime_coherence, skeptic
(`src/intelligence/ai/alpha/`). Same "influence not authority" principle as proposed below.

**Source:** `docs/plans/archive/2026-02-16-i7-signals-ai-experts-design.md`

### Core Idea
Instead of one monolithic AI, use **specialized expert agents** each analyzing a different dimension:

- **Confluence Synthesizer**: Meta-reasoning about which factors to trust
- **Smart Money Interpreter**: Sequencing SMC events into institutional narrative  
- **Regime Strategist**: Regime duration, transition forecasting
- **Cross-Market Analyst**: 14-instrument intermarket pattern detection
- **Risk Assessor**: Portfolio correlation, sizing, event risk

### Architecture Pattern
```
I7 deterministic signals → I8 AI Expert Panel (5 agents)
    ├── Confluence Synthesizer:    Meta-reasoning
    ├── Smart Money Interpreter:   Institutional narrative
    ├── Regime Strategist:         Regime forecasting
    ├── Cross-Market Analyst:      Intermarket patterns
    └── Risk Assessor:             Portfolio risk
    ↓
Signal confidence adjustment (±0.15) + rationale
```

### Key Design Principle
**AI has influence, not authority.** Deterministic signals (I7/AlphaEngine) are the backbone. AI agents can adjust confidence within bounded limits and add rationale, but cannot create or suppress signals.

### Applicability to v3.0
The same multi-agent pattern could enhance **AlphaEvents**:

1. **Regime Analyzer**: Explain why HMM switched states
2. **Feature Forensic**: Which features drove today's alpha_score spike?
3. **Decay Monitor**: Alert when IC decay exceeds threshold
4. **Cross-Sectional Analyst**: Explain why SPY outperformed peers today

**Implementation:** Each agent subscribes to `alpha_events`, runs analysis, publishes enhancement to `alpha_events:enriched`.

---

## Concept 3: Universal Ensemble (CIS)

**Status: OPEN.** `ensemble_trainer.py` has no per-bucket/domain weight stratification today
(verified: no domain/category grouping in the weighting code). Genuinely still an idea, not a
gap in an existing design — and now has a more specific home if pursued: Concept Registry
domains, or as a candidate stratification dimension (`docs/research/intel-12-stratification-dimension.md`)
rather than a bespoke bucket scheme. Gated on v3.1 OOS IC proof like everything else here.

**Source:** `docs/plans/archive/2026-03-04-cis-universal-ensemble-design.md`

### Core Idea
**Renaissance principle:** *Every measurable signal carries some predictive information. Put it in the model. Let outcomes decide the weights.*

Instead of manually wiring features to setups ("Williams%R confirms MeanReversion"), route **ALL signals into a universal ensemble**. Record every contribution. Let outcomes learn the weights via logistic regression.

### Architecture Pattern
```
ALL I1 outputs ──┐
ALL I2 outputs ──┤──► CIS (universal ensemble, 6 buckets) ──► direction + attribution
I3/I4/I5/SMC  ──┘
                │
         signal_ledger (cis_attribution JSONB)
                │
         cis_weights table ← logistic regression ← (contribution, outcome) pairs
```

### Key Innovation
**Attribution tracking.** Every signal records which constituents contributed and how much. Outcomes teach the model which signals actually predicted price.

### Applicability to v3.0
This is **exactly what v3.0 AlphaEngine does**, but the CIS design had one clever feature:

**Per-bucket ensemble weights:** Instead of one weight per feature, maintain 6 buckets (momentum, mean-reversion, breakout, volatility, volume, cross-timeframe) and learn weights separately per bucket.

**v3.0 enhancement:** Current `ic_sharpe` weighting could be stratified by **feature domain** (quant, structural, regime, macro, calendar) instead of one global weight.

---

## Concept 4: Confidence Pipeline Hardening

**Status: LESSON APPLIED.** No `CONF_FLOOR`-style clamp found in `alpha_publisher.py` — the
pitfall this concept warns against appears to have been avoided by construction, not by
explicit design decision citing this doc. Nothing to build; worth a note if anyone considers
adding a confidence floor later.

**Source:** `docs/plans/archive/2026-06-04-signal-confidence-pipeline-hardening.md`

### Core Insights
Detailed Renaissance audit of confidence calibration revealed:

1. **CONF_FLOOR bias:** Hard floor at 0.10 created a structural gap in training data — weak signals were artificially boosted, ML never saw true sub-0.10 convictions
2. **Two-layer ambiguity:** `calibrated_confidence` meant different things for winner vs non-winner signals
3. **Gate ordering:** Calibration after quality gate introduced selection bias

### Applicability to v3.0
**AlphaEvents confidence** should avoid these pitfalls:

1. **No floor clamp:** Let `alpha_score` go negative (bearish signals). Don't create artificial minimums.
2. **Single source of truth:** `ensemble_confidence` should mean the same thing everywhere
3. **Calibration before threshold:** Apply IC-based confidence calibration before `alpha_threshold` crossing

---

## Concept 5: Regime-Adaptive Signal Selection

**Status: OPEN.** Feature-selection-by-regime is not built. Now a natural extension once
`docs/research/intel-12-stratification-dimension.md` ships — a dimension's Measurement Engine
results already tell you which features carry IC in which regime; gating ensemble membership
on that is a consumer decision on top of existing facts, not new measurement infrastructure.

**Source:** `docs/plans/archive/2026-02-16-i7-signals-ai-experts-design.md`

### Core Idea
Signal type and frequency adapt to current market regime:

- **Trending regime** → Trend-following setups (momentum ignition, breakout)
- **Ranging regime** → Mean-reversion setups (support/resistance, VWAP reclaim)
- **Transitioning regime** → Breakout setups (volatility contraction, squeeze expansion)

### Applicability to v3.0
**AlphaEngine already does regime conditioning** (IC stratified by HMM regime), but we could add **regime-aware feature selection**:

Instead of using all 54 features in every regime:
```python
if regime == "trending":
    active_features = [momentum_z_fast, momentum_z_slow, informed_flow, ...]
elif regime == "ranging":
    active_features = [range_position, bar_close_pos, mean_reversion_z, ...]
```

This would improve ensemble **signal-to-noise** by excluding features known to have negative IC in the current regime.

---

## Concept 6: Three-Layer AI Architecture

**Status: PARTIALLY BUILT.** Layer 1 (deterministic ensemble) and Layer 2 (AI enhancement via
`alpha_swarm.py`'s 5 agents) exist. Layer 3 (AI novel discovery) remains deferred, correctly —
discovery is exactly the kind of unproven-until-shown capability this project's principles
gate hardest.

**Source:** `docs/plans/archive/2026-02-16-i7-signals-ai-experts-design.md`

### Core Idea
AI augmentation happens in three layers:

1. **Deterministic backbone:** I7 rules / AlphaEngine IC-weighted ensemble
2. **AI signal enhancement:** AI adjusts confidence, adds rationale, cannot create/suppress
3. **AI novel discovery:** AI discovers new patterns not encoded in rules (deferred)

### Applicability to v3.0
v3.0 should follow this pattern:

1. **Layer 1 ( deterministic):** AlphaEngine IC-weighted ensemble → alpha_score
2. **Layer 2 (enhancement):** AI explains why alpha_score fired, suggests regime context
3. **Layer 3 (discovery):** AI searches for new feature combinations with high IC

---

## Concept 7: Cost-Optimized Model Routing

**Status: OPEN.** `alpha_swarm.py`'s 5 agents do not differentiate model by task type today
(no per-agent `model=` override found). Still a real idea, still gated behind the agents it
would route between actually earning their keep first.

**Source:** `docs/plans/archive/2026-02-16-i7-signals-ai-experts-design.md`

### Core Idea
Different AI tasks need different model capabilities. Map each agent to a model tier based on cognitive requirements:

- **Reasoning-heavy** (Confluence Synthesizer): `gpt-4o` / `claude-3-opus`
- **Math-heavy** (Risk Assessor): `gemini-pro` 
- **Speed-sensitive** (Smart Money Interpreter): `gpt-3.5-turbo` / `nemotron-3-nano`
- **Local-first** (Regime Strategist): `qwen3:8b` via Ollama

### Applicability to v3.0
The same cost optimization applies to v3.0 AI agents:

- **Feature forensic:** Fast model (nemotron-3-nano:4b)
- **Regime analysis:** Medium model (qwen3:8b)  
- **Novel discovery:** Slow model (claude-3-opus, nightly batch)

---

## Implementation Priority for v3.0

### High-Value, Low-Effort (Implement First)

1. **✅ Concept 1: AI Narrative Service** 
   - **Effort:** 2-3 days (reuses I8 pattern with alpha_events input)
   - **Value:** High observability, human-understandable system
   - **Migration:** Phase 148 (after IC drift monitoring)

2. **✅ Concept 4: Confidence Pipeline Lessons**
   - **Effort:** 1 day (avoid known pitfalls in alpha_events design)
   - **Value:** Prevents structural bias in confidence calibration
   - **Migration:** Phase C (AlphaEvents implementation)

### Medium-Value, Medium-Effort (Consider for Phase D)

3. **🔄 Concept 2: Multi-Agent Panel**
   - **Effort:** 1-2 weeks (implement 4-5 specialized agents)
   - **Value:** Richer alpha_events context, better observability
   - **Migration:** Phase D (Portfolio Construction, shadow mode)

4. **🔄 Concept 7: Cost-Optimized Routing**
   - **Effort:** 3-5 days (implement model routing layer)
   - **Value:** 50-70% cost reduction on AI inference
   - **Migration:** Phase D (when scaling AI agents)

### Lower-Priority (Future Work)

5. **⏳ Concept 3: Per-Bucket Ensemble Weights**
   - **Effort:** 1 week (modify ic_sharpe computation)
   - **Value:** Marginal IC improvement (5-10%)
   - **Migration:** Phase B (Ensemble optimization)

6. **⏳ Concept 5: Regime-Aware Feature Selection**
   - **Effort:** 3-5 days (add feature filtering by regime)
   - **Value:** Improved signal-to-noise in ensemble
   - **Migration:** Phase B (after IC baseline validated)

7. **⏳ Concept 6: Three-Layer AI**
   - **Effort:** 2-3 weeks (full three-layer architecture)
   - **Value:** Long-term AI augmentation roadmap
   - **Migration:** Phase E (Live, after Layer 2 validated)

---

## What Jim Simons Would Say

> "The narrative service is brilliant. You're building a system that thinks, but you can't explain its thoughts. That's a black box, not a trading system. Fix it."
> 
> "The universal ensemble principle is correct: every measurable signal carries information. Let outcomes decide weights, not human opinion."
> 
> "AI should influence, not authority. Deterministic backbone first, AI enhancement second. Never let AI create trades from scratch."

**Renaissance standard:** **AI augments human intelligence, it doesn't replace it.** The system must remain interpretable and auditable.

---

## Concept 8: Signal-to-Noise Optimization at Source

**Status: BUILT.** `alpha_publisher.py` gates emission on both a per-TF threshold
(`alpha.quant.threshold.{tf}`) and a cost hurdle (`alpha.quant.cost_hurdle.{tf}`) — the
noise-floor-at-emission idea proposed below, APR-backed.

**Source:** `docs/plans/2026-06-07-signal-quality-crisis-root-cause-analysis.md` (DELETED)

### Core Insight
**Renaissance principle:** *Stop creating noise signals in the first place.*

The crisis: v2.x generated 7.85M signals across 30 I7 setups. 21 setups (70%) generated 57% of all signals but only 0.19% were selected. This means **99.8% of signals were noise created at the source**, not filtered downstream.

### Current State (BROKEN)
- trad_OFIContinuation: 1.59M signals → 2.8K selected (0.18% SNR) → **99.82% NOISE**
- trad_PatternCompletion: 795K signals → 1.2K selected (0.15% SNR) → **99.85% NOISE**
- trad_CVDDivergence: 250K signals → 113 selected (0.05% SNR) → **99.95% NOISE**

### Target State (RENAISSANCE)
- trad_TrendFollowing: 654K signals → 654K selected (100% SNR) → **0% NOISE**
- trad_LiquiditySweepReclaim: 333K signals → 229K selected (69% SNR) → **31% NOISE**
- trad_CHoCHReversal: 232K signals → 139K selected (60% SNR) → **40% NOISE**

### Applicability to v3.0
**AlphaEngine applies this principle automatically.** By measuring IC on the **unconditional training set** (every bar, not just signal-fired bars), v3.0 avoids the selection bias that created the noise crisis.

However, the principle extends to **alpha_event emission thresholds**:

```python
# Instead of: Emit event on any alpha_score > threshold
# Use: Emit event only when ensemble confidence exceeds noise floor

if alpha_score > threshold and ensemble_confidence > noise_floor_regime[regime]:
    emit_alpha_event()
```

Where `noise_floor_regime` is learned from IC: if features in a regime have `ic_sharpe < 0.2`, that regime has high noise and should require higher ensemble confidence to emit.

---

## Concept 9: DAG Integrity & Deterministic IDs

**Status: BUILT.** `alpha_events` uses content-addressed keys with `ON CONFLICT DO NOTHING` —
verified in `alpha_publisher.py`.

**Source:** `docs/plans/2026-06-11-signal-replay-architecture-plan.md` (DELETED)

### Core Insights

**Problem 1: DAG Violation**
`run_historical_pipeline.py --replay-only` entered at `market_data_ohlcv` even when `intelligence_features` was valid. Re-ran all I1→I6 compute (ON CONFLICT DO NOTHING discarded result), then ran I7. **100% wasted work. Hours instead of minutes.**

**Problem 2: Random Signal IDs**
Signal IDs were random UUIDs. Signals are deterministic outputs of `(ts, symbol, tf, setup_plugin, direction)`. Random IDs make `ON CONFLICT DO UPDATE` impossible, forcing `DELETE + re-insert` on every replay. **Loses audit trail, breaks external references, defeats idempotency.**

**Problem 3: Compression Hostile to DML**
`signal_ledger` had 51 compressed chunks (2.1GB uncompressed). `DELETE` forced per-tuple decompression on write. **Neither table was in the right state for bulk DML.**

### Architecture Pattern
```
Correct DAG replay:
market_data_ohlcv → [I1→I6] → intelligence_features → [I7] → signal_ledger
                                              ↑
                                         Replay enters here
                                         (skip I1→I6 if features valid)
```

### Applicability to v3.0
v3.0 **fixed these problems by design**:

1. **Content-addressed IDs:** `alpha_events` uses SHA-256(`symbol|tf|bar_ts_ns|ensemble_version`) — deterministic, reproducible, enables `ON CONFLICT`

2. **DAG-aware replay:** `corpus_pipeline_run.sh` has `--from-step N` to enter at the correct layer:
   ```
   Step 1: market_data_ohlcv → feature_vectors
   Step 2: feature_vectors → forward_returns  
   Step 3: forward_returns → feature_ic_scores
   Step 4: feature_ic_scores → alpha_events
   ```

3. **Compression-friendly:** v3.0 hypertables use compression but avoid bulk DML. Writers use batch INSERT with `ON CONFLICT DO NOTHING`.

**Lesson learned:** When designing replay, **enter the DAG at the first invalid layer, not the source.**

---

## Concept 10: Three-Tier Validation Strategy

**Status: BUILT.** The corpus/IC-gate/walk-forward pipeline this project already runs is the
tier-1/2/3 pattern proposed below, just built before deployment rather than validated after.

**Source:** `docs/plans/2026-06-07-signal-quality-crisis-root-cause-analysis.md` (DELETED)

### Core Pattern
The Renaissance Council identified a three-tier strategy for fixing signal quality:

**Tier 1: Fix BAD INPUTS**
- Upstream features (I1/I5) produce unvalidated data that I7 setups consume
- Solution: ParityAuditor catches data flow bugs before they create noise

**Tier 2: Enforce GOOD PATTERNS**  
- Multi-factor confidence, I6 confluence, strict gates, continuous regime weighting
- Solution: Architectural patterns that prevent noise creation

**Tier 3: Validate through Proof**
- Shadow mode validates setups don't create noise (p<0.05, N≥100)
- Solution: Statistical validation before production promotion

### Applicability to v3.0
The same three-tier strategy applies to **AlphaEngine validation**:

1. **Tier 1 (Fix Bad Inputs):** FeatureFactory degenerate detection (`std < 1e-8`), forward return completeness gates
2. **Tier 2 (Enforce Patterns):** IC Sharpe weighting, effective N correction, FDR multiple testing
3. **Tier 3 (Proof):** Walk-forward validation, IC decay monitoring, regime-stratified performance

**v3.0 advantage:** Validation happens **before deployment** (IC measurement on historical corpus), not after (shadow mode for signal quality).

---

## Updated Implementation Priority

### High-Value, Low-Effort (Implement First)

1. **✅ Concept 1: AI Narrative Service** 
   - **Effort:** 2-3 days (reuses I8 pattern with alpha_events input)
   - **Value:** High observability, human-understandable system

2. **✅ Concept 8: Signal-to-Noise at Source**
   - **Effort:** 1 day (add noise-floor gates to alpha_events emission)
   - **Value:** Prevents noise events, applies Renaissance principle

3. **✅ Concept 4: Confidence Pipeline Lessons**
   - **Effort:** 1 day (avoid known pitfalls in alpha_events design)
   - **Value:** Prevents structural bias in confidence calibration

### Medium-Value, Medium-Effort (Consider for Phase D)

4. **🔄 Concept 2: Multi-Agent Panel**
   - **Effort:** 1-2 weeks (implement 4-5 specialized agents)
   - **Value:** Richer alpha_events context, better observability

5. **🔄 Concept 9: DAG Integrity**
   - **Effort:** Already implemented in v3.0 ✅
   - **Value:** Replay enters at correct layer, deterministic IDs

6. **🔄 Concept 7: Cost-Optimized Routing**
   - **Effort:** 3-5 days (implement model routing layer)
   - **Value:** 50-70% cost reduction on AI inference

### Lower-Priority (Future Work)

7. **⏳ Concept 3: Per-Bucket Ensemble Weights**
   - **Effort:** 1 week (modify ic_sharpe computation)
   - **Value:** Marginal IC improvement (5-10%)

8. **⏳ Concept 5: Regime-Aware Feature Selection**
   - **Effort:** 3-5 days (add feature filtering by regime)
   - **Value:** Improved signal-to-noise in ensemble

9. **⏳ Concept 6: Three-Layer AI**
   - **Effort:** 2-3 weeks (full three-layer architecture)
   - **Value:** Long-term AI augmentation roadmap

10. **⏳ Concept 10: Three-Tier Validation**
    - **Effort:** Already implemented in v3.0 ✅
    - **Value:** Statistical rigor, prevents deployment of broken features

---

## Concept 11: Multi-Method Synthesis Pattern

**Status: SUPERSEDED.** The v2.x I4/SMC zone-engine machinery this concept was extracted from
is archived; its own "Applicability to v3.0" section below already correctly identifies the
`alpha_events` ensemble as the v3.0-native equivalent. Nothing left to build under this name.

**Source:** `docs/plans/archive/2026-06-05-sr-consensus.md` (ARCHIVED)

### Core Idea
**Three independent failures cause bad stops/targets.** The solution: synthesize multiple independent methods rather than relying on a single source.

**The Three Failure Modes:**
1. **Bad inputs from single method:** `struct_SupportResistance` with fixed `cluster_pct = 0.005` (timeframe-blind: 120 bars of 5m = 10h, 120 bars of 1h = 5 days)
2. **Incomplete input set:** Missing 8 sources (fib retracements, prior session H/L, Asian session H/L, VP HVN, AVWAP bands, Keltner midline)
3. **Non-persistent intermediate results:** Zone engine synthesis produces `zone_low/zone_high` but never writes `sr_nearest_support/resistance` to features

**Solution:** Multi-method consensus layer that combines all sources and persists results.

### Architecture Pattern
```
struct_SupportResistance (single method, bad inputs)
    ↓
zone_engine (8+ sources, incomplete)
    ↓
ctx_SRConsensus I4 plugin (multi-method synthesis)
    ↓
sr_nearest_support/resistance (persisted to intelligence_features)
    ↓
I7 plugins use consensus values (robust stops/targets)
```

### Applicability to v3.0
**AlphaEvents ensemble is the v3.0 equivalent** of this pattern:

1. **Multiple features** → IC engine measures each independently
2. **Ensemble synthesis** → `alpha_score = Σ(normalized_score[f] × ic_sharpe[f]) / effective_N`
3. **Persisted result** → `alpha_events` table stores both ensemble score AND per-feature attribution

**Key insight:** Don't rely on single methods. Synthesize multiple independent views and persist the intermediate results for observability.

---

## Concept 12: Immutable Source + Mutable State Separation

**Status: BUILT.** `feature_vectors` -> `forward_returns` -> `alpha_events` is exactly this
chain, append-only throughout (verified: `alpha_events` insert is `ON CONFLICT DO NOTHING`,
never `UPDATE`).

**Source:** `docs/plans/archive/2026-06-03-lifecycle-replay-reviews.md` (ARCHIVED)

### Core Principle
**Immutable source + mutable state separation** prevents replay corruption and enables idempotent re-computation.

**The Pattern:**
```
signal_ledger (immutable signal definition)
    ↓
signal_outcomes (mutable lifecycle state)
```

- **signal_ledger**: Immutable — once written, never updated. Contains the signal as it was generated.
- **signal_outcomes**: Mutable — lifecycle evaluation, exit status, PnL tracking. Updated as trade evolves.

### Architecture Benefits
1. **Replay safety:** Can wipe `signal_outcomes` and replay without touching original signal definitions
2. **Audit trail:** Original signal preserved alongside updated outcomes
3. **Idempotency:** Replay can be run multiple times without corrupting source data

### Applicability to v3.0
v3.0 **already follows this pattern**:

```
feature_vectors (immutable feature computation)
    ↓
forward_returns (immutable forward return labels)  
    ↓
feature_ic_scores (immutable IC measurements)
    ↓
alpha_events (mutable emission events)
```

**Key distinction:** Feature computation, IC measurement, and alpha emission are **immutable historical records**. Only downstream portfolio construction (Phase D) should have mutable state.

**Lesson:** When designing replay pipelines, **separate immutable computation from mutable state**.

---

## Concept 13: Timeframe-Aware Parameters

**Status: BUILT.** Gradient APR naming (`return_fast`/`mid`/`slow`/`extended`,
`alpha.ic.lookahead.*`) is exactly this pattern, formalized in
`docs/foundation/naming-system.md` §7.

**Source:** `docs/plans/archive/2026-06-18-timeframe-propagation-fix.md` (ARCHIVED)

### Core Issue
Fixed parameters work across all timeframes → wrong behavior at scale.

**Example:** `cluster_pct = 0.005` (0.5% price tolerance)
- At 5m TF: 37pts tolerance on ES @ 7400 (reasonable)
- At 1h TF: 37pts tolerance (same as 5m) — but 120 bars of 1h = 5 days vs 10 hours for 5m
- Result: Timeframe-blind clustering produces phantom levels

### Solution Pattern
**Timeframe-aware parameters:**
```python
# Instead of:
cluster_pct = 0.005  # Fixed across all TFs

# Use:
cluster_pct = TIMEFRAME_AWARE_CLUSTER_PCT.get(tf, 0.005)
# Where:
TIMEFRAME_AWARE_CLUSTER_PCT = {
    "5m": 0.005,   # 37pts on ES @ 7400
    "15m": 0.003,  # Tighter for longer TF
    "1h": 0.002,   # Even tighter for daily scale
    "1d": 0.001,   # Tightest for weekly patterns
}
```

### Applicability to v3.0
v3.0 AlphaEngine **already uses timeframe-aware parameters** via APR:

```python
# APR keys per timeframe:
alpha.ic.lookahead.fast = 1   # 5m/15m/1h
alpha.ic.lookahead.slow = 20  # 5m/15m/1h
alpha.ic.lookahead.extended = 60  # 1h/1d only

# Different scales for different TFs
```

**Lesson:** **Parameter values should adapt to timeframe scale**, not be universal constants.

---

## What Jim Simons Would Say About This Salvage

> "Excellent. You found the signal-to-noise analysis — that's pure Renaissance thinking. 'Stop creating noise at the source' is exactly right."
> 
> "The DAG integrity lessons are critical: deterministic IDs, correct replay entry points, compression-aware data structures. These are not optimizations, they're correctness requirements."
> 
> "The three-tier validation pattern is what separates production systems from research prototypes. Tier 1: fix inputs. Tier 2: enforce patterns. Tier 3: prove with data. This is how you ship."

**Renaissance standard:** **Salvage the principles, not the implementation.** The v2.x signal pipeline is gone, but the thinking lives on in v3.0.
