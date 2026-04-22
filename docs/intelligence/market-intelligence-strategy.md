# Market Intelligence Strategy & Agent Framework

**Version:** 3.0.0
**Last Updated:** 2026-04-21
**Status:** Operational — I1-I8 pipeline complete. For implementation details see `docs/intelligence/ai-intelligence-architecture.md`. For active services see `docs/architecture/current-state.md`.

---

## Intelligence Platform Vision

IndicAgent is an **AI-powered market intelligence platform** built from specialized intelligence agents that provide institutional-grade market insights. Each agent tier brings unique analytical expertise; together they form a dependency-aware DAG that transforms raw bars into evidence-graded trading signals.

**Core Mission:** Extract actionable market intelligence through multi-tier analysis, pattern recognition, and sophisticated market structure understanding — with every output auditable, replayable, and statistically validated before it affects production decisions.

---

## Intelligence Processing Hierarchy (I1-I8)

```
I1  Foundation indicators        — RSI, MACD, ATR, VWAP, OFI, CVD (27 plugins)
I2  Composite events             — Crossovers, exhaustion, acceleration (10 plugins)
I3  Market structure             — Swing, S/R, session levels, market profile (8 plugins)
I4  Regime classification        — GARCH, Kalman, HMM, BOCPD, VIX, cross-asset (12 plugins)
I5  Pattern detection            — Divergence, squeeze, chart patterns (16 plugins)
SMC Smart Money Concepts         — BOS/CHoCH, FVG, order blocks, liquidity (13 plugins)
I6  Cross-timeframe confluence   — CTF sub-scores → CIS scoring (1 plugin)
I7  Trading signal generation    — Setup plugins + CISScorer + SignalAggregator (36 plugins)
I8  AI narrative                 — LLM analysis per signal (OpenRouter → Ollama)
```

Each tier is DB-ignorant — it reads from the tier above it and publishes to Kafka. Only WriterAgents touch the database.

---

## Core Intelligence Agent Roles

### Pattern Analysis (I5)

**Responsibility:** Discrete pattern recognition on the mathematical foundation from I1-I4.

**What it detects:**
- **Divergence patterns** — RSI/MACD/volume divergence from price; leading reversal signals
- **Volatility squeeze** — Bollinger Bands inside Keltner Channels; compression preceding expansion
- **Chart patterns** — H&S, double top/bottom, triangles, flags, cup & handle, measured move
- **Trend confluence** — multi-indicator agreement for continuation confirmation

**Why it matters:** Pattern plugins convert continuous indicator streams into discrete events. A raw RSI value is noise; an RSI divergence confirmed by volume is signal. I5 outputs feed directly into I6 confluence scoring.

---

### Smart Money Concepts (SMC)

**Responsibility:** Institutional order flow analysis — interpreting price action as the footprint of large participants.

**What it detects:**
- **BOS/CHoCH** — Break of Structure (trend continuation) vs. Change of Character (structural reversal — earliest reversal signal in the pipeline)
- **FVG** — Fair Value Gap; a 3-candle price imbalance where liquidity was left unfilled; price has a measurable tendency to return and fill
- **Order blocks** — Institutional accumulation/distribution zones
- **Liquidity pools** — Clusters of stops that large participants target before reversing
- **BOCPD** — Bayesian Online Changepoint Detection; detects the moment statistical properties of the price series shift, before a new regime is confirmed
- **HMM** — Hidden Markov Model; classifies into known market states with full probability distributions

**Why it matters:** SMC plugins provide the institutional context that separates a technically valid setup from one with actual order flow behind it. The `ctf_ob_alignment` and `ctf_fvg_alignment` sub-scores produced here are required inputs for every I7 plugin.

---

### Market Context & Regime Classification (I4)

**Responsibility:** Statistical characterization of market state — answering "what kind of market is this right now?"

**What it classifies:**

| Model | Question | Output |
|-------|----------|--------|
| **GARCH** | Is volatility expanding or contracting? | Volatility regime + sigma estimate |
| **Kalman filter** | What is the true underlying trend, separate from noise? | Smooth trend slope, adapts to current SNR |
| **HMM** | Which hidden market state is most probable? | Probability distribution over 3 states |
| **BOCPD** | Is a new regime beginning right now? | Changepoint probability per bar |
| **Hurst Exponent** | Is this market persistent or mean-reverting? | H-value + persistence class |
| **Shannon Entropy** | How predictable is the current price series? | Entropy score → CIS quality multiplier |

**Why it matters:** Regime context gates I7 signal direction. A trend plugin firing in a mean-reverting regime (HMM state 0) is suppressed. A mean-reversion plugin firing in a strongly trending regime is suppressed. Regime classification is what prevents the pipeline from fighting the market.

---

### Cross-Timeframe Confluence (I6)

**Responsibility:** Synthesize I1-I5/SMC outputs across all active timeframes into a single set of directional sub-scores consumed by every I7 plugin.

**What it produces:**
- `ctf_trend_alignment` — trend agreement across timeframes
- `ctf_regime_agreement` — regime consensus across timeframes
- `ctf_fvg_alignment` — FVG directional bias across timeframes
- `ctf_ob_alignment` — order block directional bias across timeframes

**Why it matters:** Single-timeframe signals are noisy. A BOS/CHoCH on the 1m that contradicts the 15m and 1h structure is a false signal. I6 enforces cross-timeframe confirmation before any I7 plugin can score highly. Every I7 plugin is required to consume the relevant `ctf_*` sub-scores — this is a hard architectural rule, not a guideline.

---

### Trading Signal Generation (I7)

**Responsibility:** Translate confluence evidence into actionable trade setups with entry, stop-loss, and take-profit logic.

**How it works:**

1. Each of 36 setup plugins evaluates its thesis against I1-I6 outputs
2. `CISScorer` aggregates all plugin outputs into a Confluence Intelligence Score using 6 weighted evidence buckets
3. `SignalAggregator` ranks all candidates; applies isotonic calibration → TOD multiplier → perf_multiplier
4. Winner and all ranked counterfactuals written to `signal_ledger` as labeled training data

**CIS gate:** `|score| > 0.35` AND at least 3 of 6 evidence buckets agree on direction. A single dominant bucket cannot override.

**Why this matters:** Most systems fire on a single indicator. CIS requires cross-tier agreement — trend, momentum, structure, pattern, institutional, and regime evidence must align. This is what produces institutional-grade signal quality rather than noise amplification.

---

## DAG Execution Model

The intelligence pipeline is a **dependency-aware DAG** — not a hardcoded sequence. Plugins declare what they need as inputs and what they produce as outputs. The DAG engine derives execution order automatically via topological sort at startup.

```
Raw OHLCV
  └─► I1 (27 plugins — no dependencies, run in parallel)
        └─► I2 (depends on I1 outputs)
  └─► I3 (reads OHLCV directly)
        └─► I4 (reads I3 + I1 outputs)
  └─► I5 (reads I1 features)
  └─► SMC (reads I1-I4 + OHLCV)
        └─► I6 CTF (reads I1-I5 + SMC, cross-timeframe)
              └─► I7 Setups (reads I2-I6, regime-gated)
                    └─► I8 AI Narrative (reads I7 signals)
```

**Why this matters:**

- **Adding a plugin** means declaring its inputs. Execution order is inferred — no ordering file to maintain.
- **Circular dependencies are impossible to ship.** The DAG engine detects them at startup and hard-crashes before any live data flows.
- **Parallelization is safe.** I1 and I7 execute concurrently via `asyncio.gather` because the DAG proves they have no inter-dependencies within the tier. I2-I6 remain sequential because each tier reads the previous tier's outputs.
- **No plugin knows about other plugins directly.** Cross-plugin communication flows exclusively through tier output schemas. A plugin that needs RSI reads it from the feature context — it never calls the RSI plugin.

**Sub-wave dependency resolution:** Within tiers, some plugins depend on others in the same tier. The wave system handles this: `I2_WAVE_A` runs first (independent plugins), `I2_WAVE_B` runs after (plugins that consume Wave A outputs). Same pattern in I4 (GARCH → Kalman) and SMC (order blocks → supply/demand zones).

---

## Separation of Concerns — Compute vs. Persistence

Every agent in the pipeline has exactly one responsibility. The hardest boundary to enforce — and the most important — is between compute and persistence.

```
┌─────────────────────────────────────────────────────────┐
│  HOT PATH (in-memory, zero I/O)                         │
│  IntelligencePipelineComputeAgent: I1→I7 <10ms          │
│  • 123 plugins execute in-process                       │
│  • Zero database touches                                │
│  • Zero blocking I/O                                    │
└──────────────────────────┬──────────────────────────────┘
                           ↓ Kafka (async, non-blocking)
┌─────────────────────────────────────────────────────────┐
│  PERSISTENCE PATH (async, isolated)                     │
│  FeatureWriterAgent  → intelligence_features (DB)       │
│  SignalWriterAgent   → signal_ledger (DB)               │
│  BarWriterAgent      → market_data_ohlcv (DB)           │
└─────────────────────────────────────────────────────────┘
```

**The rule:** ComputeAgents are DB-ignorant. WriterAgents are the only agents with DB write access and never appear on the compute hot path.

**Why this matters:**

- **Database outage = zero impact on signal generation.** The hot path continues; messages queue in Kafka. When the writer recovers, it resumes from its committed offset — nothing lost, nothing reprocessed.
- **DB latency never becomes signal latency.** A slow batch write to TimescaleDB has no effect on the next bar's I1-I7 computation.
- **Operational flexibility.** DB schema changes, batch size tuning, retry policy adjustments — all in WriterAgents, never touching compute code.
- **Restart safety.** Each WriterAgent maintains a committed Kafka offset. Restart mid-batch = resume from last commit, no duplicate writes, no dropped records.

**Agent role boundaries (non-negotiable):**

| Role | DB Access | Kafka | Compute |
|------|-----------|-------|---------|
| `ProviderAgent` | ❌ | Produce only | ❌ |
| `ComputeAgent` | ❌ | Produce + Consume | ✅ |
| `WriterAgent` | ✅ Write | Consume only | ❌ |
| `AuditorAgent` | ✅ Read | Produce + Consume | ✅ |
| `TrackerAgent` | ✅ R/W | Produce + Consume | ✅ |

An agent that violates its boundary — a compute agent writing to DB, a writer agent doing computation — is an architectural defect, not a shortcut.

---

## Independent Tier Computation with Confluence-Gated Selection

Each tier operates independently — no tier knows what another concluded until I6 synthesizes the outputs. This independence is the source of signal quality: when tiers agree, the agreement is genuine, not an artifact of shared state or coordinated logic.

```
I1-I5 + SMC   →  independent analysis, no shared state
                         ↓
I6 CTF        →  synthesizes directional sub-scores across all tiers and timeframes
                         ↓
CISScorer     →  aggregates into a single Confluence Intelligence Score
                         ↓
I7 gate       →  regime gate + CIS threshold; setups that don't meet the bar are dropped
                         ↓
SignalAggregator  →  ranks survivors; winner + all counterfactuals written to signal_ledger
```

**Why independence matters:** A trend signal from I1, a structural confirmation from I3, an order block from SMC, and a regime classification from I4 are computed with no knowledge of each other. When all four point the same direction, that agreement is signal. When they disagree, the CIS gate catches it — no single dominant tier can override the ensemble.

**Why counterfactuals matter:** Every rejected candidate is written to `signal_ledger` alongside the winner. This gives a complete view of the decision boundary — not just what fired, but what almost fired and why it lost. This dataset is what the self-correction stack learns from.

---

## Intelligence Quality Framework

### Signal Validation Gates

| Gate | Condition | Failure Mode |
|------|-----------|-------------|
| **CIS threshold** | `\|score\| > 0.35` | Signal dropped |
| **Bucket agreement** | ≥ 3 of 6 buckets agree | Signal dropped |
| **Regime gate** | HMM confidence ≥ 0.55, stable ≥ 3 bars | Signal suppressed |
| **RR gate** | Viable risk:reward based on zone quality | Signal dropped |
| **Shadow gate** | `p < 0.05` AND `N ≥ 100` resolved | Feature blocked from production |

### Self-Correction Mechanisms

The pipeline monitors its own signal quality and self-adjusts at six layers. See `docs/architecture/plugin-native-architecture-explained.md` Section 8 for the full breakdown:

1. **Isotonic calibration** — bias correction on raw I7 confidence using historical outcomes
2. **TOD multiplier** — 120-cell time-of-day adjustment per `(regime_type, tf, hour_et)`
3. **perf_multiplier** — `setup_performance` table drives rank ordering; N<30 gate prevents premature adjustment
4. **KS drift** — distribution shift → CIS bucket weight penalty (early warning layer)
5. **CUSUM** — win-rate degradation → `perf_multiplier` feedback loop (outcome layer)
6. **Shadow gate** — `p < 0.05` + `N ≥ 100` required before production eligibility

### Intelligence Quality Metrics

| Metric | Measured By | Where |
|--------|------------|-------|
| Signal accuracy | 8-class outcome taxonomy | `signal_ledger.outcome` |
| Confidence calibration | Isotonic regression fit | `pre_calibration_confidence` vs actual outcome |
| Regime gate effectiveness | Suppression rate by regime | `regime_gate_suppressions_total` (Prometheus) |
| CIS bucket contribution | Per-bucket attribution per signal | `signal_ledger` JSONB |
| Setup performance | Rolling 30d win rate, avg PnL_R, Sharpe | `setup_performance` table |
| Shadow vs production | Win rate delta before/after promotion | `signal_ledger` shadow rows |

---

## See Also

- `docs/intelligence/ai-intelligence-architecture.md` — Full I1-I8 pipeline architecture and service map
- `docs/architecture/plugin-native-architecture-explained.md` — Plugin-native design principles and self-correction stack
- `docs/architecture/agent-standard.md` — Agent role taxonomy and naming conventions
- `docs/architecture/current-state.md` — Active services, data flow, performance
- `src/intelligence/CLAUDE.md` — Plugin protocol, tier lists, I7 utilities
