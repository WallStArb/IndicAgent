# IndicAgent

A market intelligence platform built on a shared event-driven spine. New domains — fundamental, qualitative, derivatives — attach by publishing typed events to the bus; nothing already running changes.

The quantitative domain is live across 60 instruments: eight analytical tiers run in-process per bar — raw indicators, composite events, market structure, regime classification (GARCH, HMM, Kalman, BOCPD), pattern detection, institutional order flow, and 36 trading setups — all adjudicated by a six-bucket Confluence Intelligence Score that requires cross-tier agreement, not a single dominant factor. Sub-10ms bar-to-signal.

**Adaptive Parameter Registry (APR):** Every detection threshold, confidence weight, and indicator period is a versioned DB row with a source and reason — not a constant in code. ML discovery writes calibrated values after p < 0.05; CIS weights refine from signal outcomes; calibration curves refit per setup per regime; plugin promotion is governed by bootstrap CI. Every parameter the system acts on is learnable, tracked, and hot-reloadable without a restart.

**Extrinsic Confidence Layer (ECL):** Market context — regime state, confluence alignment, zone friction — travels on every signal as observable metadata, never as a gate that suppresses emission. Raw signals reach the training dataset uncontaminated regardless of downstream filtering. Winners and counterfactuals alike are recorded with the full feature vector at fire time, giving the ML layer a complete picture of the decision boundary — not just what worked, but what was correctly rejected.

**Vector Intelligence Layer (VIL):** Every bar state is embedded as a normalized vector in pgvector alongside its realized forward returns. At query time, the system retrieves the K most similar historical states and what price did after them — grounding every AI agent and scoring decision in empirical evidence rather than pattern intuition. IC-weighted, independence-calibrated, and domain-agnostic: the same substrate extends to fundamental, qualitative, and derivatives domains as they come online.

**Live:** [dash.indicagent.com](https://dash.indicagent.com)

> *Instrument everything · Signal with evidence · Learn from every outcome*

---

IndicAgent applies Renaissance Capital-style discipline at every layer: how components are named, how evidence is evaluated, how models are promoted or rejected. Mathematical precision as architecture, not decoration.

It's not a pipeline but a foundational architecture that can carry any form of market intelligence through a single shared spine - quantitative today, fundamental and qualitative domains next, evolvable AI agents throughout.

---

The core architectural bet: intelligence, execution, and risk are independent subscribers to a shared event stream - not coupled services calling each other. Every component is a microservice. Every interaction is an event. Every output is an API. New domains and agents attach by subscribing and publishing; nothing already running changes.

The quantitative domain is live on 60 instruments across futures, ETFs, FX, and crypto - producing evidence-graded trading signals in under 10ms, in production since early 2026, accumulating labeled training data with every bar. The architecture is designed to extend:

| Domain | Status | Scope |
|--------|--------|-------|
| **Quantitative** | In production | 8 tiers from raw indicators through regime classification to trading signals and AI synthesis |
| **Fundamental** | Designed | Earnings, macro data, COT positioning, sector rotation |
| **Qualitative** | Designed | News NLP, sentiment, prediction markets, macro regime narrative |
| **Derivatives** | Designed | Vol surface, gamma exposure, skew, options flow |

Each domain is an independent analysis engine. Downstream application agents - trade execution, portfolio management, risk management - consume from whichever domains they need by subscribing to the bus.

**The AI layer is multi-provider and agent-organized.** A multi-provider LLM chain (local Ollama, OpenRouter, DeepSeek) runs with per-provider circuit breakers - no single model or vendor is a dependency. Specialist agents handle focused tasks; composite agents synthesize them into a coherent view, the way a trading desk works. Two deeper systems sit behind this: an Evolvable AI framework where agents improve through Darwinian selection, and a Vector Intelligence Layer that grounds every AI conclusion in the K most similar historical bar states and what actually happened after them. Both are covered in detail below.

**What makes this different from a signal pipeline:**

- **Counterfactual recording** - every ranked candidate is recorded, not just winners. The system preserves the full decision boundary - what CIS selected and what it rejected - creating a training dataset that captures the rejections, not just the outcomes.
- **Statistical rigor throughout** - bootstrap confidence intervals for win rates, not point estimates. p < 0.05 promotion gates with minimum N. KS drift detection. CUSUM control charts. Proof, not thresholds.
- **Full signal lifecycle** - signals tracked from zone activation through 8-class outcome resolution with MAE and MFE per signal. Portfolio-level risk analytics embedded in signal tracking, not a win/loss tally.
- **Evolvable** - agents improve through natural selection: genome mutation, recombination, LLM-directed mutation. Fitness = accuracy × novelty × calibration × efficiency. Statistical gates at every lifecycle transition.
- **Empirical memory** - a Vector Intelligence Layer embeds every bar state in pgvector and retrieves the K most similar historical analogs at query time, with realized forward returns. IC-weighted, independence-calibrated, and domain-agnostic.
- **Self-improving** - CIS weights auto-refine from signal outcomes. ML models retrain on their own labeled data. Drift detection adjusts feature contributions in real time.
- **Self-healing** - services auto-restart in DAG order. Bar and signal replay auditors detect gaps and resolve orphaned lifecycles.
- **Full lineage and reproducibility** - every AI agent call tracked with prompt version, model, inputs, outputs, and timing. Every signal traces back through every transformation to raw data.
- **Provider-agnostic by design** - the intelligence pipeline has zero knowledge of where data comes from. It consumes typed events from the bus. Any real-time source plugs in the same way.
- **API-first** - every output immediately available over REST and SSE. Any HTTP client subscribes without pipeline changes.

---

## The Unified Data Bus

The central architectural decision: **services never call each other directly.** All communication flows through a durable, replayable event stream. Producers publish typed events; consumers subscribe to topics. A service going down means messages queue on the stream. On restart, it resumes from its committed offset - nothing lost, nothing re-requested. No service needs to know any other service exists.

This is what makes the microservices split real rather than cosmetic. In a conventional setup, services call each other via REST or gRPC - decoupled in name but coupled in operation. Here, the coupling is eliminated entirely. The bus is the only contract between producers and consumers, and that contract is a typed schema - `IntelligenceEvent`.

### Hot / Warm / Cold Data Tiers

```
Hot:  Market Data → Redpanda Streams → Services           (sub-ms ingestion)
Warm: Services → Intelligence Pipeline (I1–I8)            (<10ms extraction)
Cold: Writers → TimescaleDB (feature store, signal ledger) (async batch)
```

**Redpanda** (Kafka-compatible) on the hot path - sub-millisecond tick ingestion and stream fan-out to all downstream services. Raw market data enters here; every intelligence service reads from here. No database touches the hot path. Durable, partitioned, replayable logs - consumer groups ensure at-least-once delivery.

**Replay from offset 0.** A new consumer - a trading bot, ML model, alert engine, or downstream product - bootstraps by replaying the stream from the beginning. No data migration. No special onboarding. No pipeline changes. The history is already there.

### Zero Coupling Between Services

Each service has exactly one responsibility:

| Service | Owns |
|---------|------|
| Data Provider | Bar formation from high-frequency ticks (100–500+ ticks/sec), multi-timeframe aggregation |
| Intelligence Pipeline | Unified I1–I7 in-process computation - indicators, structure, regime, patterns, SMC, confluence, trading signals |
| Signal Writer | I7 signal persistence to signal_ledger (all ranked candidates) |
| Signal Tracker Compute | Zone activation, MAE/MFE, outcome classification (DB-ignorant; publishes LifecycleTransition events) |
| Lifecycle Writer | Persists LifecycleTransition events to signal_ledger |
| Signal Metrics Compute | Rolling 30d Sharpe/win-rate per setup per regime |
| Feature Writer | Intelligence feature persistence to TimescaleDB |
| LLM Writer | LLM call audit trail with outcome back-fill |
| Alpha Swarm | Routes analytical tasks to specialist swarm agents |
| AI Narrative | I8 LLM analysis and group synthesis |
| API | SSE fan-out and REST delivery to clients |

```
Data Source ──► [Redpanda topics] ──► intelligence_pipeline_agent (I1–I7, unified in-process)
                                       ──► signal_writer_agent (signal_ledger persistence)
                                       ──► feature_writer_agent (intelligence_features)
                                       ──► alpha_swarm_agent (shadow analysis)
                                       ──► ai_narrative_service (I8)
                                       ──► api_service ──► SSE ──► any HTTP client
```

Each arrow is a Redpanda topic. The topics are the API between services.

### Stream Keys

Every stream is namespaced and typed:

| Topic | Carries |
|-------|---------|
| `{env}.intelligence` | Full typed `IntelligenceEvent` (I1–I7 payload) keyed `SYMBOL:TF` |
| `{env}.intelligence.i7.signals` | All ranked I7 candidates per bar (pre-ledger write) |
| `{env}.intelligence.journal` | High-confidence signals routed to AI narrative (I8 input) |
| `{env}.intelligence.lifecycle` | LifecycleTransition events from SignalTrackerComputeAgent |
| `{env}.intelligence.signal_metrics` | Rolling signal performance stats per setup per regime |
| `{env}.narratives` | I8 LLM narrative text keyed `SYMBOL:TF` |
| `{env}.llm.calls` | Every LLM invocation (success, failure, model used) |
| `{env}.llm.outcomes` | Signal lifecycle exits with outcome, P&L R, MAE, MFE |

### The Service DAG

The service DAG runs in 10 layers. Dependencies are declared, not hardcoded - the execution engine derives order via topological sort at startup. Circular dependencies are detected and hard-crash before any live data flows.

```
L1   data-provider                                    - data ingestion
L2   provider-merger                                  - stream merge
L3   bar-aggregator, bar-auditor                      - bar processing
L4   bar-writer                                       - OHLCV persistence
L5   intelligence-pipeline, cross-asset, macro-compute - I1–I7 compute + context
L6   feature-writer, signal-writer, signal-tracker,
     lifecycle-writer, lineage-writer                  - persistence writers (parallel)
L7   alpha-swarm, llm-writer                          - AI/LLM layer
L8   roll-compute, signal-metrics, graduation-writer   - analytics + rolling metrics
L9   signal-auditor, parity-auditor, alerting-agent    - audit, parity, alerting
L10  service-auditor                                   - meta: monitors + restarts all above
```

A meta-service at L10 monitors all others, restarts in DAG order, and escalates after repeated failures. Each service is independently deployable, restartable, and observable - systemd-managed with Prometheus lag monitoring.

### DAG Invariants

These are non-negotiable architectural constraints. Any code that violates one of them breaks the guarantees above.

1. **`ProviderMergerAgent` is the sole writer to `market.bars`** - downstream agents are isolated from provider topology. Adding a new data source requires zero downstream changes.
2. **I1–I7 runs entirely in-process** - Kafka is a sink, not an inter-stage pipe. No Kafka hop between intelligence tiers.
3. **No ComputeAgent touches the database** - only WriterAgents, TrackerAgents, and AuditorAgents perform DB operations. A DB outage has zero impact on signal generation.
4. **All topic keys via `stream_keys.py`** - no hardcoded topic strings anywhere in the codebase.
5. **No agent calls another agent directly** - topics are the only coupling. Every agent can be restarted independently and resumes from its committed Kafka offset.
6. **All timestamps UTC** - `datetime.now(UTC)` only. Every bar, event, and DB write is timezone-aware.
7. **Scaling via systemd + Prometheus lag** - no Kubernetes HPA. Consumer lag is the scaling signal.

Full system map with Mermaid diagram and topic registry: [`docs/architecture/architecture-dag-topology.md`](docs/architecture/architecture-dag-topology.md).

---

## Intelligence Pipeline: I1–I8

The quantitative domain processes data through 8 tiers. Each builds on the outputs of the tiers below it - no tier skips a level. A multi-timeframe aggregator rolls 1m bars forward to 5m, 15m, 1h, 4h, and 1d; each timeframe runs the full pipeline independently, giving every signal a multi-timeframe context.

### Layer 1: Data Foundation

A data provider daemon connects to a real-time market feed and forms 1m bars from high-frequency ticks. Bar-close events trigger the full I1–I8 pipeline. The provider is an implementation detail - the pipeline consumes typed events from the bus, not from any specific broker.

### Layer 2: Mathematical Intelligence

**I1 - Raw Indicators**

Incremental computation - each bar updates indicator state without recomputing history. RSI, MACD, Bollinger Bands, ATR, VWAP, Supertrend, Parabolic SAR, Stochastic RSI, Chaikin Money Flow, Aroon, SMA, EMA, OBV, ADX/DI, ROC, Awesome Oscillator, Accelerator Oscillator, Donchian Channels, CCI, Williams %R, MFI, Keltner Channels, Historical Volatility, Chandelier Exit, HMA, OFI, CVD. Every value published once per bar per symbol per timeframe.

**I2 - Composite Events**

Discrete events derived from I1 outputs. The standout plugins are second-derivative: **MomentumAcceleration** detects inflection points *before* they complete using rate-of-change on RSI, MACD, and ROC; **ExhaustionScore** composites volume, RSI extreme, reversal candlestick, and ATR spike to identify when a trend is running out of fuel - a leading indicator for regime transition.

**I3 - Market Structure**

Price action context above the indicator level: swing detection, S/R zones, Market Profile (volume distribution → POC, value area), Anchored VWAP, Fibonacci, session levels. **SwingMomentum** links live momentum readings directly to structural swing context - giving I5 divergence plugins a richer foundation.

**I4 - Regime Classification**

The statistical core. Six models answer distinct questions about the current regime:

| Model | Question | Output |
|-------|----------|--------|
| **GARCH** | Is volatility expanding or contracting? | Volatility regime (low/normal/elevated/extreme) + sigma estimate |
| **Kalman filter** | What is the true underlying trend, separate from noise? | Smooth trend slope - adapts to current signal-to-noise ratio |
| **HMM** | Which hidden regime is most probable? | Probability *distribution* over 3 states - not just an argmax |
| **BOCPD** | Is a new regime beginning right now? | Changepoint probability per bar - detects transitions before HMM confirms |
| **Hurst Exponent** | Is this market persistent or mean-reverting? | H-value + persistence class - gates signal direction vs. regime |
| **Shannon Entropy** | How predictable is the current price series? | Entropy score - feeds CIS quality multiplier |

### Layer 3: Pattern Intelligence

**I5 - Pattern Detection**

Discrete pattern recognition on the mathematical foundation: RSI divergence, volatility squeeze (Bollinger Bands inside Keltner Channels - compression that precedes expansion), chart patterns (H&S, double top/bottom, triangles, flags, cup and handle, measured move). All feed directly into I6 confluence scoring.

**I6 - Smart Money Concepts + Confluence**

Institutional order flow analysis - the interpretation of price action as the footprint of large participants:

- **BOS/CHoCH** - Break of Structure (trend continuation) vs. Change of Character (swing structure broken *against* the trend - the earliest structural reversal signal)
- **FVG** (Fair Value Gap) - 3-candle price imbalance where liquidity was left unfilled. Tracked by type, fill status, and freshness
- **BOCPD** - Bayesian Online Changepoint Detection. Detects the moment statistical properties shift in real time - before HMM confirms a new regime
- **Liquidity pools · Order blocks · ICT Killzones · AMD cycles** - complete institutional order flow model, aggregated across 6 timeframes into a single directional score

**I7 - Trading Setups**

Each plugin defines a trade thesis with entry, stop-loss, and take-profit logic: `TrendFollowing` · `MeanReversion` · `LiquiditySweepReclaim` · `SqueezeExpansion` · `VWAPDeviation` · `FVGFill` · `PatternCompletion` · `DivergenceStack` · `CHoCHReversal` · `OFIContinuation` · `OFIDivergence` · `CVDDivergence` · `CrossAssetDivergence` · `AnchoredVWAPReversion` · `POCRejection` · `ORB15` · `ORB30` · `VCP` - 36 setups in total.

**Signal architecture uses two named systems:**

**Extrinsic Confidence Layer (ECL)** — the set of extrinsic confidence vectors (CTF score, HMM regime weight, zone friction, exhaustion guard) that travel on each signal as observable metadata. ECL vectors annotate signals with market context; they are never gates that suppress emission and never inputs to the intrinsic confidence composite. The ECL boundary is a hard architectural invariant: intrinsic confidence = pattern-internal factors only; extrinsic context = ECL metadata. This keeps raw signals as uncontaminated training data regardless of downstream filtering. See `docs/architecture/setup-confidence-patterns.md`.

**Adaptive Parameter Registry (APR)** — all detection thresholds, confidence weights, and indicator periods that govern signal generation live in the APR rather than in code. Parameters start as `[initial_estimate]` human priors and evolve as ML discovery writes calibrated values after p < 0.05. Hot-reload via Kafka outbox — no restarts required. The APR makes every parameter observable and learnable; hard-coded constants in signal plugins are an architecture violation. See `docs/foundation/parameter-store.md`.

When multiple setups fire on the same bar, the **CIS scorer** adjudicates (see below). Selected signals pass two gates:
1. **RR gate** - viable risk:reward based on zone quality and distance to target
2. **Regime gate** - HMM confidence threshold, regime stability, direction match. Direction mismatches are suppressed and recorded as shadow signals for counterfactual tracking

Every I7 signal passes through a deterministic quality pipeline before Kafka emission - see [Signal Quality Pipeline](#signal-quality-pipeline) below.

### Layer 4: AI Intelligence

**I8 - AI Narrative & Synthesis**

For every signal above confidence 0.7, the AI Narrative Service generates a structured analysis of the full signal context - tier state, regime, SMC context, setup rationale, entry/stop/target. The LLM receives the full `IntelligenceEvent` payload, not a template. Beyond per-signal narratives: group synthesis at configurable intervals across 6 asset groups (equity indices, energy, metals, rates, FX, crypto).

The multi-provider LLM chain (local Ollama on AMD ROCm GPU, OpenRouter) runs with per-provider circuit breakers - no single model is a dependency. Every call logged to `llm_calls` for full audit. Outcomes are back-filled as signals resolve, linking every LLM call to its eventual result.

### Feature Coverage

Every bar for every instrument on every timeframe produces a full feature vector across all tiers.

| Tier | Plugins | Data Points | What It Measures |
|------|---------|-------------|-----------------|
| **I1** Raw Indicators | 28 | ~50 | Price, momentum, volatility, volume math - RSI, MACD, ATR, Bollinger, VWAP, OFI, CVD, etc. |
| **I2** Composite Events | 10 | ~20 | Discrete events from I1 - crossovers, threshold breaches, momentum acceleration, exhaustion scoring |
| **I3** Market Structure | 8 | ~77 | Price geometry - swing points, S/R zones, market profile (POC/VA), session levels, Fibonacci zones |
| **I4** Regime Context | 12 | ~93 | Statistical state - GARCH vol forecast, Kalman trend, HMM regime probabilities, Hurst persistence, Shannon entropy, volume profile |
| **I5** Patterns | 16 | ~91 | Discrete patterns - RSI/MACD/CMF divergence, squeeze detection, chart patterns (H&S, triangles, flags, cup & handle) |
| **SMC** Smart Money | 13 | ~89 | Institutional footprint - BOS/CHoCH, fair value gaps, order blocks, liquidity pools, BOCPD changepoints, AMD cycles |
| **I6** Confluence | 6 | ~26 | Cross-timeframe alignment - trend, structure, regime, momentum, orderflow, squeeze agreement across 4 timeframes |
| **I7** Trading Signals | 36 + 2 agg | ~283 | Actionable setups - entry/stop/target, confidence scoring, feature snapshots, CIS bucket breakdown, regime gate metadata |
| | **129 + 2** | **~729** | |

Each data point is computed incrementally per bar (O(1) via `compute_next()`, not batch), persisted to `intelligence_features` (TimescaleDB), and streamed to subscribers in real-time via SSE.

---

## CIS: Confluence Intelligence Score

The decision engine. When multiple I7 setups fire simultaneously on the same bar, CIS adjudicates by aggregating evidence from the entire pipeline into a single directional score.

### Six Evidence Buckets

| Bucket | Reads from | Weight |
|--------|-----------|--------|
| **Trend** | Kalman slope, trend regime, SMC trend, cross-TF alignment | 0.20 |
| **Momentum** | RSI deviation, MACD histogram, ROC, momentum bias | 0.20 |
| **Structure** | Swing pattern, BOS/CHoCH events, CHoCHReversal | 0.15 |
| **Pattern** | Double top/bottom, H&S, triangle completions | 0.05 |
| **Institutional** | Order blocks, FVG activity, supply/demand zones | 0.25 |
| **Regime** | HMM state probabilities, BOCPD changepoint, vol regime | 0.15 |

CIS fires only when `|score| > 0.35` **and** at least 3 of 6 buckets agree on direction. A single dominant bucket cannot override the rest - cross-tier confirmation is structurally required.

Each bucket returns `(score, contribution)` - not just the aggregate. The breakdown is logged per signal and exposed via the API. You can see exactly which buckets drove a CIS election and by how much.

### The Learning Loop

Every CIS result is tagged with a `weights_version`. Every signal lifecycle outcome pairs the full CIS bucket vector at signal time with its eventual outcome. All ranked candidates - not just winners - are recorded, giving a complete view of the decision boundary including the counterfactuals CIS rejected.

```
Signal fires → CIS tags with weights_version=N
     │
     ▼
Signal lifecycle: activation · zone_entry_pct · bars_to_activation · MAE · MFE
→ 8-class outcome: never_activated · stopped_at_entry · stopped_in_trade ·
                   target_1 · target_1_2 · target_full · ttl_expired_ahead · ttl_expired_behind
     │
     ▼
Outcome + full I1–I8 feature vector → signal_ledger (labeled training data)
     │
     ▼
Logistic regression → new cis_weights (version N+1)
→ better selection → more outcome data → loop
```

The learning path: logistic regression on this dataset fits per-bucket weights that maximize outcome prediction. When updated weights are present, the scorer loads them at startup. CIS improves without code changes.

---

## Signal Quality Pipeline

Every I7 signal passes through a deterministic sequence of transformations between plugin output and Kafka emission. Confidence is not a single number assigned at plugin time - it is refined at each stage by independent evidence.

```
I7 plugin fires
  → compose_confidence()        enforce [0.10, 0.95] - no plugin claims certainty
  → pre_quality_confidence      preserve raw plugin output for ML training labels
  → alpha decay                 0.5^(fires_since_last_win / half_life) - autocorrelation discount
  → CIS scoring                 add cis_score, bucket_scores across 6 evidence dimensions
  → quality gate                min(Hurst, Entropy) × KS drift penalty × empirical floor
  → regime gate                 suppress on hmm_regime vs plugin.regime_type mismatch
  → ToD adjustment              120-cell (regime_type, timeframe, hour_et) win-rate multiplier
  → isotonic calibration        map raw → empirical probability via historical outcomes
  → rank_signals()              adjusted_rank = perf_multiplier from rolling Sharpe [0.5, 1.5]
  → select_winner()             highest-ranked regime-eligible signal; ties → confidence
  → swarm overlay               adjusted_confidence = calibrated × swarm_multiplier (MoA, 5 agents)
  → structural completeness     verify required fields; DLQ + metric increment on any miss
  → emit to intelligence.i7.signals
```

**[1] `compose_confidence` - clamp `[0.10, 0.95]`** - enforced at plugin construction via a single shared function. No plugin can claim certainty (≥ 0.95) or produce a zero-confidence signal that would persist invisibly in lifecycle tracking. No inline clamping permitted in plugin bodies.

**[2] `pre_quality_confidence` - training data integrity** - stamped before any multiplier or decay touches the signal. This field is what the ML model trains against - raw plugin output, uncontaminated by post-processing. Every downstream adjustment is auditable without corrupting the training labels.

**[3] Alpha decay - `0.5^(n / half_life)`** where `n` counts fires since last win, not elapsed bars. A plugin that fires 10 consecutive bars is not 10 independent observations - each re-fire after a win is autocorrelated evidence. Confidence halves every `half_life` fires. A plugin that goes quiet and re-emerges carries zero accumulated decay - silence is not evidence of quality loss. Half-life constants (`1m=10, 5m=8, 15m=8, 1h=6` fires) are empirical priors; the training data exists to derive them from measured autocorrelation structure.

**[4] Quality gate - `min(Hurst, Entropy) × KS drift penalty × empirical floor`** - `min()` not product because Hurst and Entropy both measure regime predictability and are correlated; compounding them double-penalizes the same signal. KS drift penalty (Kolmogorov-Smirnov test against historical feature distributions) discounts proportionally to out-of-distribution divergence - not a binary drop. Empirical floor derived from p10 confidence of historically profitable signals.

**[5] Regime gate** - HMM regime state versus plugin's declared `regime_type` (`"trend"` / `"mean_reversion"` / `"any"`). Trend plugins suppressed in ranging regime; mean-reversion plugins suppressed in trending. Suppressed signals are still written to `signal_ledger` (`regime_suppressed`) for counterfactual tracking.

**[6] Time-of-day adjustment - 120 cells** - `(regime_type, timeframe, hour_et)` lookup table of rolling historical win rates. A trend setup at RTH open has structurally different reliability than the same setup at 2pm ET. Cells with insufficient history default to neutral (1.0).

**[7] Isotonic calibration** - raw confidence is systematically biased upward. Isotonic regression fits a monotone map from raw → empirical win probability using resolved signal outcomes, per `(setup_plugin, regime_type)` segment. Calibration in a trending regime is independent of calibration in a ranging regime - same plugin, different reliability profile.

**[8] Ranking - `adjusted_rank` from rolling Sharpe `[0.5, 1.5]`** - validated setups (`n ≥ 30`) ranked by rolling 30-day Sharpe per regime. Unvalidated setups receive a warm-up penalty (`adjusted_rank = 0.5`) - they cannot outrank proven setups until statistically demonstrated. Winner selection: highest `adjusted_rank` among regime-eligible signals; confidence breaks ties.

**[9] Swarm overlay** - after winner selection, `AlphaSwarm` applies `swarm_multiplier` from a mixture-of-agents composite (5 specialist agents: skeptic, correlation, volume, ML scorer, macro). Can reduce confidence; cannot change which signal was selected.

**[10] CUSUM + shadow gate - the two feedback loops** - CUSUM control charts track win rate per setup and feed back into `perf_multiplier` without waiting for the 30-day window to catch up. Shadow gate requires `n ≥ 100` AND `bootstrap_ci_lower(pnl_r) > 0.0` (statistically positive EV at 95% CI) before a plugin enters the live stream. Demotion: `EV[R] < -0.05` for 3 consecutive evaluation cycles.

Full stage-by-stage detail: [`docs/signals/signals-foundation.md`](docs/signals/signals-foundation.md) · CIS bucket weights and adaptive weight systems: [`docs/intelligence/intelligence-foundation.md`](docs/intelligence/intelligence-foundation.md)

---

## Signal Lifecycle

Every signal is tracked through its complete lifecycle - not fired and forgotten.

**Zone-based activation.** Signals define entry zones (proximal, distal) rather than single price levels. The tracker monitors price relative to these zones and records `zone_entry_pct` - how deep into the zone price penetrated before activating or expiring. This provides granular data on entry quality that a simple "price crossed X" model cannot.

**MAE and MFE per signal.** Maximum Adverse Excursion and Maximum Favorable Excursion are tracked from activation through exit. These are portfolio-level risk analytics embedded directly in signal tracking - the basis for optimal stop and target placement in position sizing.

**8-class outcome taxonomy:**

| Outcome | Meaning |
|---------|---------|
| `never_activated` | Price never entered the signal zone before TTL expired |
| `stopped_at_entry` | Stop hit at or near entry, before meaningful trade developed |
| `stopped_in_trade` | Stop hit after activation, during the trade |
| `target_1` | First profit target reached |
| `target_1_2` | First and second targets reached |
| `target_full` | All targets reached |
| `ttl_expired_ahead` | TTL expired while in profit |
| `ttl_expired_behind` | TTL expired while at a loss |

**Counterfactual recording.** All ranked candidates - not just winners - are written to `signal_ledger`. The system records the full I1–I8 feature vector, the CIS bucket breakdown, and the eventual outcome for every signal the pipeline considered. This is the decision boundary: the dataset tells the ML model not just what worked, but what *almost* worked and what was correctly rejected.

**Structural validation at construction.** Every signal is built through a single public factory (`make_signal_from_frame`) that enforces structural invariants - stop distance, stop type, minimum R:R - at the construction boundary. A signal that fails these gates never enters the pipeline. The executor re-validates at the aggregation boundary. Structural guards, not version tags.

---

## The AI Swarm & Evolvable Intelligence

### Specialist Agents and Composite Agents

The AI layer is organized the way a trading desk is organized: **specialist agents perform tasks, composite agents perform roles.**

A skeptic agent challenges every signal. A correlation agent checks whether the signal is genuinely independent or a restating of existing positions. A volume agent analyzes whether order flow confirms or contradicts the setup. These are specialists - focused, fast, replaceable.

Composite agents orchestrate multiple specialists into a coherent view - the same way a senior trader synthesizes input from a technical analyst, a risk manager, and a flow trader. The output isn't a single model's opinion; it's a structured multi-perspective assessment with dissent recorded.

Every agent call is traced. A `LineageRecorder` tracks prompt version, model, inputs, outputs, and timing per call. Full reproducibility - you can reconstruct why any agent made any decision at any point in history.

### Evolvable AI (eAI) - Agents That Evolve

Beyond learning from data, the platform is designed for agents that evolve through Darwinian selection. Inspired by research in evolvable AI (PNAS 2025) and Renaissance Technologies' approach to model management.

Three epochs of AI:

1. **Intelligence by design** - handcrafted rules, logic, expert systems
2. **Intelligence by learning** - training on data, gradient descent, RLHF
3. **Intelligence by evolution** - agents that improve their own capacity for improvement

Markets are non-stationary. Manual agent design produces agents that reflect current mental models. An evolutionary system discovers edges that exist beyond those models.

**The agent genome** - each agent's "DNA" is a composite of independently heritable components:

| Chromosome | What evolves |
|------------|-------------|
| System prompts | Reasoning strategy, analytical frame, chain-of-thought structure |
| Configuration parameters | Thresholds, timeframe weights, scoring coefficients |
| Tool sets | Which data sources and analysis tools the agent can access |
| Model adapters | Fine-tuned weights for task-specific specialization |
| Guardrails | Constraints and behavioral boundaries |

**Three reproductive operators:**

- **Mutation** - blind perturbation of genome components. Exploration. Escape local optima.
- **Recombination** - two fit parents contribute genome segments via crossover. Prompt from parent A + config from parent B + tool set blend. Novel combinations neither parent could produce alone.
- **LLM-directed mutation** - an LLM analyzes a parent's genome and performance, then proposes targeted improvements. Directed search with access to the full corpus of trading research as its gene pool. The most powerful operator, reserved for high-fitness parents.

**Lifecycle: birth → shadow incubation → breeding → promotion → live.**

Every newborn agent enters shadow mode - observing live data, producing analysis, zero production impact. Fitness is measured out-of-sample across multiple regimes. The system tracks which reproductive operator produces the fittest offspring and dynamically shifts budget toward better operators - meta-optimization of the search itself.

**Composite fitness = accuracy × novelty × calibration × regime specificity × efficiency.**

An agent that's right for the wrong reasons, or that duplicates an existing agent's edge, doesn't promote. The statistical gate: bootstrap CI > 0 at 95% confidence. Unique, calibrated, regime-aware alpha - nothing less clears the gate.

Promotion requires both automated gates (sustained fitness across ≥ 3 regimes, stability, novelty) and human review - the *why* matters, not just the *what*. On promotion, full genome + ancestry chain is recorded permanently, traceable to generation 0.

---

## Machine Learning Layer (MLAgent)

> The feature store and signal ledger are already accumulating the labeled training data this consumes.

The ML layer closes the learning loop at the model level - replacing hand-tuned weights with a full ensemble trained on labeled signal outcomes. Five agents, orchestrated by LangGraph:

| Agent | Role |
|-------|------|
| **Orchestrator** | Routes work, decides retrain / promote / escalate based on monitoring signals |
| **Data Quality Agent** | Validates training data integrity before any model runs |
| **Discovery Agent** | tsfresh feature extraction, Pearson IC analysis, regime-conditional IC, cross-asset lag correlation |
| **Training Agent** | LightGBM ensemble per segment (regime × setup × TF), time-series CV, shadow mode gate |
| **Monitoring Agent** | Evidently drift detection (KS/PSI/Wasserstein), CUSUM degradation, circuit breaker |

No model reaches production without p < 0.05 with sufficient N. Borderline p-values pause the graph and require human approval - a dashboard alert presents the full model comparison; 4-hour timeout defaults to reject.

**The dataset - already accumulating:**

| Table | Stores | ML role |
|-------|--------|---------|
| `intelligence_features` | Full I1–I8 feature vector per bar (tiered JSONB) | Training inputs |
| `signal_ledger` | Signal + 8-class lifecycle outcome, MAE, MFE, bars-in-trade | Training targets |
| `llm_calls` | Every LLM invocation with back-filled signal outcome | LLM model scoring |
| `signal_metrics` | Per-setup rolling 30d win rate, avg P&L R, Sharpe per regime | Performance baseline |
| `cis_weights` | Adaptive bucket weights, versioned | Model deployment output |

Every bar the pipeline processes adds a row to `intelligence_features`. Every signal that resolves adds an outcome row to `signal_ledger`. The ML layer consumes this dataset - the platform has been building it since day one.

**ML stack:** `langgraph` + `langchain` · `langfuse` (self-hosted observability) · `guardrails-ai` (LLM output validation) · `scipy` + `tsfresh` (700+ statistical features) · `evidently` (drift detection) · `polars` (Rust dataframes) · `lightgbm` (tabular champion) · `shap` (TreeSHAP explainability) · `optuna` (Bayesian hyperparameter optimization) · `mlflow` (model registry) · `river` (online/incremental learning).

---

## Adaptive Parameter Registry (APR) — Every Parameter Is a DB Row

Every numeric value that governs signal behavior — detection thresholds, confidence weights, indicator periods, governance gates, regime multipliers — lives in the APR rather than in code. Hard-coded constants in `src/` are an architecture violation.

Parameters are not static configuration. They start as `[initial_estimate]` human priors and move through a defined lifecycle:

```
seed → operator_tuning → ml_learned → user_override → ml_learned again
```

Every write is recorded in `config_history` with `changed_by` and `reason` — the full conversation between human judgment and empirical evidence is preserved. ML discovery writes calibrated values back after p < 0.05 with sufficient N. Updates broadcast via Kafka outbox for hot-reload; no service restarts required.

### What the APR governs

| Namespace | Examples |
|-----------|---------|
| `threshold.*` | Plugin detection gates — minimum structural strength, zone proximity, divergence depth |
| `weights.*` | CIS bucket weights, confidence composite factors |
| `feature.*` | Indicator periods — SMA/RSI/ATR lookback windows |
| `regime.*` | HMM confidence thresholds, regime stability gates |
| `shadow.*` | Promotion gates — minimum N, bootstrap CI floor |
| `signal.*` | TTL bars, alpha decay half-life per timeframe |
| `swarm.*` | Swarm agent weights, mixture-of-agents coefficients |

### The feedback loop

The APR is the write target for every learning system in the platform:

- **ML discovery** — tsfresh feature extraction + IC analysis → writes optimal indicator periods and threshold values after p < 0.05
- **CIS weight refinement** — logistic regression on outcome labels → writes updated bucket weights versioned by `weights_version`
- **Isotonic calibration** — fits monotone confidence maps per `(setup_plugin, regime_type)` segment → writes calibration parameters back to APR
- **Shadow governance** — bootstrap CI evaluation every N signals → writes promotion/demotion decisions

Every parameter the system acts on has a path from human prior to empirically calibrated value. The APR is what makes "self-improving" a structural property rather than a marketing claim.

Full spec: [`docs/foundation/parameter-store.md`](docs/foundation/parameter-store.md)

---

## Vector Intelligence Layer - Empirical Memory for the Pipeline

The I1–I7 pipeline is a sophisticated prediction machine with one critical gap: it has no memory of what it has predicted before. Every bar is processed as if it is the first bar. RSI reads 67, regime is trending, SMC structure shows a bullish order block - the pipeline computes all of this, fires a confluence score, generates a signal. Then the bar closes, price moves, and the system forgets. The intelligence state at that bar and the outcome that followed are never connected.

Renaissance's edge is not in having better models - it is in having more observations per model. The Medallion fund runs thousands of overlapping signals, each carrying a small IC, and the edge compounds across their statistical independence. The critical infrastructure that makes this possible is the ability to retrieve, at any level of granularity, the historical states most similar to now and what price did after them.

That infrastructure is the Vector Intelligence Layer.

### What VIL Does

VIL is a retrieval substrate. Its job is exactly two things:

1. **Embed** - encode bar states, plugin histories, and signals as L2-normalized vectors, stored in pgvector alongside what price did afterward at T+5, T+10, T+20
2. **Retrieve** - given the current bar as a query vector, return the K most similar historical states and their realized forward returns

That is the full scope of VIL. It returns analog sets. It does not score them.

The boundary is intentional. Turning an analog set into a score - directional hit rate, return distribution, composite conviction, percentile rank - belongs to the layers above. The retrieval substrate stays focused, testable, and reusable across every consumer that needs "find conditions similar to these and see what happened."

The embedding serialization is the hardest problem and the one with the highest blast radius. Raw flattening of the ~100 numerical fields from `intelligence_features` fails because mixed scales (RSI 0–100, volume in millions, price in thousands) make cosine distance meaningless - dominated by magnitude, not structure. The solution: per-feature rolling z-scores (or percentile ranks for bounded features), point-in-time only, categorical fields excluded from the vector and applied as retrieval filters. The contract is versioned - a serialization change invalidates stored history and forces explicit migration, never a silent corruption.

### The Five-Layer Stack

VIL is the foundation of a five-layer empirical intelligence stack. Each layer has a strict contract and a single owner:

```
vil-01  Substrate         Embed · label · retrieve → list[AnalogResult]
                          Three tables (embeddings, outcome_labels, similarity_pairs)
                          One retrieval primitive - scoped k-NN, regime filter, distance gate

vil-02  Feature IC        Outcome Labeler - forward R-multiples per bar at T+5/10/20/60
                          IC Factory - Spearman IC × IC Sharpe × FDR correction per feature
                          Analog Finder - thin VIL wrapper returning raw analog set
                          Question: "what predicts price, with what stability, in which regime?"

vil-03  Scoring Engine    Transforms list[AnalogResult] + IC weights → Score Object
                          Distribution · directional HR · expected R · composite z-score
                          Conviction envelope (based on analog count + mean distance)
                          Four resolution levels: L0 plugin, L1 symbol/TF, L2 cross-TF, L3 cross-asset

vil-04  Correlation       Pairwise cosine similarity of plugin/signal/feature histories
                          Eigenvalue decomposition → effective-N (truly independent signal sources)
                          Redundant plugin suppression fed back to shadow_registry
                          Question: "are you counting one observation as two?"

vil-05  Signal Combiner   IC-weighted + decorrelated combination of the full live edge set
                          Shrinks raw E[R] toward zero in proportion to IC Sharpe
                          Marginal contribution, not standalone strength, is the value metric
                          The terminal layer - where aggregate independent conviction lives
```

Each layer measures or transforms; none acts. VIL retrieves. vil-02 measures prediction (IC). vil-04 measures independence (effective-N). vil-03 scores each edge in isolation. vil-05 combines them into one conviction view that accounts for both trust and overlap. The separation is what makes each layer testable and the whole stack evolvable.

### What VIL Enables

| Consumer | What they gain |
|---|---|
| **LLM swarm agents** | Grounded historical evidence in every prompt: "47 similar bars found - 63% up at T+10, avg +0.4R." Agents reason over evidence, not pattern intuition |
| **I7 governance** | Evidence-based raise/suppress: does the current intelligence state historically precede favorable moves? IC replaces hand-tuned rules |
| **eAI fitness** | Empirical ground truth: an agent's predictions are measured against the analog distribution for the same bars. Calibration is a SQL query, not a narrative judgment |
| **Signal independence** | With 138 plugins, if effective-N is 20, downstream confidence estimates are inflated 7x. vil-04 surfaces this continuously - `effective_plugin_count` is a live, alertable gauge |
| **Research** | "Which features have genuine predictive power at 10-bar horizon in trending regime?" becomes a query over `feature_ic_stats`, queryable in Superset |
| **Signal combiner** | IC-weighted, decorrelated conviction across the full live edge set - many small independent edges summing to one large stable view, the way Renaissance actually does it |

### Out-of-Distribution Detection

When the current bar has no analogs within the distance threshold, the market is in a state the historical record has never seen. Every model downstream - every score, every IC weight, every analog distribution - is extrapolating out-of-sample. VIL exposes an **OOD monitor**: `vil_ood_rate`, the rolling fraction of live retrievals returning no close analogs. A spike is an early warning that the current environment has decoupled from history - arriving before parametric regime classifiers catch it, because "nothing looks like this" precedes "this looks like regime X." VIL surfaces the signal; a consumer decides the response. Reduce conviction, widen intervals, alert research - the decision is explicit, never silent.

### Extending Intelligence to New Domains

The VIL substrate is domain-agnostic. The same embed → label → retrieve architecture that works for quantitative bar states works for any structured intelligence state. This is the foundation for the extension to fundamental and qualitative intelligence:

| Domain | What gets embedded | What gets retrieved |
|---|---|---|
| **Fundamental** | Earnings surprise vectors, macro indicator states, COT positioning | Historical macro analogs and what equity regimes followed |
| **Qualitative** | News sentiment vectors, prediction market states, analyst positioning | Sentiment conditions and what price environments followed |
| **Cross-domain** | Joined quantitative + fundamental state | Conditions where multiple domains agreed - the highest-conviction analog |
| **Derivatives** | Vol surface shape, gamma exposure, skew | Options flow regimes and what spot price did in each |

Each domain plugs into the same VIL tables, the same k-NN primitive, the same scoring engine. No new infrastructure per domain - the substrate compounds with every domain added and every bar processed. The older the system, the more valuable it becomes.

Full design: [`docs/ideas/vil-01-vector-intelligence-layer.md`](docs/ideas/vil-01-vector-intelligence-layer.md) through `vil-05`.

---

## API Layer: Intelligence as Output

The API is the product. Every signal, indicator value, regime classification, and AI narrative is immediately available over standard HTTP.

### REST Endpoints

| Endpoint | Returns |
|----------|---------|
| `GET /api/signals` | Signal history with full I1–I8 feature context |
| `GET /api/signals/recent` | Recent signals with setup performance JOIN |
| `GET /api/features` | Full I1–I8 feature vectors per bar, per symbol, per timeframe |
| `GET /api/market-data` | OHLCV history for any instrument/timeframe |
| `GET /api/instruments` | Active instrument list with contract metadata |
| `GET /api/drift` | Live KS + CUSUM drift state - pipeline confidence in its own signals |

### SSE Streams

Persistent HTTP connections. No polling. Events push as they happen.

| Stream | Pushes |
|--------|--------|
| `intelligence` | Full typed `IntelligenceEvent` per bar - complete I1–I8 payload |
| `signals` | Aggregated signals as they fire, with CIS score and constituent contributions |
| `signal_scorecard` | All ranked I7 candidates per bar - not just the winner |
| `narratives` | I8 LLM narrative text per signal |
| `ticks` | Live tick stream for price display |

Any HTTP client - a Python trading bot, a Jupyter notebook, an alert engine, a downstream product - connects to an SSE endpoint and receives the same intelligence the internal pipeline produces, in real time, with zero effect on pipeline throughput.

---

## Observability

All services push metrics via OTel to a central Collector, which exposes a Prometheus endpoint. Grafana dashboards cover pipeline throughput per symbol/TF, per-service P50/P95/P99 latency, signal generation and regime gate drop rates, LLM call success and fallback rates, per-plugin error rates.

Four visualization layers serve different audiences and time horizons:

| Layer | Tool | Purpose |
|-------|------|---------|
| **Operational** | Grafana + Prometheus | Pipeline health, latency, throughput, service status |
| **Market Intelligence** | Next.js dashboard (SSE) | Live signals, price panels, AI narratives, SMC context, signal scorecard |
| **Analytics** | Apache Superset (planned) | Signal outcome analysis, setup performance, regime patterns |
| **ML Observability** | Langfuse (self-hosted) | AI agent traces, prompt versions, model comparisons |

---

## Application Agents & Platform Extensibility

The same bus architecture that decouples intelligence domains from each other also decouples intelligence from application:

| Agent | Role | Attaches via |
|-------|------|-------------|
| **TradeAgent** | Directional execution, position sizing, order management | Subscribes to signal streams |
| **PortfolioAgent** | Capital allocation, Kelly sizing, performance attribution | Subscribes to execution events |
| **RiskAgent** | VaR, drawdown enforcement, margin monitoring, emergency halt | Subscribes to portfolio state; publishes binding halt instructions |

Risk enforcement is a stream subscriber - not a wrapper around execution code. Portfolio management is a stream subscriber - not a shared database. The bus is the architecture.

New domains attach the same way. The fundamental analysis engine subscribes to market data, publishes `fundamental:earnings`, `fundamental:sector_rotation`. The derivatives engine publishes `deriv:vol_regime`, `deriv:gex`. Downstream agents consume from whichever domains they need. Nothing already running changes.

---

## At a Glance

| | |
|---|---|
| **Intelligence tiers** | I1–I8 (indicators through AI synthesis) |
| **Plugins** | 129 + 2 aggregators across 8 tiers |
| **Data points** | ~729 distinct fields per bar per symbol per timeframe |
| **Instruments** | 60 - futures, ETFs, FX, crypto |
| **Latency** | <10ms bar-to-intelligence |
| **Data bus** | Redpanda (Kafka-compatible, sub-ms, durable, replayable) |
| **Persistence** | TimescaleDB (feature store, signal ledger, LLM audit) |
| **Services** | 25+ systemd microservices, DAG-orchestrated |
| **AI providers** | Ollama (local GPU), OpenRouter, Ollama Cloud - per-provider circuit breakers |
| **Stack** | Python · FastAPI · asyncpg · Next.js · Prometheus · Grafana |

**Current state:** Quantitative domain in production since early 2026. Vector Intelligence Layer (pgvector substrate, five-layer empirical stack) designed - the foundation for IC-measured prediction, independence-calibrated confidence, and domain extension. Fundamental, qualitative, and derivatives domains designed. Application agents architecturally defined. ML layer designed, awaiting data gate. eAI framework designed.

---

## Documentation

Docs in `docs/foundation/` and domain folders (`intelligence/`, `data/`, `signals/`, `agents/`, `platform/`) carry a verification contract: a document with `Status: current` has had every factual claim traced to a source file, table, or live system state at the date shown. A wrong claim is treated as corrupted data - downgraded to `draft` immediately. See [Documentation System](docs/foundation/documentation-system.md) for the full quality model.

### Foundation - verified, portable

| Document | Covers |
|----------|--------|
| [Principles](docs/foundation/principles.md) | The invariants behind every design decision |
| [Naming System](docs/foundation/naming-system.md) | Complete vocabulary: rings, taxonomy, surfaces, mechanical derivation rules |
| [Documentation System](docs/foundation/documentation-system.md) | Taxonomy, recipe-card format, verification lifecycle, decay model |

### Intelligence Domain - verified

| Document | Covers |
|----------|--------|
| [Intelligence Foundation](docs/intelligence/intelligence-foundation.md) | I1–I8 definitions, data flow philosophy, CIS bucket weights, adaptive weight systems |
| [Intelligence Plugins](docs/intelligence/intelligence-plugins.md) | Plugin protocol, 132-plugin inventory, how to add a plugin |
| [Intelligence AI](docs/intelligence/intelligence-ai.md) | Swarm agents, LLM chain, shadow governance, graduation criteria |
| [Intelligence Operations](docs/intelligence/intelligence-operations.md) | Services, monitoring, debugging the intelligence pipeline |

### Signals Domain - verified

| Document | Covers |
|----------|--------|
| [Signals Foundation](docs/signals/signals-foundation.md) | signal_ledger schema, full signal quality pipeline (alpha decay, calibration, CIS, ranking), feedback loops |
| [Signals Lifecycle](docs/signals/signals-lifecycle.md) | State machine, zone activation, 8-class outcome taxonomy, MAE/MFE tracking |
| [Signals Operations](docs/signals/signals-operations.md) | Debugging stalled signals, replay auditor, TTL expiry runbooks |

### Research & Planning - not authoritative

| Document | Covers |
|----------|--------|
| [ML Architecture](docs/ideas/ai-02-ml-agent-architecture.md) | ML layer design - 5 agents, LangGraph orchestration, promotion gates |
| [eAI Design](docs/ideas/ai-03-evolvable-ai-agents.md) | Evolvable AI framework - genome model, reproductive operators, fitness function |
| [VIL - Substrate](docs/ideas/vil-01-vector-intelligence-layer.md) | pgvector retrieval substrate - embed, label, retrieve; schema; serialization spec |
| [VIL - Feature IC](docs/ideas/vil-02-predictive-feature-intelligence.md) | Outcome Labeler, IC Factory, Analog Finder - what predicts price |
| [VIL - Scoring Engine](docs/ideas/vil-03-scoring-engine.md) | Analog set → Score Object; four resolution levels; conviction envelope |
| [VIL - Correlation](docs/ideas/vil-04-correlation-intelligence.md) | Effective-N; plugin/signal independence; redundancy suppression |
| [VIL - Signal Combiner](docs/ideas/vil-05-signal-combiner.md) | IC-weighted, decorrelated combination of the live edge set |
| [VIL - Platform Ideas](docs/ideas/vil-06-platform-ideas.md) | Regime discovery, lead-lag, hypothesis backtester, episodic memory |
| [DAG Execution](docs/concepts/dag-execution.md) | Service DAG topology and execution model |
| [Roadmap](.planning/ROADMAP.md) | Phase roadmap and current position |

### AI Assistant

- [CLAUDE.md](CLAUDE.md) - architecture, commands, conventions, gotchas
