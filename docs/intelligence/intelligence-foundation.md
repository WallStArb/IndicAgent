# Intelligence Foundation — Principles & Architecture

**Version:** 1.0.0
**Last Updated:** 2026-05-28
**Status:** stale (v2.x, see banner)
**Milestone:** v2.8 — AI Platform + Evolvable Agents

---

> **Staleness note (2026-08-01):** This doc describes the ARCHIVED v2.x I1-I8 tiered pipeline
> (IntelligencePipeline, AlphaSwarm, NarrativeSwarm, `signal_ledger` outcomes feeding ML
> training) as the live hot-path architecture. That system has no live consumer as of
> 2026-07-02 per CLAUDE.md. See CLAUDE.md's Architecture section for the current v3.0
> pipeline. Not yet rewritten for v3.0 -- tracked for a future doc pass, not fixed here.

## Purpose

The WHY and WHAT of IndicAgent's intelligence pipeline: Renaissance principles applied to market intelligence, tier definitions (indicators through AI narrative, I1-I8), data flow philosophy, and core data contracts.

**Tier glossary:** I1 = indicators, I2 = composite_events, I3 = structure, I4 = context, I5 = patterns, SMC = smart_money, I6 = confluence, I7 = signals, I8 = AI_narrative. See `docs/foundation/naming-system.md` for full reference.

Start here to understand the system before implementing.

---

## Renaissance Principles

> "The edge is in measurement, not prediction." — Renaissance principle applied

### Principle 1: Determinism in the Hot Path, AI Out-of-Band

**Why:** LLMs are probabilistic. The same question twice can yield different answers. This is unacceptable for signal generation where reproducibility is required.

**What this means:**

```
HOT PATH (deterministic, I1-I7):
  Bar → Indicators (I1) → Composite events (I2) → Structure (I3) → Context (I4)
      → Patterns (I5) → Smart money (SMC) → Confluence (I6) → Signals (I7) → Signal
  All plugins are pure Python functions. Same input = same output.
  Latency: ~220ms per bar (single symbol, all timeframes).

OUT-OF-BAND (AI/LLM, I8):
  Signal (I7) → AlphaSwarm (LLM agents evaluate quality)
  Signal (I7) → NarrativeSwarm (generates explanation)
  signal_ledger outcomes → ML training (offline)
  LLMs consume pipeline outputs, never sit on the critical path.
```

The real-time pipeline is deterministic. AI is an adjacent layer that explains, evaluates, and learns.

### Principle 2: DB-Ignorant Compute, Writer-Owned Persistence

> "Your edge disappears if your pipeline blocks on database writes."

**Why:** Database calls are I/O-bound and unpredictable. A slow query, connection timeout, or lock contention introduces latency variance that destroys edge.

**What this means:**

- **Compute agents (I1-I7)** publish to Kafka, never write to DB directly
- **Writer agents** consume Kafka and batch-write to TimescaleDB
- **State is checkpointed locally** (per symbol/timeframe/plugin) — no warmup on restart
- **Replay is trivial** — replay bars from DB, same plugins produce same outputs

### Principle 3: Regime-Aware Signal Generation

> "The same signal means completely different things in a trending market vs ranging vs volatility-expansion."

**Why:** Markets are non-stationary. A momentum setup in a quiet regime is not the same trade as momentum in a volatile regime.

**What this means:**

I4 (Regime Classification) precedes I7 (Signal Generation). Every I7 plugin receives `regime_state` and must respect it. Regime incompatibility disqualifies signals before ranking.

### Principle 4: Shadow-First Validation

> "Discard most signals. The bar to enter the model is high."

**Why:** Most patterns don't repeat. Most ideas don't have edge. Statistical proof is required before capital deployment.

**What this means:**

All I7 plugins and swarm agents are auto-enrolled in `shadow_registry` at startup:

```
Promotion criteria:
  - n >= 100 resolved signals
  - bootstrap_ci_lower(pnl_r) > 0.0 (at 95% confidence)

Demotion criteria:
  - EV[R] < -0.05 for 3 consecutive cycles
```

Shadow components continue writing data whether shadow or live. The `shadow_only` flag controls production influence, not data capture.

---

## I1-I8 Processing Hierarchy

```
I1  Foundation indicators        — 28 plugins: RSI, MACD, ATR, VWAP, OFI, CVD, volume_zscore
I2  Composite events             — 10 plugins: Crossovers, exhaustion, acceleration
I3  Market structure             — 8 plugins: Swing, S/R, session levels, market profile
I4  Regime classification        — 12 plugins: GARCH, Kalman, HMM, BOCPD, VIX, cross-asset
I5  Pattern detection            — 16 plugins: Divergence, squeeze, chart patterns
SMC Smart Money Concepts         — 16 plugins: BOS/CHoCH, FVG, OB, HMM (4 TFs), liquidity, AMD cycle
I6  Cross-timeframe confluence   — 6 plugins: CTF sub-scores → CIS scoring
I7  Trading signal generation    — 36 plugins + 2 aggregators: Setups + CISScorer + SignalAggregator
I8  AI narrative                 — LLM analysis per signal (Ollama local, default gemma4:e4b)
```

**Total: 132 plugins** + 2 aggregators (CISScorer, SignalAggregator).

### Layer Responsibilities

| Layer | Measures | Why it matters |
|-------|----------|-----------------|
| **I1 Foundation** | Raw indicator values | Mathematical foundation — all higher layers read these |
| **I2 Composite** | Indicator interactions | Crossovers, acceleration — turns continuous values into events |
| **I3 Structure** | Price structure facts | Swings, S/R, session levels — the market's geometry |
| **I4 Regime** | Regime classification | Prevents fighting the market — trend vs ranging vs volatile |
| **I5 Patterns** | Discrete pattern events | Divergence, squeeze, H&S — recognizable formations |
| **SMC** | Institutional footprints | BOS/CHoCH, FVG, OB — order flow evidence |
| **I6 Confluence** | Multi-timeframe agreement | Single-TF signals are noisy — confluence confirms |
| **I7 Signal** | Trading setups | The output — entry, stop-loss, take-profit |
| **I8 Narrative** | Human-readable explanation | Post-hoc reasoning — never affects signal generation |

---

## Data Flow

### Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Provider Layer                          │
│  IBKRProvider → market.bars.raw.ibkr                      │
│                          ↓                                      │
│              ProviderMerger (failover, routing)            │
│                          ↓                                      │
│                market.bars (canonical 1m)                       │
│                          ↓                                      │
│         BarAggregator (1m → HTF)                    │
│                          ↓                                      │
│                market.bars.htf (5m/15m/1h/4h/1d)               │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│         IntelligencePipeline (I1-I7 in-process)     │
│                                                                  │
│  Bar → [I1 parallel] → I2 → I3 → I4 → I5 → SMC → I6 → [I7 parallel] │
│                                                                  │
│  Internal asyncio.Queue (I6→I7) — zero I/O on hot path           │
│  State checkpointing — no warmup on restart                      │
└─────────────────────────────────────────────────────────────────┘
                          ↓                 ↓
              intelligence.journal    intelligence.i7.signals
              (tiered JSONB)           (winner signal)
                          ↓                 ↓
┌─────────────────────────────────────────────────────────────────┐
│                      Persistence Layer                           │
│  FeatureWriter → intelligence_features (TimescaleDB)       │
│  SignalWriter → signal_ledger (TimescaleDB)                │
└─────────────────────────────────────────────────────────────────┘
```

### Tier Parallelization

**Parallelized (via asyncio.gather + ThreadPoolExecutor):**
- **I1** (28 plugins) — Technical indicators
- **I7** (36 plugins) — Trading signals

**Sequential (current bottleneck):**
- **I2-I6** (74 plugins across 5 tiers) — 160ms, 73% of total latency

**GIL constraint:** Python's Global Interpreter Lock prevents threading from achieving true parallelism. Only one thread executes Python bytecode at a time.

---

## Core Data Contracts

### IntelligenceEvent (I1-I7)

Canonical schema defined in `src/intelligence/schemas.py`. All intelligence outputs flow through one model:

```python
class IntelligenceEvent(BaseModel):
    schema_version: Literal["1.0"]
    ts: datetime
    symbol: str
    tf: str
    bar: OHLCVBar
    i1: I1Indicators      # extra='allow' — 28 plugins, dynamic field names
    i2: I2Events          # Composite events
    i3: I3Structure       # Market structure (extra='forbid')
    i4: I4Context         # Context classification (extra='forbid')
    i5: I5Patterns        # Pattern detection (extra='forbid')
    smc: SMCContext       # Smart money concepts (extra='forbid')
    i6: I6Confluence      # Cross-timeframe confluence (extra='forbid')
    bar_close_ts: datetime | None
    i1_computed_at: datetime | None
    computed_at: datetime
    pipeline_latency_ms: float
```

**Sub-model field counts:**
- I1Indicators: ~50+ fields (extra='allow' for period-encoded names)
- I2Events: 17 fields (extra='allow')
- I3Structure: 77 fields (extra='forbid')
- I4Context: 93 fields (extra='forbid')
- I5Patterns: 91 fields (extra='forbid')
- SMCContext: 89 fields (extra='forbid')
- I6Confluence: 30+ fields (extra='forbid')

### Signal Schema

Version `"v1"` from `SIGNAL_SCHEMA_VERSION` in `src/intelligence/trading/signal_schema.py`. Single canonical constant — all producers/consumers import from there.

**Key fields:**
- `entry_zone_low` / `entry_zone_high` — entry zone bounds from TradeFrame
- `expires_at` — TTL deadline (bar-time wall-clock timestamp, Phase 107.5)
- `signal_type` — values: `at_close`, `at_pullback`, `at_limit`, `at_reclaim`, `zone_proximal`
- `exit_at` — when signal exited (not `exit_ts`)
- `activated_at` — when signal became active
- `outcome` — 8-class taxonomy

---

## Kafka Topics (Stream Keys)

All topic names built via `src/core/stream_keys.py`. Use the `topic_*` functions — never hardcode.

**Naming convention:** `<env>.<domain>[.<sublayer>]` — dots only, never colons.

### Core Topics

| Topic | Purpose | Consumer |
|-------|---------|----------|
| `market.bars` | Canonical 1m bars from merger | BarAggregator, IntelligencePipeline |
| `market.bars.htf` | HTF bars (5m-1d) from aggregator | IntelligencePipeline |
| `intelligence.journal` | Full I1-I7 feature vector per bar | FeatureWriter |
| `intelligence.i7.signals` | All ranked I7 signals per bar | SignalWriter, AlphaSwarm |
| `signals.aggregated` | Winner signal per bar | SignalTracker, API |
| `narratives` | I8 narrative output | LLMWriter, API |
| `llm.calls` | LLM audit log (every call) | LLMWriter |
| `signal_lineage` | Agent ancestry per signal | LineageWriter |
| `swarm.alpha` | Unified alpha multiplier topic | SwarmLedgerWriter |

### DLQ Topics

Every writer has a DLQ: `*.writer.dlq`. Route unparseable payloads here instead of silent drops.

---

## Database Schema

### Hypertables (TimescaleDB)

- `market_data_ohlcv` — Raw OHLCV ground truth (keep forever). Time column: `timestamp`
- `intelligence_features` — Full I1-I7 feature vectors per bar (ML training dataset, keep forever). Column name: `ts` (not `feature_ts`)

  **Tier->DB column mapping** (`IntelligenceEvent` Python field -> `intelligence_features` JSONB column):

  | Python field | DB column | Pydantic model |
  |-------------|-----------|----------------|
  | `i1` | `technical_indicators` | `I1Indicators` |
  | `i2` | `composite_events` | `I2Events` |
  | `i3` | `regime_features` | `I3Structure` |
  | `i4` | `confluence_scores` | `I4Context` |
  | `i5` | `pattern_detections` | `I5Patterns` |
  | `smc` | `smc` | `SMCContext` |
  | `i6` | `cross_timeframe_context` | `I6Confluence` |

- `signal_ledger` — ALL I7 signals + lifecycle outcomes (keep forever). Key columns: `entry_zone_low`, `entry_zone_high`, `expires_at`, `exit_at`. Time column: `timestamp`
- `signal_lineage` — Signal-affecting transforms and agent predictions (keep forever)
- `llm_calls` — LLM audit log + outcomes (keep forever). Composite PK: `(call_id, called_at)`

**Design principle:** Never drop data that could contain signal. Storage is cheapest, data is irreplaceable.

---

## CIS & Signal Confidence

CIS (Confluence Intelligence Score) requires agreement from at least 3 of 6 independent evidence buckets:

| Bucket | Reads from | Weight |
|--------|-----------|--------|
| **Trend** | Kalman slope, trend regime, SMC trend, cross-TF alignment | 0.20 |
| **Momentum** | RSI deviation, MACD histogram, ROC, momentum bias | 0.20 |
| **Structure** | Swing pattern, BOS/CHoCH events | 0.15 |
| **Pattern** | Double top/bottom, H&S, triangle completions | 0.05 |
| **Institutional** | Order blocks, FVG activity, supply/demand zones | 0.25 |
| **Regime** | HMM state probabilities, BOCPD changepoint, vol regime | 0.15 |

**Rule:** `|score| > 0.35` AND at least 3 of 6 buckets agree on direction.

**Key invariant:** `active` signal is always derived from `all_ranked`, never from the raw `signals` list.

The full stage sequence — `compose_confidence`, alpha decay, quality gate, regime gate, ToD adjustment, calibration, ranking, and winner selection — is documented in `docs/signals/signals-foundation.md` (Signal Quality Pipeline section). That is the canonical reference for how raw I7 plugin output becomes a ranked, selected signal.

### Adaptive Weight Systems

Two independent weight systems govern signal scoring. Do not conflate them.

**1. CIS Bucket Weights** — governs which *direction* to trust

Bootstrap weights (version 0) are manually tuned. The architecture supports learned weights loaded from `cis_weights` DB table. When `version > 0` exists, the scorer loads it at startup. Every `CISResult` carries `weights_version` — all signals in `signal_ledger` are traceable to the exact weight set that produced them.

```
signal fires (weight version N)
  → signal-tracker-compute tracks outcome (stop / target / TTL)
  → outcome written to signal_ledger
  → weight-learning job reads outcomes, fits logistic regression per bucket
  → new weights written to cis_weights (version N+1)
  → scorer loads version N+1 at next restart
```

**2. Setup Performance Weights** — governs which *setup plugin* to prefer

Independent of CIS scoring. Applied as a Sharpe-normalized performance multiplier on setup ranking.

```
signal_metrics table (rolling 30-day):
  setup_plugin, tf, symbol, regime_type, track, window_days, n, sharpe

perf_multiplier = 0.5 + ((n - 1 - rank) / n)   range [0.5, 1.5]
  rank = ascending Sharpe rank (best Sharpe → rank n-1 → highest multiplier)

Promotion gate: n >= 30 required — below threshold multiplier = 1.0 (neutral)
Regime conditioning: weights loaded per current HMM regime_type
  symbol-specific weights take precedence; '*' wildcard is fallback
```

`IntelligencePipeline` loads weights at startup and refreshes every hour. No Redis — weights flow: `signal_metrics` table → in-memory `_perf_weights` dict.

**Composition:** CIS governs which *direction* has cross-tier confirmation. Performance weights govern which *setup plugin* to prefer within the eligible pool. Neither overwrites the other.

---

## Renaissance Checklist

Before adding a new plugin, tier, or intelligence feature:

| Question | Renaissance principle |
|----------|----------------------|
| Can we measure it precisely and deterministically? | Determinism in hot path |
| Does it repeat statistically (n>=100, bootstrap CI > 0)? | Shadow-first validation |
| What regime is it valid in? Does it respect regime gates? | Regime-aware signal generation |
| Is it DB-ignorant (Kafka pub only)? | DB-ignorant compute |
| Does it write lineage whether shadow or live? | Continuous data capture |
| Will it feed the learning loop? | Infrastructure as edge |
| What's the latency budget? GIL-aware? | Infrastructure as edge |

---

## See Also

- **Implementation:** `intelligence-plugins.md` — How to add plugins
- **AI Agents:** `intelligence-ai.md` — How to add AI agents
- **Operations:** `intelligence-operations.md` — Services, monitoring, debugging
- **Code reference:** `src/intelligence/CLAUDE.md` — Plugin protocol, tier lists, utilities
- **Plugin registry:** `src/intelligence/register_plugins.py` — TIER_I1..TIER_I7 canonical lists
