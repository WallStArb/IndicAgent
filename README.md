# IndicAgent — Composable Market Intelligence Platform

**AI-first · API-first · Self-improving · Provider-agnostic**

> *Instrument everything · Signal with evidence · Learn from every outcome*

---

IndicAgent is a composable, AI-first market intelligence platform where multiple analysis domains feed multiple application agents — all connected through a unified streaming data bus.

The platform is built on one architectural bet: that intelligence, execution, and risk should be independent subscribers to a shared event stream — not coupled services calling each other. Every component is a microservice. Every interaction is an event. Every output is an API. New domains and new agents attach by subscribing and publishing — nothing already running changes.

**Multiple intelligence domains, one data spine:**

| Domain | Status | Scope |
|--------|--------|-------|
| **Quantitative** | In production | 8 tiers from raw indicators through regime classification to trading signals and AI synthesis |
| **Fundamental** | Designed | Earnings, macro data, COT positioning, sector rotation |
| **Qualitative** | Designed | News NLP, sentiment, prediction markets, macro regime narrative |
| **Derivatives** | Designed | Vol surface, gamma exposure, skew, options flow |

Each domain is an independent analysis engine that subscribes to market data streams and publishes its own intelligence events. They don't depend on each other to function. Downstream application agents — trade execution, portfolio management, risk management — consume from whichever domains they need, the same way: by subscribing to the bus.

The quantitative domain runs live on 60 instruments across futures, ETFs, FX, and crypto, transforming raw market data into evidence-graded trading signals in under 10ms. It's been in production since early 2026, accumulating its own labeled training data with every bar.

**The AI layer is independent and non-monolithic.** A multi-provider LLM chain (local Ollama, OpenRouter, DeepSeek) with per-provider circuit breakers means no single model or vendor is a dependency. Specialist agents perform analytical tasks — skeptic, correlation, volume analysis — while composite agents perform roles the way a trading desk would. An Evolvable AI (eAI) architecture is designed for agents that don't just learn from data, but evolve through Darwinian selection: mutation, recombination, and fitness-gated promotion, with statistical proof required at every generation.

**What makes this different from a signal pipeline:**

- **Self-improving** — CIS weights auto-refine from signal outcomes. ML models retrain on their own labeled data. Drift detection adjusts feature contributions in real time.
- **Self-healing** — services auto-restart in DAG order. A bar auditor detects and fills data gaps. A signal replay auditor resolves orphaned lifecycles.
- **Counterfactual recording** — every ranked candidate is recorded, not just winners. The system preserves the full decision boundary — what CIS selected and what it rejected — creating a training dataset that captures the rejections, not just the outcomes.
- **Full signal lifecycle** — signals tracked through zone activation to 8-class outcome resolution with MAE and MFE per signal. Portfolio-level risk analytics embedded in signal tracking, not a win/loss tally.
- **Statistical rigor throughout** — bootstrap confidence intervals for win rates, not point estimates. p < 0.05 promotion gates with minimum N. KS drift detection. CUSUM control charts. The system uses proof, not thresholds.
- **Provider-agnostic by design** — the intelligence pipeline has zero knowledge of where data comes from. It consumes typed events from the bus. Any real-time source plugs in the same way.
- **Full lineage and reproducibility** — every AI agent call tracked with prompt version, model, inputs, outputs, and timing. Every signal traces back through every transformation to raw data.
- **Evolvable** — eAI framework applies natural selection to AI agents. Genome mutation, sexual recombination, LLM-directed mutation. Fitness = accuracy × novelty × calibration × efficiency. Statistical gates at every lifecycle transition.
- **API-first** — every output immediately available over REST and SSE. Any HTTP client subscribes without pipeline changes.

---

## The Unified Data Bus

The central architectural decision: **services never call each other directly.** All communication flows through a durable, replayable event stream. Producers publish typed events; consumers subscribe to topics. A service going down means messages queue on the stream. On restart, it resumes from its committed offset — nothing lost, nothing re-requested. No service needs to know any other service exists.

This is what makes the microservices split real rather than cosmetic. In a conventional setup, services call each other via REST or gRPC — decoupled in name but coupled in operation. Here, the coupling is eliminated entirely. The bus is the only contract between producers and consumers, and that contract is a typed schema — `IntelligenceEvent`.

### Hot / Warm / Cold Data Tiers

```
Hot:  Market Data → Redpanda Streams → Services           (sub-ms ingestion)
Warm: Services → Intelligence Pipeline (I1–I8)            (<10ms extraction)
Cold: Writers → TimescaleDB (feature store, signal ledger) (async batch)
```

**Redpanda** (Kafka-compatible) on the hot path — sub-millisecond tick ingestion and stream fan-out to all downstream services. Raw market data enters here; every intelligence service reads from here. No database touches the hot path. Durable, partitioned, replayable logs — consumer groups ensure at-least-once delivery.

**The operational superpower: replay from offset 0.** A new consumer — a trading bot, ML model, alert engine, or downstream product — bootstraps by replaying the stream from the beginning. No data migration. No special onboarding. No pipeline changes. The history is already there.

### Zero Coupling Between Services

Each service has exactly one responsibility:

| Service | Owns |
|---------|------|
| Data Provider | Bar formation from high-frequency ticks (100–500+ ticks/sec), multi-timeframe aggregation |
| Intelligence Pipeline | Unified I1–I7 in-process computation — indicators, structure, regime, patterns, SMC, confluence, trading signals |
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

The service DAG runs in 10 layers. Dependencies are declared, not hardcoded — the execution engine derives order via topological sort at startup. Circular dependencies are detected and hard-crash before any live data flows.

```
L1   data-provider                                    — data ingestion
L2   provider-merger                                  — stream merge
L3   bar-aggregator, bar-auditor                      — bar processing
L4   bar-writer                                       — OHLCV persistence
L5   intelligence-pipeline, cross-asset, macro-compute — I1–I7 compute + context
L6   feature-writer, signal-writer, signal-tracker,
     lifecycle-writer, lineage-writer                  — persistence writers (parallel)
L7   alpha-swarm, llm-writer                          — AI/LLM layer
L8   roll-compute, signal-metrics, graduation-writer   — analytics + rolling metrics
L9   signal-auditor, parity-auditor, alerting-agent    — audit, parity, alerting
L10  service-auditor                                   — meta: monitors + restarts all above
```

A meta-service at L10 monitors all others, restarts in DAG order, and escalates after repeated failures. Each service is independently deployable, restartable, and observable — systemd-managed with Prometheus lag monitoring.

---

## Intelligence Pipeline: I1–I8

The quantitative domain processes data through 8 tiers. Each builds on the outputs of the tiers below it — no tier skips a level. A multi-timeframe aggregator rolls 1m bars forward to 5m, 15m, 1h, 4h, and 1d; each timeframe runs the full pipeline independently, giving every signal a multi-timeframe context.

### Layer 1: Data Foundation

A data provider daemon connects to a real-time market feed and forms 1m bars from high-frequency ticks. Bar-close events trigger the full I1–I8 pipeline. The provider is an implementation detail — the pipeline consumes typed events from the bus, not from any specific broker.

### Layer 2: Mathematical Intelligence

**I1 — Raw Indicators**

Incremental computation — each bar updates indicator state without recomputing history. RSI, MACD, Bollinger Bands, ATR, VWAP, Supertrend, Parabolic SAR, Stochastic RSI, Chaikin Money Flow, Aroon, SMA, EMA, OBV, ADX/DI, ROC, Awesome Oscillator, Accelerator Oscillator, Donchian Channels, CCI, Williams %R, MFI, Keltner Channels, Historical Volatility, Chandelier Exit, HMA, OFI, CVD. Every value published once per bar per symbol per timeframe.

**I2 — Composite Events**

Discrete events derived from I1 outputs. The standout plugins are second-derivative: **MomentumAcceleration** detects inflection points *before* they complete using rate-of-change on RSI, MACD, and ROC; **ExhaustionScore** composites volume, RSI extreme, reversal candlestick, and ATR spike to identify when a trend is running out of fuel — a leading indicator for regime transition.

**I3 — Market Structure**

Price action context above the indicator level: swing detection, S/R zones, Market Profile (volume distribution → POC, value area), Anchored VWAP, Fibonacci, session levels. **SwingMomentum** links live momentum readings directly to structural swing context — giving I5 divergence plugins a richer foundation.

**I4 — Regime Classification**

The statistical core. Six models answer distinct questions about market state:

| Model | Question | Output |
|-------|----------|--------|
| **GARCH** | Is volatility expanding or contracting? | Volatility regime (low/normal/elevated/extreme) + sigma estimate |
| **Kalman filter** | What is the true underlying trend, separate from noise? | Smooth trend slope — adapts to current signal-to-noise ratio |
| **HMM** | Which hidden market state is most probable? | Probability *distribution* over 3 states — not just an argmax |
| **BOCPD** | Is a new regime beginning right now? | Changepoint probability per bar — detects transitions before HMM confirms |
| **Hurst Exponent** | Is this market persistent or mean-reverting? | H-value + persistence class — gates signal direction vs. regime |
| **Shannon Entropy** | How predictable is the current price series? | Entropy score — feeds CIS quality multiplier |

### Layer 3: Pattern Intelligence

**I5 — Pattern Detection**

Discrete pattern recognition on the mathematical foundation: RSI divergence, volatility squeeze (Bollinger Bands inside Keltner Channels — compression that precedes expansion), chart patterns (H&S, double top/bottom, triangles, flags, cup and handle, measured move). All feed directly into I6 confluence scoring.

**I6 — Smart Money Concepts + Confluence**

Institutional order flow analysis — the interpretation of price action as the footprint of large participants:

- **BOS/CHoCH** — Break of Structure (trend continuation) vs. Change of Character (swing structure broken *against* the trend — the earliest structural reversal signal)
- **FVG** (Fair Value Gap) — 3-candle price imbalance where liquidity was left unfilled. Tracked by type, fill status, and freshness
- **BOCPD** — Bayesian Online Changepoint Detection. Detects the moment statistical properties shift in real time — before HMM confirms a new regime
- **Liquidity pools · Order blocks · ICT Killzones · AMD cycles** — complete institutional order flow model, aggregated across 6 timeframes into a single directional score

**I7 — Trading Setups**

Each plugin defines a trade thesis with entry, stop-loss, and take-profit logic: `TrendFollowing` · `MeanReversion` · `LiquiditySweepReclaim` · `SqueezeExpansion` · `VWAPDeviation` · `FVGFill` · `PatternCompletion` · `DivergenceStack` · `CHoCHReversal` · `OFIContinuation` · `OFIDivergence` · `CVDDivergence` · `CrossAssetDivergence` · `AnchoredVWAPReversion` · `POCRejection` · `ORB15` · `ORB30` · `VCP` — 36 setups in total.

When multiple setups fire on the same bar, the **CIS scorer** adjudicates (see below). Selected signals pass two gates:
1. **RR gate** — viable risk:reward based on zone quality and distance to target
2. **Regime gate** — HMM confidence threshold, regime stability, direction match. Direction mismatches are suppressed and recorded as shadow signals for counterfactual tracking

Quality gates on every signal:
- **Alpha decay** — confidence degrades over time. Modeled explicitly as a decay curve, not assumed constant
- **Freshness decay** — signal value drops as the bar context that generated it ages
- **Per-setup cooldown** — prevents the same setup firing repeatedly within the same regime window

### Layer 4: AI Intelligence

**I8 — AI Narrative & Synthesis**

For every signal above confidence 0.7, the AI Narrative Service generates a structured analysis of the full signal context — tier state, regime, SMC context, setup rationale, entry/stop/target. The LLM receives the full `IntelligenceEvent` payload, not a template. Beyond per-signal narratives: group synthesis at configurable intervals across 6 asset groups (equity indices, energy, metals, rates, FX, crypto).

The multi-provider LLM chain (local Ollama on AMD ROCm GPU, OpenRouter) runs with per-provider circuit breakers — no single model is a dependency. Every call logged to `llm_calls` for full audit. Outcomes are back-filled as signals resolve, linking every LLM call to its eventual result.

### Data Points Tracked

The pipeline tracks **~729 distinct data points** across **129 plugins + 2 aggregators**, from raw math through AI synthesis. Every bar for every instrument on every timeframe produces this full feature vector.

| Tier | Plugins | Data Points | What It Measures |
|------|---------|-------------|-----------------|
| **I1** Raw Indicators | 28 | ~50 | Price, momentum, volatility, volume math — RSI, MACD, ATR, Bollinger, VWAP, OFI, CVD, etc. |
| **I2** Composite Events | 10 | ~20 | Discrete events from I1 — crossovers, threshold breaches, momentum acceleration, exhaustion scoring |
| **I3** Market Structure | 8 | ~77 | Price geometry — swing points, S/R zones, market profile (POC/VA), session levels, Fibonacci zones |
| **I4** Regime Context | 12 | ~93 | Statistical state — GARCH vol forecast, Kalman trend, HMM regime probabilities, Hurst persistence, Shannon entropy, volume profile |
| **I5** Patterns | 16 | ~91 | Discrete patterns — RSI/MACD/CMF divergence, squeeze detection, chart patterns (H&S, triangles, flags, cup & handle) |
| **SMC** Smart Money | 13 | ~89 | Institutional footprint — BOS/CHoCH, fair value gaps, order blocks, liquidity pools, BOCPD changepoints, AMD cycles |
| **I6** Confluence | 6 | ~26 | Cross-timeframe alignment — trend, structure, regime, momentum, orderflow, squeeze agreement across 4 timeframes |
| **I7** Trading Signals | 36 + 2 agg | ~283 | Actionable setups — entry/stop/target, confidence scoring, feature snapshots, CIS bucket breakdown, regime gate metadata |
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

CIS fires only when `|score| > 0.35` **and** at least 3 of 6 buckets agree on direction. A single dominant bucket cannot override the rest — cross-tier confirmation is structurally required.

Each bucket returns `(score, contribution)` — not just the aggregate. The breakdown is logged per signal and exposed via the API. You can see exactly which buckets drove a CIS election and by how much.

### The Learning Loop

Every CIS result is tagged with a `weights_version`. Every signal lifecycle outcome pairs the full CIS bucket vector at signal time with its eventual outcome. All ranked candidates — not just winners — are recorded, giving a complete view of the decision boundary including the counterfactuals CIS rejected.

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

## Self-Correcting Pipeline

The pipeline monitors its own signal quality and self-adjusts at six independent layers — no manual recalibration required.

```
Raw confidence (I7 plugin output)
    → [1] Isotonic calibration    → calibrated_confidence
    → [2] TOD multiplier          → time-adjusted confidence
    → [3] perf_multiplier         → performance-weighted rank
    → [4] KS drift penalty        → distribution-aware CIS bucket weights
    → [5] CUSUM monitor           → feedback loop back into perf_multiplier
    → [6] Shadow mode gate        → statistical proof before production eligibility
```

**[1] Isotonic Calibration** — raw confidence values are systematically biased. Isotonic regression maps them to empirically calibrated values using historical outcome data. Raw value stored alongside calibrated value for audit.

**[2] Time-of-Day Multiplier** — signal quality varies by session and regime. A trend setup at RTH open behaves differently than the same setup at 2pm. Per cell: `(regime_type, timeframe, hour_et)` — 120 cells total.

**[3] Performance Multiplier** — rolling 30-day Sharpe and win rate per setup per regime. Gate: setups with N < 30 use `perf_multiplier = 1.0` — no effect until statistically proven.

**[4] KS Drift Monitor** — Kolmogorov-Smirnov test compares current feature distributions against historical baseline. When a feature drifts significantly, its CIS contribution is penalized. The signal doesn't disappear — it gets discounted proportionally to how far out-of-distribution it is.

**[5] CUSUM Performance Monitor** — cumulative sum control charts track win rate per setup. When cumulative performance crosses the degradation threshold, `perf_multiplier` is automatically reduced. Recovery restores it. The loop closes itself.

**[6] Shadow Mode Gate** — every new feature or plugin runs in shadow mode before production. Shadow signals are generated, tracked through full lifecycle, and scored — but never published live. Promotion requires p < 0.05 AND N ≥ 100 resolved signals. `shadow_promotion_ready` Prometheus gauge signals when gate conditions are met.

---

## Signal Lifecycle

Every signal is tracked through its complete lifecycle — not fired and forgotten.

**Zone-based activation.** Signals define entry zones (proximal, distal) rather than single price levels. The tracker monitors price relative to these zones and records `zone_entry_pct` — how deep into the zone price penetrated before activating or expiring. This provides granular data on entry quality that a simple "price crossed X" model cannot.

**MAE and MFE per signal.** Maximum Adverse Excursion and Maximum Favorable Excursion are tracked from activation through exit. These are portfolio-level risk analytics embedded directly in signal tracking — the basis for optimal stop and target placement in position sizing.

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

**Counterfactual recording.** All ranked candidates — not just winners — are written to `signal_ledger`. The system records the full I1–I8 feature vector, the CIS bucket breakdown, and the eventual outcome for every signal the pipeline considered. This is the decision boundary: the dataset tells the ML model not just what worked, but what *almost* worked and what was correctly rejected.

**Signal schema versioning.** A `signal_schema_version` column distinguishes signal generations. ML training queries filter to the current schema version — contaminated data from earlier pipeline versions is excluded by construction.

---

## The AI Swarm & Evolvable Intelligence

### Specialist Agents and Composite Agents

The AI layer is organized the way a trading desk is organized: **specialist agents perform tasks, composite agents perform roles.**

A skeptic agent challenges every signal. A correlation agent checks whether the signal is genuinely independent or a restating of existing positions. A volume agent analyzes whether order flow confirms or contradicts the setup. These are specialists — focused, fast, replaceable.

Composite agents orchestrate multiple specialists into a coherent view — the same way a senior trader synthesizes input from a technical analyst, a risk manager, and a flow trader. The output isn't a single model's opinion; it's a structured multi-perspective assessment with dissent recorded.

Every agent call is traced. A `LineageRecorder` tracks prompt version, model, inputs, outputs, and timing per call. Full reproducibility — you can reconstruct why any agent made any decision at any point in history.

### Evolvable AI (eAI) — Agents That Evolve

Beyond learning from data, the platform is designed for agents that evolve through Darwinian selection. Inspired by research in evolvable AI (PNAS 2025) and Renaissance Technologies' approach to model management.

Three epochs of AI:

1. **Intelligence by design** — handcrafted rules, logic, expert systems
2. **Intelligence by learning** — training on data, gradient descent, RLHF
3. **Intelligence by evolution** — agents that improve their own capacity for improvement

Markets are non-stationary. Manual agent design produces agents that reflect current mental models. An evolutionary system discovers edges that exist beyond those models.

**The agent genome** — each agent's "DNA" is a composite of independently heritable components:

| Chromosome | What evolves |
|------------|-------------|
| System prompts | Reasoning strategy, analytical frame, chain-of-thought structure |
| Configuration parameters | Thresholds, timeframe weights, scoring coefficients |
| Tool sets | Which data sources and analysis tools the agent can access |
| Model adapters | Fine-tuned weights for task-specific specialization |
| Guardrails | Constraints and behavioral boundaries |

**Three reproductive operators:**

- **Mutation** — blind perturbation of genome components. Exploration. Escape local optima.
- **Recombination** — two fit parents contribute genome segments via crossover. Prompt from parent A + config from parent B + tool set blend. Novel combinations neither parent could produce alone.
- **LLM-directed mutation** — an LLM analyzes a parent's genome and performance, then proposes targeted improvements. Directed search with access to the full corpus of trading research as its gene pool. The most powerful operator, reserved for high-fitness parents.

**Lifecycle: birth → shadow incubation → breeding → promotion → live.**

Every newborn agent enters shadow mode — observing live data, producing analysis, zero production impact. Fitness is measured out-of-sample across multiple regimes. The system tracks which reproductive operator produces the fittest offspring and dynamically shifts budget toward better operators — meta-optimization of the search itself.

**Composite fitness = accuracy × novelty × calibration × regime specificity × efficiency.**

An agent that's right for the wrong reasons, or that duplicates an existing agent's edge, doesn't promote. The statistical gate: bootstrap CI > 0 at 95% confidence. Unique, calibrated, regime-aware alpha — nothing less clears the gate.

Promotion requires both automated gates (sustained fitness across ≥ 3 regimes, stability, novelty) and human review — the *why* matters, not just the *what*. On promotion, full genome + ancestry chain is recorded permanently, traceable to generation 0.

---

## Machine Learning Layer (MLAgent)

> The feature store and signal ledger are already accumulating the labeled training data this consumes.

The ML layer closes the learning loop at the model level — replacing hand-tuned weights with a full ensemble trained on labeled signal outcomes. Five agents, orchestrated by LangGraph:

| Agent | Role |
|-------|------|
| **Orchestrator** | Routes work, decides retrain / promote / escalate based on monitoring signals |
| **Data Quality Agent** | Validates training data integrity before any model runs |
| **Discovery Agent** | tsfresh feature extraction, Pearson IC analysis, regime-conditional IC, cross-asset lag correlation |
| **Training Agent** | LightGBM ensemble per segment (regime × setup × TF), time-series CV, shadow mode gate |
| **Monitoring Agent** | Evidently drift detection (KS/PSI/Wasserstein), CUSUM degradation, circuit breaker |

No model reaches production without p < 0.05 with sufficient N. Borderline p-values pause the graph and require human approval — a dashboard alert presents the full model comparison; 4-hour timeout defaults to reject.

**The dataset — already accumulating:**

| Table | Stores | ML role |
|-------|--------|---------|
| `intelligence_features` | Full I1–I8 feature vector per bar (tiered JSONB) | Training inputs |
| `signal_ledger` | Signal + 8-class lifecycle outcome, MAE, MFE, bars-in-trade | Training targets |
| `llm_calls` | Every LLM invocation with back-filled signal outcome | LLM model scoring |
| `signal_metrics` | Per-setup rolling 30d win rate, avg P&L R, Sharpe per regime | Performance baseline |
| `cis_weights` | Adaptive bucket weights, versioned | Model deployment output |

Every bar the pipeline processes adds a row to `intelligence_features`. Every signal that resolves adds an outcome row to `signal_ledger`. The ML layer consumes this dataset — the platform has been building it since day one.

**ML stack:** `langgraph` + `langchain` · `langfuse` (self-hosted observability) · `guardrails-ai` (LLM output validation) · `scipy` + `tsfresh` (700+ statistical features) · `evidently` (drift detection) · `polars` (Rust dataframes) · `lightgbm` (tabular champion) · `shap` (TreeSHAP explainability) · `optuna` (Bayesian hyperparameter optimization) · `mlflow` (model registry) · `river` (online/incremental learning).

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
| `GET /api/drift` | Live KS + CUSUM drift state — pipeline confidence in its own signals |

### SSE Streams

Persistent HTTP connections. No polling. Events push as they happen.

| Stream | Pushes |
|--------|--------|
| `intelligence` | Full typed `IntelligenceEvent` per bar — complete I1–I8 payload |
| `signals` | Aggregated signals as they fire, with CIS score and constituent contributions |
| `signal_scorecard` | All ranked I7 candidates per bar — not just the winner |
| `narratives` | I8 LLM narrative text per signal |
| `ticks` | Live tick stream for price display |

Any HTTP client — a Python trading bot, a Jupyter notebook, an alert engine, a downstream product — connects to an SSE endpoint and receives the same intelligence the internal pipeline produces, in real time, with zero effect on pipeline throughput.

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

Risk enforcement is a stream subscriber — not a wrapper around execution code. Portfolio management is a stream subscriber — not a shared database. The bus is the architecture.

New domains attach the same way. The fundamental analysis engine subscribes to market data, publishes `fundamental:earnings`, `fundamental:sector_rotation`. The derivatives engine publishes `deriv:vol_regime`, `deriv:gex`. Downstream agents consume from whichever domains they need. Nothing already running changes.

---

## At a Glance

| | |
|---|---|
| **Intelligence tiers** | I1–I8 (indicators through AI synthesis) |
| **Plugins** | 129 + 2 aggregators across 8 tiers |
| **Data points** | ~729 distinct fields per bar per symbol per timeframe |
| **Instruments** | 60 — futures, ETFs, FX, crypto |
| **Latency** | <10ms bar-to-intelligence |
| **Data bus** | Redpanda (Kafka-compatible, sub-ms, durable, replayable) |
| **Persistence** | TimescaleDB (feature store, signal ledger, LLM audit) |
| **Services** | 25+ systemd microservices, DAG-orchestrated |
| **AI providers** | Ollama (local GPU), OpenRouter, Ollama Cloud — per-provider circuit breakers |
| **Stack** | Python · FastAPI · asyncpg · Next.js · Prometheus · Grafana |

**Current state:** Quantitative domain in production since early 2026. Fundamental, qualitative, and derivatives domains designed. Application agents architecturally defined. ML layer designed, awaiting data gate. eAI framework designed.

---

## Documentation

Docs in `docs/foundation/` and domain folders (`intelligence/`, `data/`, `signals/`, `agents/`, `platform/`) carry a verification contract: a document with `Status: current` has had every factual claim traced to a source file, table, or live system state at the date shown. A wrong claim is treated as corrupted data — downgraded to `draft` immediately. See [Documentation System](docs/foundation/documentation-system.md) for the full quality model.

### Foundation — verified, portable

| Document | Covers |
|----------|--------|
| [Principles](docs/foundation/principles.md) | The invariants behind every design decision |
| [Naming System](docs/foundation/naming-system.md) | Complete vocabulary: rings, taxonomy, surfaces, mechanical derivation rules |
| [Documentation System](docs/foundation/documentation-system.md) | Taxonomy, recipe-card format, verification lifecycle, decay model |

### Intelligence Domain — verified

| Document | Covers |
|----------|--------|
| [Intelligence Foundation](docs/intelligence/intelligence-foundation.md) | I1–I8 definitions, data flow philosophy, tier contracts |
| [Intelligence Plugins](docs/intelligence/intelligence-plugins.md) | Plugin protocol, 132-plugin inventory, how to add a plugin |
| [Intelligence AI](docs/intelligence/intelligence-ai.md) | Swarm agents, LLM chain, shadow governance, graduation criteria |
| [Intelligence Operations](docs/intelligence/intelligence-operations.md) | Services, monitoring, debugging the intelligence pipeline |

### Research & Planning — not authoritative

| Document | Covers |
|----------|--------|
| [ML Architecture](docs/ideas/ai-02-ml-agent-architecture.md) | ML layer design — 5 agents, LangGraph orchestration, promotion gates |
| [eAI Design](docs/ideas/ai-03-evolvable-ai-agents.md) | Evolvable AI framework — genome model, reproductive operators, fitness function |
| [DAG Execution](docs/concepts/dag-execution.md) | Service DAG topology and execution model |
| [Roadmap](.planning/ROADMAP.md) | Phase roadmap and current position |

### AI Assistant

- [CLAUDE.md](CLAUDE.md) — architecture, commands, conventions, gotchas
