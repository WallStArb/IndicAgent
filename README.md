# IndicAgent Market Intelligence Platform

**v2.0 · 123 plugins · 2641 tests · 60 instruments · <10ms end-to-end**

> *Instrument everything · Signal with evidence · Learn from every outcome*

---

**IndicAgent is a high-frequency, institutional-grade market intelligence platform engineered with the architectural rigor of a top-tier quantitative hedge fund.** We apply rigorous engineering principles—event-driven microservices, dependency-aware DAG orchestration, and sub-millisecond hot-path isolation—to transform raw market data into evidence-graded trading signals. 

IndicAgent takes raw tick data from any real-time source and produces evidence-graded trading signals — regime-classified, institutionally contextualized, AI-narrated, and drift-corrected — in under 10ms. 123+ plugins execute in dependency order across 8 intelligence tiers. Every output is published to a durable, replayable event stream, allowing any HTTP client to subscribe to live intelligence over SSE or pull via REST without pipeline changes.

Signals don't fire on a single indicator. Our CIS (Confluence Intelligence Score) requires cross-tier agreement from at least 3 of 6 independent evidence buckets; regime conflicts veto, and signals lose confidence explicitly as they age. Every winner and every rejected counterfactual lands in the feature store with its full I1–I8 context, ensuring the system accumulates its own high-fidelity labeled training dataset with every bar it processes.

Designed for resilience, reproducibility, and massive scale, our pipeline processes 123+ plugins across 8 intelligence tiers, building its own labeled training datasets in real-time. Every signal is multi-bucket adjudicated, regime-aware, and AI-synthesized, delivering actionable intelligence with institutional-grade transparency and self-correcting statistical integrity.

IndicAgent enables you to build institutional-grade intelligence that is as self-correcting as it is transparent.

---

---

## Design Principles

Our platform is built on 8 foundational principles that ensure institutional-grade reliability, modularity, and operational simplicity.

**→ [Read the full Foundational Principles](docs/architecture/principles.md)**

| Principle | Summary |
| :--- | :--- |
| **Plugin-Native Shell** | Modular intelligence: the system is an empty container for self-describing plugins. |
| **Event-Driven Microservices** | No direct service calls; all communication is via durable, replayable Redpanda streams. |
| **Hot Path Isolation** | Real-time pipelines never touch the DB directly; persistence is fully async. |
| **Topological Orchestration** | Plugin dependencies are declared; execution order is derived automatically (DAG). |
| **Incremental-First** | $O(1)$ computation per bar via `compute_next()` for sub-ms execution. |
| **Data Contracts Over APIs** | Typed schemas (`IntelligenceEvent`) are the only contract; logic is opaque. |
| **Institutional Rigor** | Evidence-graded signals require multi-bucket (CIS) consensus. |
| **Self-Correcting Pipeline** | Live drift detection and CUSUM feedback loops ensure continuous integrity. |

---

## The Unified Data Bus

The central architectural decision: **event-driven microservices over a shared stream. Services never call each other directly.**

This is what makes the microservices split real rather than cosmetic. In a conventional microservices setup, services still call each other via REST or gRPC — they are decoupled in name but coupled in operation: if service B is down, service A fails. Here, the coupling is eliminated entirely. Services are producers and consumers on a durable event stream. A service going down means messages queue on the stream. When it restarts, it resumes from its committed offset — nothing lost, nothing re-requested. No service needs to know any other service exists.

The unified data bus is the data spine of the platform — the single structure everything attaches to and everything flows through. Every tick ingested, every indicator computed, every regime classified, every signal fired, every AI narrative generated: all of it moves as messages on the bus. No service calls another. No shared database in the hot path. The bus is the only contract between producers and consumers, and that contract is a typed schema.

**Redpanda** (Kafka-compatible) on the hot path — sub-millisecond tick ingestion and stream fan-out to all downstream services. Raw market data enters here; every intelligence service reads from here. No database touches the hot path. Durable, partitioned, replayable logs — consumer groups ensure at-least-once delivery: if a service disconnects, messages queue. On reconnect, it resumes from its committed offset — nothing lost, nothing skipped.

### Replay from offset 0

The most operationally powerful property of this architecture: **a new consumer gets the full intelligence history on day one.** A trading bot, ML model, alert engine, or downstream product bootstraps by replaying the stream from the beginning. No data migration. No special onboarding. No pipeline changes. The history is already there.

### Zero coupling between services — Separation of Concerns in practice

This is Separation of Concerns (SoC) as an architectural invariant, not a coding guideline. Each service has exactly one responsibility:

| Service | Owns |
|---------|------|
| TWS Daemon | Data collection from market feed |
| Feature Pipeline | I1–I6 unified in-process computation — indicators, structure, regime, patterns, SMC, confluence |
| Signal Generator | I7 setup detection and CIS adjudication |
| Signal Lifecycle | Open trade tracking, MAE/MFE, outcome classification |
| Feature Writer | Persistence of intelligence vectors to TimescaleDB |
| LLM Writer | LLM call audit trail with outcome back-fill |
| AI Narrative | I8 LLM analysis and group synthesis |
| API | SSE fan-out and REST delivery to clients |

Producers publish. Consumers subscribe. No service knows the others exist.

Restart `feature_pipeline_service` to deploy a new plugin: zero effect on `signal_lifecycle_service` tracking open trades. The AI narrative service falls behind under load: indicator calculation is unaffected. A new consumer subscribes to the `intelligence:SYMBOL:TF` stream: existing producers don't change a line.

```
IBKR TWS ──► [Redpanda topics] ──► feature_pipeline_service (I1–I6)
                                    ──► signal_generator_service (I7) ──► signal_lifecycle_service
                                    ──► feature_writer_service
                                    ──► ai_narrative_service (I8)
                                    ──► api_service ──► SSE ──► any HTTP client
```

Each arrow is a Redpanda topic. The topics are the API between services.

### Stream keys

Every stream is namespaced and typed:

| Stream | Carries |
|--------|---------|
| `intelligence:SYMBOL:TF` | Full typed `IntelligenceEvent` (I1–I8 payload) — single canonical bus |
| `intelligence_i7:SYMBOL:TF` | I7 signal scorecard (all ranked candidates per bar) |
| `signals:SYMBOL:TF:aggregated` | Selected I7 signal with CIS score + ranked candidates |
| `narratives:SYMBOL:TF` | I8 AI narrative text |
| `llm_calls:stream` | Every LLM invocation (success, failure, counterfactual) |
| `llm_outcomes:stream` | Signal lifecycle exits with outcome, P&L R, MAE, MFE |
| `cross_asset` | Cross-asset spread dynamics (EQ index group) |

---

## The Plugin System

### 121 plugins in a dependency DAG

Every output in the pipeline is produced by a plugin. Plugins are stateless workers that read from the typed bus and write back to it. The dependency graph is declared, not hardcoded: each plugin specifies what it reads, and the DAG engine derives execution order automatically at startup using topological sort.

This means:
- **RSI always completes before RSI Divergence reads it.** Guaranteed by the graph, not by convention.
- **Circular dependencies are impossible to ship.** The engine detects them at startup and hard-crashes before any live data flows.
- **Adding a plugin means declaring its inputs.** Ordering is inferred. No execution order file to maintain.

```
Raw OHLCV
  └─► I1 Indicators (25 plugins, no dependencies)
        └─► I2 Composite Events (depend on I1)
  └─► I3 Structure (reads OHLCV directly)
        └─► I4 Context / Regime (reads I3 + OHLCV)
  └─► I5 Patterns (reads I1 features)
  └─► I6 SMC + Confluence (reads I1–I5, cross-timeframe)
        └─► I7 Setups (reads I2–I6, regime-gated)
              └─► I8 AI Narrative (reads I7 signals)
```

### Plugin count by tier


### Plugin Validation Layer

Comprehensive validation runs at service startup to ensure system integrity before processing any data.

**Location:** `src/core/plugin_validator.py`

**Validations:**

- Tier list registration — all `TIER_*` plugins must be in registry
- Required attributes — I7 plugins must have `regime_type` attribute; all plugins need `name`, `outputs`, `inputs`
- Schema coverage — verifies all plugin outputs are covered by `IntelligenceEvent` schema
- Orphaned plugins — detects imported plugin modules with missing `.py` files
- TREND_SETUPS sync — ensures hardcoded trend setups match TIER_I7 plugins with `regime_type="trend"`

**Integration:** Called at startup of `feature_pipeline_service` and `signal_generator_service` before each service begins processing.

**Error handling:** Raises `RuntimeError` with `sys.exit(1)` if any validation fails, preventing services from starting with misconfigured plugins.

| Tier | Count | Role |
|------|-------|------|
| I1 | 27 | Raw technical indicators — RSI, MACD, ATR, VWAP, ADX, Supertrend, HMA, OFI, CVD, and 18 more |
| I2 | 11 | Discrete events derived from I1 — crossovers, threshold crossings, volume surges, momentum acceleration |
| I3 | 7 | Market structure — swing detection, S/R zones, Market Profile, Fibonacci, session levels |
| I4 | 11 | Regime classification — GARCH, Kalman filter, HMM, BOCPD, Hurst Exponent, Shannon Entropy, Volume Profile, Anchored VWAP, and more |
| I5 | 15 | Pattern detection — RSI divergence, squeeze, chart patterns, trend confluence, key level reactions |
| I6 SMC | 13 | Smart Money Concepts — BOS/CHoCH, FVG, order blocks, liquidity pools, ICT killzones, AMD cycles, BOCPD |
| I6 confluence | 1 | Cross-timeframe SMC synthesis |
| I7 setups | 36 | Trading setups — entry, stop, target logic; CIS-gated; includes OFI/CVD microstructure and cross-asset divergence |
| Aggregation | 2 | CIS scorer + signal aggregator |

→ [DAG Execution](docs/concepts/dag-execution.md)

---

## Intelligence Pipeline: I1–I8

The pipeline is organized as four layers. Each tier builds on the outputs of the tiers below it — no tier skips a level.

### Layer 1: Data Foundation

A daemon connects to IBKR TWS and forms **1m bars from high-frequency ticks** (100–500+ ticks/sec). These bar-close events trigger the full I1–I8 pipeline. A multi-timeframe aggregator rolls 1m bars forward to 5m, 15m, 1h, 4h, and 1d — each timeframe runs the full pipeline independently, giving every signal a multi-timeframe context. Real-time tick streams feed price display separately.

### Layer 2: Mathematical Intelligence

**I1 — Raw Indicators (25 plugins)**

Incremental computation — each bar updates indicator state without recomputing history. RSI, MACD, Bollinger Bands, ATR, VWAP, Supertrend, Parabolic SAR, Stochastic RSI, Chaikin Money Flow, Aroon, SMA, EMA, OBV, ADX/DI, ROC, Awesome Oscillator, Accelerator Oscillator, Donchian Channels, CCI, Williams %R, MFI, Keltner Channels, Historical Volatility, Chandelier Exit, HMA. Every value published once per bar per symbol per timeframe.

**I2 — Composite Events (11 plugins)**

Discrete events derived from I1 outputs — crossovers, threshold crossings, volume surges. The standout plugins here are second-derivative: **MomentumAcceleration** detects inflection points *before* they complete using rate-of-change on RSI, MACD, and ROC; **ExhaustionScore** composites volume, RSI extreme, reversal candlestick, and ATR spike to identify when a trend is running out of fuel — a leading indicator for regime transition.

**I3 — Market Structure (8 plugins)**

Price action context above the indicator level: swing detection, S/R zones, Market Profile (volume distribution → POC, value area), Anchored VWAP, Fibonacci, session levels. **SwingMomentum** links live momentum readings directly to structural swing context — giving I5 divergence plugins a richer foundation to confirm or reject.

**I4 — Regime Classification (7 plugins)**

The statistical core. Six models answer distinct questions about market state — see the [regime model stack](#the-regime-model-stack) below for the full breakdown. The two v1.8 additions are the most distinctive:

- **Hurst Exponent** — quantifies regime *persistence*. H > 0.6 = trending market; H < 0.4 = mean-reverting. Signals running against their persistence class are filtered before reaching I7.
- **Shannon Entropy** — quantifies market *predictability* from an information-theoretic standpoint. High entropy = noisy, low-conviction environment. Feeds a quality multiplier into CIS ranking that discounts signals generated when the market is least predictable.

### Layer 3: Pattern Intelligence

**I5 — Pattern Detection (14 plugins)**

Discrete pattern recognition on the mathematical foundation: RSI divergence (price and RSI diverging — a leading reversal signal), volatility squeeze (Bollinger Bands inside Keltner Channels — compression that precedes expansion), and completed chart patterns (H&S, double top/bottom, triangles, flags, cup and handle, measured move). All 14 feed directly into I6 confluence scoring.

**I6 SMC — Smart Money Concepts (13 plugins + 1 confluence aggregator)**

Institutional order flow analysis — the interpretation of price action as the footprint of large participants. The most analytically significant plugins:

- **BOS/CHoCH** — Break of Structure (trend continuation confirmed) vs. Change of Character (swing structure broken *against* the trend — the earliest structural reversal signal in the pipeline)
- **FVG** (Fair Value Gap) — a 3-candle price imbalance where liquidity was left unfilled. Tracked by type, fill status, and freshness; price has a measurable tendency to return and fill them
- **BOCPD** (Bayesian Online Changepoint Detection) — detects the moment the *statistical properties* of the price series shift, in real time and without hindsight. Unlike HMM which classifies into known states, BOCPD detects the transition event itself — before a new regime is confirmed
- **Liquidity pools · Order blocks · ICT Killzones · AMD cycles** — complete institutional order flow model; cross-timeframe confluence aggregates all 6 timeframes into a single directional score

**I7 — Trading Setups (17 plugins + CIS aggregator)**

Each plugin defines a trade thesis with entry, stop-loss, and take-profit logic:

`TrendFollowing` · `MeanReversion` · `LiquiditySweepReclaim` · `MTFAlignment` · `SqueezeExpansion` · `VWAPDeviation` · `MomentumBreakout` · `LiquidityHunt` · `SupplyDemandSetup` · `CHoCHReversal` · `FVGFill` · `PatternCompletion` · `DivergenceStack` · `RegimeTransition` · `GapAnalysisSetup` · `CandlestickPatternSetup` · `SessionExtremesSetup`

When multiple setups fire on the same bar, the **CIS scorer** selects the winner (see below). The selected signal passes two gates before reaching the bus:

1. **RR gate** — viable risk:reward based on zone quality and distance to target. Fails → dropped.
2. **Regime gate** — HMM confidence ≥ 0.55, regime stable ≥ 3 bars. Direction mismatch → dropped.

All ranked candidates — winner and counterfactuals — are written to `signal_ledger` as labeled training data.

**Renaissance quality gates — I7 (v1.8):**

- **Alpha decay** — signal confidence degrades over time after firing. A signal 10 bars old carries less weight than one 2 bars old. Modeled explicitly as a decay curve, not assumed constant.
- **Freshness decay** — separate from alpha decay: signal value drops as the bar context that generated it ages. Both decay curves are logged per signal.
- **Per-setup cooldown gate** — prevents the same setup firing repeatedly within the same regime window. Statistically justified deduplication, not a simple timer.

### Layer 4: AI Intelligence

**I8 — AI Narrative (LLM chain)**

For every signal above confidence 0.7 (on 5m, 15m, 1h timeframes), the AI Narrative Service generates a structured natural language analysis of the full signal context — tier state, regime, SMC context, setup rationale, entry/stop/target. The LLM receives the full `IntelligenceEvent` payload, not a template.

Beyond per-signal narratives: group synthesis at configurable intervals across 6 asset groups (equity indices, energy, metals, rates, FX, crypto).

LLM chain (priority order): **OpenRouter** (primary, free models, 100+ model catalogue) → **Ollama local** (qwen3.5:9b, offline, AMD ROCm GPU). Every call — successful and failed — is logged to `llm_calls` for full audit. `llm_writer_service` back-fills signal outcomes into `llm_calls` rows as they resolve, linking every LLM call to its eventual outcome.

---

## The CIS Aggregator

The Composite Intelligence Score is the decision engine. When 5–8 setup plugins fire simultaneously on the same bar, CIS adjudicates by aggregating evidence from the *entire* pipeline into a single directional score.

### Six evidence buckets

| Bucket | Reads from | Weight |
|--------|-----------|--------|
| **Trend** | Kalman slope, trend regime, SMC trend, cross-TF alignment | 0.20 |
| **Momentum** | RSI deviation, MACD histogram, ROC, momentum bias | 0.20 |
| **Structure** | Swing pattern, BOS/CHoCH events, CHoCHReversal | 0.15 |
| **Pattern** | Double top/bottom, H&S, triangle completions | 0.05 |
| **Institutional** | Order blocks, FVG activity, supply/demand zones | 0.25 |
| **Regime** | HMM state probabilities, BOCPD changepoint, vol regime | 0.15 |

CIS fires only when `|score| > 0.35` **and** at least 3 of 6 buckets agree on direction. A single dominant bucket cannot override the rest — cross-tier confirmation is structurally required.

### Constituent contributions (v1.8)

Each of the 6 buckets now returns `(score, contribution)` — not just the aggregate. The breakdown is logged per signal and exposed via the API. You can see exactly which buckets drove a CIS election and by how much — full transparency into every signal decision.

### The learning loop

Every CIS result is tagged with a `weights_version`. Every signal lifecycle outcome lands in `signal_ledger` as a labeled row, pairing the full CIS bucket vector at signal time with its eventual outcome. All ranked candidates — not just winners — are recorded, giving a complete view of the decision boundary including the counterfactuals CIS rejected.

The learning path: logistic regression on this dataset fits per-bucket weights that maximize outcome prediction. When updated weights are present, the scorer loads them at startup. CIS improves without code changes.

```
Signal fires → CIS tags result with weights_version=N
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

→ [CIS Scoring](docs/concepts/cis-scoring.md)

---

## Drift Detection & Self-Correction

> *The pipeline monitors its own signal quality and self-adjusts while live.*

This is one of the harder properties to build into a production intelligence system, and one of the most important. Signals that were valid under last month's market regime may be noise in this one. The platform detects this automatically — no manual recalibration required.

### KS Drift Monitor

A **Kolmogorov-Smirnov test** runs continuously against the feature distributions stored in the `drift_monitor` hypertable. When the current feature distribution for a given setup drifts significantly from its historical baseline, a penalty is applied **directly into CIS scoring** for that setup. The signal doesn't disappear — it gets discounted proportionally to how far out-of-distribution its feature context is.

### CUSUM Performance Monitor

**Cumulative Sum (CUSUM)** control charts track whether signal performance is degrading over time. When the CUSUM statistic exceeds threshold, `perf_multiplier` — the performance weight applied to ranked signals — is **auto-adjusted without code changes and logged**. The system corrects for performance drift as it happens.

### Drift API

```
GET /api/drift    →  current KS + CUSUM state per symbol/timeframe, externally observable
```

Drift state is not internal telemetry — it's a first-class API endpoint. Any external consumer can observe the pipeline's current confidence in its own signals.

---

## API Layer: Intelligence as Output

The API is the product. Every signal, indicator value, regime classification, and AI narrative the pipeline produces is immediately available over standard HTTP — REST for pull-based access, SSE for real-time push.

### REST endpoints

| Endpoint | Returns |
|----------|---------|
| `GET /api/signals` | Signal history with optional full I1–I8 feature context at signal time |
| `GET /api/signals/recent` | Recent signals with setup performance JOIN (win rate, avg P&L R, sample size) |
| `GET /api/features` | Full I1–I8 feature vectors per bar, per symbol, per timeframe |
| `GET /api/market-data` | OHLCV history for any instrument/timeframe |
| `GET /api/instruments` | Active instrument list with contract metadata |
| `GET /api/drift` | Live KS + CUSUM drift state — pipeline confidence in its own signals |
| `GET /indicators/available` | All 103 plugins and their tier assignments |

### SSE streams

Persistent HTTP connections. No polling. Events push as they happen.

| Stream | Pushes |
|--------|--------|
| `intelligence` | Full typed `IntelligenceEvent` per bar — complete I1–I8 payload |
| `signals` | I7 aggregated signals as they fire, with CIS score and constituent contributions |
| `signal_scorecard` | All ranked I7 candidates per bar — not just the winner |
| `indicators` | Raw I1 indicator values per bar |
| `narratives` | I8 LLM narrative text per signal |
| `ticks` | Live tick stream for price display |

Any HTTP client — a Python trading bot, a Jupyter notebook, an alert engine, a downstream product — connects to an SSE endpoint and receives the same intelligence the internal pipeline produces, in real time, with zero effect on pipeline throughput.

---

## AI & Statistical Intelligence

### The regime model stack

Six models run across I4 and I6, each answering a distinct question about market state:

| Model | Question | Output |
|-------|----------|--------|
| **GARCH** | Is volatility expanding or contracting? | Volatility regime (low / normal / elevated / extreme) + sigma estimate |
| **Kalman filter** | What is the true underlying trend, separate from noise? | Smooth trend slope — adapts to current signal-to-noise ratio |
| **HMM** | Which hidden market state is most probable? | Probability *distribution* over 3 states — not just an argmax |
| **BOCPD** | Is a new regime beginning right now? | Changepoint probability per bar — detects transitions before HMM confirms |
| **Hurst Exponent** | Is this market persistent or mean-reverting? | H-value + persistence class — gates signal direction vs. regime |
| **Shannon Entropy** | How predictable is the current price series? | Entropy score — feeds CIS quality multiplier |

### The LLM chain

1. **OpenRouter** (primary): free models, 100+ model catalogue, per-regime model routing
2. **Ollama local** (offline fallback): qwen3.5:9b, AMD ROCm GPU, fully offline

Every call — success or failure — written to `llm_calls` (TimescaleDB hypertable). Per-model win rates and average P&L ratios tracked in `llm_model_scores`, refreshed every 15 minutes.

### Machine Learning Layer (MLAgent)

> **Planned — next milestone.** The feature store and signal ledger are already accumulating the labeled training data this will consume.

The CIS learning loop closes at the weight level. MLAgent closes it at the model level — replacing hand-tuned weights with a full ensemble trained on labeled signal outcomes.

**Three compounding layers:**

```
Layer 1: Discovery     — automated IC analysis finds which features actually predict outcomes
Layer 2: Scoring       — per-regime × per-setup LightGBM ensemble scores every signal
Layer 3: Feedback Loop — outcomes retrain the model; drift triggers automatic retraining
```

**The dataset it consumes — already accumulating:**

| Table | Stores | MLAgent role |
|-------|--------|-------------|
| `intelligence_features` | Full I1–I8 feature vector per bar (tiered JSONB) | Training inputs |
| `signal_ledger` | I7 signal + 8-class lifecycle outcome, MAE, MFE, bars-in-trade | Training targets |
| `llm_calls` | Every LLM invocation with back-filled signal outcome | LLM model scoring |
| `drift_monitor` | KS statistics + CUSUM state per setup/TF | Drift detection source |
| `setup_performance` | Per-setup rolling 30d win rate, avg P&L R, Sharpe | Performance baseline |
| `cis_weights` | Adaptive bucket weights, versioned | Model deployment output |

Every bar the live pipeline processes adds a row to `intelligence_features`. Every signal that resolves adds an outcome row to `signal_ledger`. MLAgent consumes this dataset — the platform has been building it since day one.

**Five-agent LangGraph architecture:**

| Agent | Role | Type |
|-------|------|------|
| **Orchestrator** | Routes work, decides retrain / promote / escalate based on monitoring signals | Deterministic |
| **Data Quality Agent** | Validates training data integrity before any model runs | Deterministic |
| **Discovery Agent** | IC analysis (alphalens), tsfresh feature extraction, regime-conditional IC, cross-asset lag correlation | LLM-guided |
| **Training Agent** | LightGBM ensemble per segment (regime × setup × TF), time-series CV, shadow mode gate | Deterministic |
| **Monitoring Agent** | Evidently drift detection (KS/PSI/Wasserstein), CUSUM degradation, circuit breaker | Event-driven |

No model reaches production without `p < 0.05` with sufficient N. Borderline p-values pause the graph and require human approval via LangGraph `interrupt()` — a dashboard alert presents the full model comparison; 4-hour timeout defaults to reject. Every HITL decision logged with approver, timestamp, and reasoning.

**ML stack:** `langgraph` + `langchain` (agent orchestration, already in stack) · `langfuse` self-hosted (agent observability, OTEL bridge to Grafana) · `guardrails-ai` (LLM output validation against Pydantic schemas) · `scipy` + `alphalens-reloaded` (IC/ICIR analysis per feature per regime) · `tsfresh` (700+ statistical features extracted automatically from any time series) · `evidently` (KS/PSI/Wasserstein drift detection, self-hosted) · `polars` (Rust dataframes, 10–100× faster than pandas for feature matrix construction) · `lightgbm` (the model — tabular data champion) · `shap` (TreeSHAP explainability per signal) · `optuna` (Bayesian hyperparameter optimisation) · `statsmodels` (CUSUM, time-series statistics) · `mlflow` self-hosted (model registry, experiment tracking) · `river` (online/incremental learning between retrains).

**Explicitly not added:** PyTorch/TensorFlow (tree ensembles dominate tabular benchmarks) · Feast (TimescaleDB is the feature store) · Weights & Biases (cloud/paid — MLflow is the open standard) · Ray/Dask (overkill for current data volume).

→ [MLAgent Design](docs/ideas/ml-learning-machine.md)

---

## Observability

Every service exposes a Prometheus-compatible metrics endpoint:

| Service | Metrics |
|---------|---------|
| `feature_pipeline_service` | :9125 |
| `signal_generator_service` | :9112 |
| `ai_narrative_service` | :9113 |
| `signal_lifecycle_service` | :9115 |
| `feature_writer_service` | :9116 |
| `llm_writer_service` | :9117 |
| `cross_asset_service` | :9118 |

Grafana dashboards: pipeline throughput per symbol/TF · per-service P50/P95/P99 latency · signal generation and regime gate drop rates · LLM call success and fallback rates · per-plugin error rates.

A new plugin that causes latency spikes is visible within seconds. A regime gate filtering too aggressively shows up as a signal rate drop before it affects any downstream consumer.

---

## Extension Model

The stream architecture makes extension explicit. New data domains and product layers attach the same way: **subscribe to the streams you need, publish what you produce.** Nothing already running changes.

### Planned product layers

| Product | Role | Attaches via |
|---------|------|-------------|
| **QualAgent** | Macro regime, COT positioning, news NLP, sentiment, prediction markets | Subscribes to market streams; publishes `qual:regime`, `qual:score` |
| **DerivAgent** | Vol surface, gamma exposure, VRP, skew, options execution | Subscribes to intelligence streams; publishes `deriv:vol_regime`, `deriv:gex` |
| **TradeAgent** | Directional execution, position sizing, order management | Subscribes to `signals:SYMBOL:TF:aggregated` |
| **PrimeAgent** | Unified P&L, capital allocation, Kelly sizing, performance attribution | Subscribes to execution events from all strategies |
| **AegisAgent** | Independent risk: VaR, drawdown enforcement, margin monitoring, emergency halt | Subscribes to portfolio state; publishes binding halt instructions |

Risk enforcement is a stream subscriber — not a wrapper around execution code. Portfolio management is a stream subscriber — not a shared database. The bus is the architecture.

---

## At a Glance

| | |
|---|---|
| **Version** | v2.0 in progress — Signal Integrity & ML Foundation |
| **Instruments** | 60 — equity index futures (ES, NQ, RTY, YM) · energy (CL) · metals (GC, SI, HG, PL) · rates (ZN, ZF, ZB, ZT) · volatility (VX) · agriculture (ZS, ZC, ZW) · FX (EURUSD, GBPUSD, USDJPY, USDCHF) · crypto (BTCUSD, ETHUSD, SOLUSD) · 38 ETFs |
| **Plugins** | 121 across I1–I7 + 2 aggregation components |
| **Tests** | 2641 passing (unit) |
| **Latency** | <10ms bar-to-intelligence, feed-provider bound |
| **Data in** | IBKR TWS: 100–500+ ticks/sec per instrument |
| **Data out** | Redpanda Topics · TimescaleDB feature store · REST API · SSE |
| **Hot/Warm path** | Redpanda (Kafka-compatible, sub-ms, durable, replayable) |
| **Cold path** | TimescaleDB on PostgreSQL 17 (feature store, signal ledger, LLM audit) |
| Services | 7 systemd services, `Restart=always` |
| **Stack** | Python 3.13 · FastAPI · LangGraph · Next.js 16.1 / React 19.2 · Tailwind v4 · Prometheus · Grafana |

---

## Current Status

**v2.0 in progress — Signal Integrity & ML Foundation.**

- **I1–I8 pipeline:** Fully operational. 121 plugins + 2 aggregation components, typed intelligence bus, feature store, CIS scorer with constituent contributions.
- **v2.0 phases complete:** DAG Refactor (Phase 40) · Intelligence Gap Fill (Phase 41) · Candlestick Expansion (Phase 42) · I6 Confluence (Phase 43) · Feature Pipeline Renaissance (Phase 44.1 — `indicator_service` + `market_analysis_service` unified into `feature_pipeline_service`).
- **Feature Pipeline:** I1–I6 now run as a single in-process pipeline (`feature_pipeline_service`) — eliminates inter-service hops, reduces end-to-end latency, simplifies service topology.
- **Cross-asset intelligence:** OFI/CVD microstructure (I1) + 7 new I7 setups + `cross_asset_service` injecting spread dynamics into I7 for EQ index instruments.
- **CIS pipeline:** Kalman filter → TOD multiplier → isotonic calibration → sorted by `calibrated_confidence`. Full audit trail per signal.
- **API layer:** REST + SSE. Full intelligence accessible to any HTTP client over standard HTTP.
- **Dashboard:** Price hero · multi-TF intelligence panels · SMC panel · I7 signal drill panel with DB history · Signal Scorecard (all ranked candidates) · AI narrative cards · tier tooltips throughout.
- **AI Narratives:** OpenRouter (free models) / Ollama (conf > 0.7, 5m/15m/1h); group synthesis across 6 asset groups; full `llm_calls` audit trail with outcome back-fill.
- **Next:** Phase 44.2 — Signal Generator consolidation.

---

## Documentation

**→ [Full Documentation](docs/README.md)**
**→ [Roadmap](.planning/ROADMAP.md)**
**→ [DAG Execution](docs/concepts/dag-execution.md)**
**→ [CIS Scoring](docs/concepts/cis-scoring.md)**
**→ [Data Pipeline](docs/concepts/data-pipeline.md)**

**For AI Assistants:** [CLAUDE.md](CLAUDE.md)

---

**v2.0 · 121 plugins · 2641 tests · 60 instruments**
