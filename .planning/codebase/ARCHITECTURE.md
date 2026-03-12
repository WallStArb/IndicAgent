# Architecture

**Analysis Date:** 2026-03-11

## Pattern Overview

**Overall:** Plugin-native event-driven intelligence pipeline with 8 tiers of analysis (I1–I8) flowing through a hot/warm/cold data architecture.

**Key Characteristics:**
- **Plugin-based intelligence tiers**: All analysis is modular — each tier (I1–I8) runs independent plugins that consume typed inputs and produce validated outputs
- **Typed event bus**: Single canonical `IntelligenceEvent` model flows through the system; every plugin output is validated against sub-models
- **Multi-layered data streaming**: Hot tier (Redis Streams, sub-ms), Warm tier (service pipeline, <10ms), Cold tier (TimescaleDB batch, async)
- **Stateful plugin execution**: Plugin state is isolated per (symbol, timeframe, plugin_name), swapped on/off per-bar to prevent cross-symbol leakage
- **Consumer group-driven service orchestration**: Each service is a stateless stream consumer with idempotent replay capability

## Layers

**Data Foundation (Layer 1):**
- Purpose: Collect and distribute raw market data
- Location: `src/providers/ibkr.py` (TWS connection), `production/daemons/` (tick publisher)
- Contains: IBKR quote ticks, bar OHLCV via TWS
- Depends on: IBKR Interactive Brokers
- Used by: All downstream services

**Technical Indicators (Layer I1):**
- Purpose: Compute 23 technical indicators (RSI, MACD, Bollinger Bands, ATR, ADX, etc.) at 1m/5m/15m/1h resolution
- Location: `services/indicator_service.py`, `src/intelligence/indicators/`
- Contains: 23 indicator plugins (trend, momentum, volatility, volume categories)
- Depends on: Market data from `market:SYMBOL:TF` Redis streams
- Used by: Market analysis service (I3–I6 pipeline)
- Output: Single combined message per bar to `indicators:SYMBOL:TF` stream

**Composite Events (Layer I2):**
- Purpose: Detect crossovers, threshold crossings, extremes on top of I1 outputs
- Location: `src/intelligence/composites/`
- Contains: 11 composite plugins (MACD events, RSI events, Stochastic events, ADX events, Volume events, Acceleration regime, Donchian position, OBV momentum, Derivative oscillator, Exhaustion score, MA composites)
- Depends on: I1 indicator outputs
- Used by: Incorporated into `IntelligenceEvent.i2` for downstream pattern detection

**Structure Analysis (Layer I3):**
- Purpose: Identify market structure, support/resistance, swing patterns, profile levels
- Location: `src/intelligence/structure/`
- Contains: 8 plugins (swing detector, S/R, trend structure, market profile, session levels, anchored VWAP, Fibonacci zones, swing momentum)
- Depends on: OHLCV bars
- Used by: Pattern detection and confluence analysis
- Outputs: Swing highs/lows, support/resistance levels, trend direction, market profile POC/VA, Fibonacci ratios

**Context Classification (Layer I4):**
- Purpose: Quantify regime (volatility, trend, momentum) and session context
- Location: `src/intelligence/context/`
- Contains: 7 plugins (vol regime, trend regime, momentum context, GARCH volatility, Kalman filter, session context, MTF volatility)
- Depends on: I1 indicators, price bars, time/date
- Used by: Signal generation (regime gating), trading setup qualification
- Outputs: Regime flags (ranging/trending), vol percentile, session killzones, HMM regime state

**Pattern Detection (Layer I5):**
- Purpose: Identify chart patterns, divergences, confluence zones, technical formations
- Location: `src/intelligence/patterns/`
- Contains: 14 plugins (RSI divergence, squeeze, vol divergence, confluence, double top/bottom, head & shoulders, triangle/wedge, candlestick patterns, flag/pennant, cup & handle, measured move, volume profile, key level reaction, trend confluence)
- Depends on: I3 structure, I1 indicators, OHLCV
- Used by: I7 trading setups (pattern-based entries)
- Outputs: Pattern confidence scores, target levels, formation state

**Smart Money Concepts (Layer SMC/I6 sub-tier):**
- Purpose: Institutional/smart money flow analysis (order blocks, fair value gaps, liquidity pools, killzones)
- Location: `src/intelligence/smart_money/`
- Contains: 13 plugins (BOS/CHoCH, FVG, order blocks, liquidity sweeps, BOCPD changepoint, HMM regime, liquidity pools, supply/demand zones, ICT killzones, AMD cycle, breaker blocks, mitigation blocks, premium/discount)
- Depends on: Swing structure, OHLCV extremes, time of day
- Used by: I6 confluence, I7 setup targeting
- Outputs: Zone levels, sweep/mitigation events, killzone entry/exit signals

**Confluence & Cross-Timeframe (Layer I6):**
- Purpose: Aggregate multi-timeframe alignment, validate I3–SMC signals across TFs
- Location: `src/intelligence/confluence/` (1 plugin: CrossTimeframeConfluence)
- Contains: Single `CrossTimeframeConfluence` plugin that reads aligned timeframes
- Depends on: I3, SMC, I4 outputs across multiple timeframes (1m, 5m, 15m, 1h)
- Used by: Signal generation, setup quality scoring
- Outputs: CTF alignment score, highest aligned TF, multi-TF trend agreement

**Trading Setups (Layer I7):**
- Purpose: Generate trade entry signals based on confluence of I1–I6 indicators
- Location: `src/intelligence/trading/` (17 plugins + aggregator)
- Contains: 17 I7 setup plugins (TrendFollowing, MeanReversion, LiquiditySweepReclaim, MTFAlignment, SqueezeExpansion, VWAPDeviation, MomentumBreakout, LiquidityHunt, SupplyDemandSetup, CHoCHReversal, FVGFill, PatternCompletion, DivergenceStack, RegimeTransition, GapAnalysisSetup, CandlestickPatternSetup, SessionExtremesSetup) + aggregator (Aggregator, CIS-based composite score)
- Depends on: All I1–I6 outputs; I4 regime for gating
- Used by: Signal generation, signal lifecycle tracking
- Output: Per-bar collection of fired setups with direction/targets/entry zones; aggregator selects ONE active signal per bar via regime gate + performance weighting

**AI Narrative (Layer I8):**
- Purpose: Generate LLM-based narrative context and confirmations for signals
- Location: `services/ai_narrative_service.py`, `src/intelligence/llm_providers.py`
- Contains: LLM chain (Z.ai GLM-5 → OpenRouter fallback → Ollama qwen3.5:9b), per-signal narrative generation
- Depends on: I7 active signal, bar context, historical setup outcomes
- Used by: Dashboard narrative display, outcome feedback loops
- Output: Narrative metadata to `narratives:SYMBOL:TF` stream; outcomes to `llm_outcomes:stream`

## Data Flow

**Live Signal Pipeline:**

1. **Market collection** (TWS → tick publisher) → `market:SYMBOL:TF` Redis stream (1m bars)
2. **I1 computation** (indicator_service) consumes `market:SYMBOL:TF` → publishes `indicators:SYMBOL:TF`
3. **I2–I6 computation** (market_analysis_service) consumes `indicators:SYMBOL:TF` → publishes `intelligence:SYMBOL:TF` (typed IntelligenceEvent)
4. **I7 signal generation** (signal_generator_service) consumes `intelligence:SYMBOL:TF` → fires setups → publishes to `signals:SYMBOL:TF:aggregated` (one active signal per bar)
5. **Signal lifecycle** (signal_lifecycle_service) consumes market bars + live signals → tracks MAE/MFE/outcomes → publishes to `signal_ledger`
6. **I8 narratives** (ai_narrative_service) consumes `signals:SYMBOL:TF:aggregated` → LLM analysis → publishes `narratives:SYMBOL:TF`
7. **Feature persistence** (feature_writer_service) consumes `intelligence:SYMBOL:TF` + enrichments → batch writes to `intelligence_features` hypertable
8. **LLM audit** (llm_writer_service) consumes `llm_calls:stream` + `llm_outcomes:stream` → writes `llm_calls` hypertable + back-fills `llm_model_scores`

**State Management:**

- **Per-bar plugin state**: Each plugin maintains internal state (e.g., GARCH volatility model, HMM regime probabilities). State is isolated per (symbol, timeframe, plugin_name) in service memory (`_plugin_states` dict). Swapped on/off before/after each plugin execution to prevent cross-symbol state bleed.
- **In-memory signal tracking**: Signal lifecycle service maintains `_activated_at`, `_mae`, `_mfe` dicts keyed by `signal_id`. Written to `signal_ledger` on signal exit. No distributed state — per-service in-memory only.
- **CIS aggregator weights**: Loaded from `setup_performance` table at startup + every 60 min into Redis cache `setup_performance:weights`. Applied per-setup in aggregator ranking.
- **Consumer groups**: Each service maintains Redis consumer group (e.g., `indicator_service`, `market_analysis`, `signal_generator`) starting at `$` (skip backlog on first run). Groups persist across restarts, enabling replay of missed bars during downtime.

## Key Abstractions

**Plugin Protocol:**
- Purpose: Encapsulate analysis logic with typed inputs/outputs
- Examples: `src/intelligence/indicators/rsi.py`, `src/intelligence/structure/swing_detector.py`, `src/intelligence/trading/trend_following.py`
- Pattern: Each plugin implements `PatternPlugin` with `inputs` (tuple of `InputSpec`), `outputs` (frozenset of field names), and `compute_full(bar_data, state) -> dict`. Plugins are stateless functions; state management is external.

**IntelligenceEvent Schema:**
- Purpose: Canonical typed model for all intelligence flowing through system
- Examples: `src/intelligence/schemas.py` defines `OHLCVBar`, `I1Indicators`, `I2Events`, `I3Structure`, `I4Context`, `I5Patterns`, `SMCContext`, `I6Confluence`, `IntelligenceEvent`
- Pattern: Nested Pydantic models with `extra="forbid"` (strict) on I3–I6/SMC to catch schema drift; `extra="allow"` on I1 to permit period-encoded field names (rsi_14, atr_20, etc.)

**Signal Ledger Entry:**
- Purpose: Persistent record of every signal, its lifecycle, and outcome
- Examples: `src/intelligence/trading/signal_ledger.py` defines `LedgerEntry` dataclass
- Pattern: Single table `signal_ledger` hypertable in TimescaleDB with (symbol, timestamp) primary key. Rows are immutable after exit; fields populated progressively (determined_at → activation → outcome).

**Trade Frame:**
- Purpose: Encapsulate entry zone geometry, stop/target levels for a signal
- Examples: `src/intelligence/trading/trade_framer.py` defines `TradeFrame` and `_resolve_zone_bounds()`
- Pattern: Zone bounds computed at signal determination time from setup-specific rules (e.g., supply_demand → nearest_supply/demand levels; fvg → fvg_bottom/top; others → entry ± 1.0×ATR). Used by lifecycle tracker for zone-aware activation detection.

**Aggregator:**
- Purpose: Select ONE active signal per bar from all fired I7 setups
- Examples: `src/intelligence/trading/aggregator.py`
- Pattern: Rank all fired setups by (regime eligibility × perf_multiplier × confluence_score); activate highest-ranked if regime-eligible; suppress mean-reversion setups in trending regimes (HMM) and trend-following in ranging regimes.

**CIS (Composite Intelligence Score):**
- Purpose: Weighted aggregate quality score across I1–I6 constituents
- Examples: `src/intelligence/trading/cis_scorer.py`
- Pattern: Bucket-based scoring — I1 (technical), I3 (structure), I4 (context), I5 (patterns), SMC (smart money), I6 (confluence) each get weighted scores; final CIS ∈ [-1.0, +1.0]. Applied at signal fire time by signal_generator to populate `signal_ledger.cis_score`.

## Entry Points

**indicator_service (I1):**
- Location: `services/indicator_service.py`
- Triggers: Executes on schedule; triggered by market bar arrival on `market:SYMBOL:TF` stream
- Responsibilities: Read bar OHLCV, run 23 I1 plugins, publish combined `indicators:SYMBOL:TF` message

**market_analysis_service (I3–I6):**
- Location: `services/market_analysis_service.py`
- Triggers: Consumes `indicators:SYMBOL:TF` (I1 output)
- Responsibilities: Parse I1 output, run I3/I4/I5/SMC/I6 plugins, construct typed `IntelligenceEvent`, publish to `intelligence:SYMBOL:TF`

**signal_generator_service (I7):**
- Location: `services/signal_generator_service.py`
- Triggers: Consumes `intelligence:SYMBOL:TF` (full intelligence event)
- Responsibilities: Run 17 I7 setup plugins, aggregate via CIS + regime gating, fire one active signal per bar, publish to `signals:SYMBOL:TF:aggregated`

**signal_lifecycle_service (lifecycle):**
- Location: `services/signal_lifecycle_service.py`
- Triggers: Consumes market bars (1m) and `signals:SYMBOL:TF:aggregated`
- Responsibilities: Track signal activation, compute MAE/MFE, classify 8-class outcome, write to `signal_ledger`

**ai_narrative_service (I8):**
- Location: `services/ai_narrative_service.py`
- Triggers: Consumes `signals:SYMBOL:TF:aggregated`
- Responsibilities: Call LLM with setup context, generate narrative, publish to `narratives:SYMBOL:TF`, emit LLM audit events

**feature_writer_service (cold storage):**
- Location: `services/feature_writer_service.py`
- Triggers: Consumes `intelligence:SYMBOL:TF` (I6 outputs) + enrichment streams
- Responsibilities: Batch accumulate feature vectors, write to `intelligence_features` hypertable (ML training dataset)

**FastAPI API:**
- Location: `src/api/main.py`
- Triggers: HTTP requests from dashboard / external clients
- Responsibilities: Serve instrument metadata, current market state, signal summaries, SSE stream for live updates

## Error Handling

**Strategy:** Graceful degradation per plugin; services continue on upstream plugin failures.

**Patterns:**
- **Plugin timeout**: If plugin exceeds budget (computed live at execution), it returns `None` for all outputs; downstream plugins see `None` and handle per their `InputSpec` (required inputs → skip that downstream plugin; optional → proceed with `None`)
- **Service restart**: Consumer groups persist across restarts. On restart, service resumes from last acknowledged position in stream (not `$` — `$` only applies on first group creation). Missed bars are replayed on next startup.
- **Validation failure**: If `IntelligenceEvent` fails Pydantic validation, message is logged + dropped; service continues to next message (no blocking).
- **Database connection loss**: Services retry with exponential backoff (retry_utils.py); feature_writer queues locally; signal_lifecycle falls back to in-memory state (resets on crash).

## Cross-Cutting Concerns

**Logging:**
- Tool: `structlog` with structured fields (timestamp, service, symbol, timeframe, level)
- Pattern: Every service logs startup, per-bar processing, errors. Logs streamed via `journalctl` on systemd units.

**Validation:**
- Plugin outputs validated against registry output schemas + Pydantic models (I3–I6 strict mode)
- IntelligenceEvent validated before publishing to stream
- Signal ledger entries type-checked at insert time

**Authentication:**
- IBKR: Client ID 35+, TWS running on LAN at 10.0.0.33:7497
- API: No authentication (local only, no secrets exposed)
- LLM: API keys in `.env` (ZAI_API_KEY, OPENROUTER_API_KEY)

**Metrics & Observability:**
- Prometheus metrics exported by each service on individual port (indicator :9109, market-analysis :9114, signal-gen :9112, etc.)
- Metrics: Per-plugin execution time, latency from bar close to signal fire, error rates
- Dashboards: Grafana via `production/grafana/`

---

*Architecture analysis: 2026-03-11*
