# I7 Trading Signals + AI Expert Panel — Design Document

**Date:** 2026-02-16
**Status:** Approved
**Scope:** I7 setup detection, AI expert panel (I8), signal distribution, external API

---

## Vision

Transform IndicAgent from an intelligence observation platform into an actionable signal generation engine. The system generates regime-adaptive trading signals from its I1-I6 intelligence stack, enriches them with a multi-expert AI panel, and distributes them via Redis Streams (internal) and a future WebSocket API (external). A separate trading application subscribes to signals — IndicAgent never executes trades.

---

## Architecture Summary

```
I1-I6 Intelligence Pipeline (33 plugins, operational)
    ↓
I7 Rule-Based Setup Detection (14 plugins, 3 phases)
    ├── Regime-driven: TrendFollowing, MeanReversion, Breakout, RegimeTransition
    ├── Smart Money: LiquiditySweepReclaim, OrderBlockRetest, FVGMitigationEntry
    ├── Volatility: SqueezeExpansion, VolatilityContraction
    ├── Cross-TF: MultiTimeframeAlignment, TimeframeDivergence
    └── Momentum: MomentumIgnition, ExhaustionReversal, VWAPReclaim
    ↓
I8 AI Expert Panel (5 agents, Ollama local → OpenRouter remote)
    ├── Confluence Synthesizer:    Meta-reasoning about which factors to trust
    ├── Smart Money Interpreter:   Sequencing SMC events into institutional narrative
    ├── Regime Strategist:         Regime duration, transition forecasting
    ├── Cross-Market Analyst:      14-instrument intermarket pattern detection
    └── Risk Assessor:             Portfolio correlation, sizing, event risk
    ↓
Signal Distribution
    ├── Internal: Redis Streams (env:signals:SYMBOL:TF) → SSE → Dashboard
    └── External: WebSocket API with auth + filtering (future)
```

### Key Design Decisions

1. **IndicAgent = intelligence only.** Trading execution is a separate application that subscribes to signals.
2. **Regime-adaptive signals.** Signal type and frequency adapt to current market regime (trending → trend setups, ranging → reversion setups, transitioning → breakout setups).
3. **AI has influence, not authority.** I7 produces deterministic, reproducible signals. AI experts can adjust confidence within bounded limits (±0.15) and add rationale, but cannot create or suppress signals.
4. **Three-layer AI:** (1) Deterministic I7 backbone, (2) AI signal enhancement, (3) AI novel discovery.
5. **Two-tier distribution.** Redis Streams for co-located internal services (<1ms). WebSocket API for remote consumers (future).
6. **Ollama first, OpenRouter later.** Local inference during development (zero cost, full privacy). OpenRouter expansion when ready to scale.
7. **Cost-optimized model routing.** Each AI expert maps to a model tier based on its cognitive requirements (reasoning, math, speed). Configuration-driven, easily swappable.

---

## I7 Setup Detection Plugins

### Signal Schema (`signal.v1`)

Published to: `env:signals:SYMBOL:TIMEFRAME`

```python
{
    "type": "signal.v1",
    "schema_version": "1.0.0",
    "symbol": str,                    # Trading symbol (e.g., "ES")
    "timeframe": str,                 # Timeframe that generated the signal
    "timestamp": str,                 # UTC ISO-8601
    "signal_type": str,               # "trend_long", "trend_short", "reversion_long", etc.
    "setup_plugin": str,              # Which I7 plugin generated it
    "direction": int,                 # +1 long, -1 short
    "entry_price": float,             # Suggested entry level
    "stop_loss": float,               # Stop loss level
    "targets": list[float],           # [T1, T2, T3] price targets
    "confidence": float,              # 0.0-1.0 base confidence
    "risk_reward_ratio": float,       # Risk/reward based on T1
    "regime_context": str,            # Current regime when signal generated
    "confluence_score": float,        # I6 score at signal time
    "supporting_factors": list[str],  # Which I1-I6 outputs support this
    "invalidation_conditions": list[str],  # What cancels this signal
    "ttl_bars": int,                  # Signal expires after N bars
    "ai_enhancement": {               # Added by I8 expert panel (null until enhanced)
        "adjusted_confidence": float,
        "expert_assessments": list[dict],
        "combined_rationale": str,
        "risk_flags": list[str],
    } | None,
}
```

### Setup Catalog (14 setups, 3 phases)

#### Phase 1 — Foundation (5 setups)

**`trad_TrendFollowing`** — Regime = trending
- **Triggers:** I4 trend regime = bullish/bearish + I6 confluence > threshold + confirming structure (HH/HL for longs, LH/LL for shorts)
- **Entry:** Pullback to EMA or order block retest
- **Stop:** Below last swing low (longs) / above last swing high (shorts)
- **Targets:** ATR-based (1R, 2R, 3R) or next S/R level
- **Confidence:** Weighted from confluence score + regime strength + smart money alignment
- **Dependencies:** I3 (swings, trend), I4 (trend regime), I6 (confluence)

**`trad_MeanReversion`** — Regime = ranging
- **Triggers:** I4 volatility regime = low/normal + price at S/R extremes + RSI divergence or exhaustion signals
- **Entry:** At support/resistance level with reversal confirmation
- **Stop:** Beyond the range boundary + ATR buffer
- **Targets:** Opposite side of range or midpoint
- **Confidence:** Weighted from range integrity + divergence strength + volume confirmation
- **Dependencies:** I3 (S/R), I4 (vol regime), I5 (RSI divergence)

**`trad_LiquiditySweepReclaim`** — Highest-conviction SMC setup
- **Triggers:** Liquidity sweep detected (I6) → price reclaims level within 1-3 bars → FVG or order block at reclaim zone → volume spike confirms absorption
- **Entry:** At FVG/OB after reclaim
- **Stop:** Beyond the sweep extreme
- **Targets:** Next liquidity pool / opposing S/R
- **Confidence:** Weighted from sweep magnitude + reclaim speed + volume ratio + regime alignment
- **Dependencies:** I6 (liquidity sweeps, FVG, order blocks)

**`trad_MultiTimeframeAlignment`** — When everything agrees
- **Triggers:** I6 cross-timeframe confluence score > 0.8 + ≥3 timeframes aligned + regime agreement
- **Entry:** On the lowest aligned timeframe's signal (best R/R)
- **Stop:** Based on lowest timeframe structure
- **Targets:** Based on highest aligned timeframe structure
- **Confidence:** Directly from I6 confluence score
- **Dependencies:** I6 (cross-timeframe confluence)

**`trad_SqueezeExpansion`** — Volatility breakout
- **Triggers:** BB squeeze detected (I5) + duration > N bars + Keltner inside Bollinger → first expansion bar with volume > 1.5x average
- **Direction:** Determined by I4 momentum context + trend regime
- **Targets:** Measured move = squeeze range projected in breakout direction
- **Confidence:** Weighted from squeeze duration + volume expansion ratio + regime clarity
- **Dependencies:** I5 (BB squeeze), I4 (momentum context), I1 (volume)

#### Phase 2 — Smart Money & Volatility (4 setups)

**`trad_OrderBlockRetest`** — Institutional demand/supply
- **Triggers:** BOS/CHoCH confirms structure shift → price returns to OB zone → rejection candle + declining pullback volume
- **Entry:** At OB boundary
- **Stop:** Through the OB
- **Targets:** Origin of the structure break
- **Dependencies:** I6 (BOS/CHoCH, order blocks), I1 (volume)

**`trad_FVGMitigationEntry`** — Fair value gap fill
- **Triggers:** Unmitigated FVG in trend direction → price retraces into gap → regime confirms trend → volume decreases on approach
- **Entry:** Inside FVG zone
- **Stop:** Beyond FVG
- **Dependencies:** I6 (FVG), I4 (trend regime)

**`trad_ExhaustionReversal`** — End of move
- **Triggers:** RSI divergence (I5) + weakening momentum (I4) + price at S/R extreme + declining volume on new highs/lows + Williams %R extreme
- **Entry:** On reversal confirmation (structure shift or engulfing)
- **Stop:** Beyond the extreme
- **Dependencies:** I5 (RSI divergence), I4 (momentum), I3 (S/R), I1 (Williams %R, volume)

**`trad_VWAPReclaim`** — Institutional reference
- **Triggers:** Price breaks below VWAP → reclaims above → holds on retest → volume confirms
- **Entry:** On retest hold
- **Stop:** Below VWAP
- **Targets:** Previous session high or next S/R
- **Dependencies:** I1 (VWAP), I1 (volume)

#### Phase 3 — Advanced (5 setups)

**`trad_RegimeTransition`** — Catches the regime shift
- **Triggers:** HMM state probability shifting (transition probability > 0.6) + BOCPD change point + declining trend structure integrity
- **Entry:** In direction of emerging regime
- **Stop:** Based on pre-transition structure
- **Dependencies:** I6 (HMM, BOCPD), I3 (trend structure)

**`trad_Breakout`** — Classic breakout with smart money confirmation
- **Triggers:** Price at consolidation boundary + BOS event + volume expansion + squeeze resolved
- **Entry:** On breakout bar close
- **Stop:** Inside consolidation range
- **Targets:** Measured move (range height projected)
- **Dependencies:** I6 (BOS), I5 (squeeze), I3 (S/R), I1 (volume)

**`trad_TimeframeDivergence`** — Counter-trend exhaustion in higher-TF trend
- **Triggers:** Higher TF trending + lower TF counter-trend exhaustion + lower TF structure shift back toward higher TF
- **Entry:** When lower TF realigns with higher TF
- **Dependencies:** I6 (cross-TF confluence), I4 (regime per TF), I5 (divergences)

**`trad_MomentumIgnition`** — Start of move
- **Triggers:** I4 momentum neutral→strong + MACD histogram expanding + volume > 2x average + no nearby overhead S/R
- **Entry:** On ignition bar close
- **Stop:** Below ignition bar low
- **Dependencies:** I4 (momentum context), I1 (MACD, volume), I3 (S/R)

**`trad_VolatilityContraction`** — Fade extreme volatility
- **Triggers:** ATR percentile > 90th + vol regime "extreme" → first contraction bar → RSI divergence
- **Entry:** Fade overextension toward VWAP/mean
- **Stop:** Beyond the volatility extreme
- **Dependencies:** I4 (vol regime), I1 (ATR, RSI, VWAP)

---

## I8 AI Expert Panel

### LLM Abstraction Layer

```python
# src/intelligence/ai/llm_client.py
class LLMClient:
    """Unified LLM interface — Ollama (local) or OpenRouter (remote)."""

    async def complete(
        self,
        model: str,
        messages: list[dict],
        response_format: dict | None = None,
    ) -> dict:
        """Send completion request. Returns structured JSON."""

    # Features:
    # - Ollama: POST http://localhost:11434/api/chat
    # - OpenRouter: POST https://openrouter.ai/api/v1/chat/completions
    # - Structured JSON output enforcement
    # - Retry with exponential backoff
    # - Cost tracking (tokens, latency, model)
    # - Response caching (same input → same output within TTL)
```

### Configuration

```json
{
    "llm_backend": "ollama",
    "ollama_url": "http://localhost:11434",
    "openrouter_url": "https://openrouter.ai/api/v1",
    "openrouter_api_key": "${OPENROUTER_API_KEY}",
    "expert_models": {
        "confluence_synthesizer": "qwen2.5:14b",
        "smart_money_interpreter": "llama3.3:8b",
        "regime_strategist": "qwen2.5:14b",
        "cross_market_analyst": "qwen2.5:14b",
        "risk_assessor": "phi4:14b"
    },
    "expert_frequency": {
        "confluence_synthesizer": "per_signal",
        "smart_money_interpreter": "per_signal",
        "regime_strategist": "per_signal",
        "cross_market_analyst": "every_5min",
        "risk_assessor": "per_signal"
    }
}
```

### Expert Plugin Protocol

```python
# src/intelligence/ai/expert_protocol.py
class ExpertPlugin(Protocol):
    name: str
    required_context: list[str]       # ["I4_regime", "I6_hmm", "I6_bocpd"]
    model_requirement: str            # "reasoning" | "fast" | "math"
    max_confidence_adjustment: float  # Bounded, e.g., 0.15
    max_frequency: str                # "per_signal" | "per_minute" | "every_5min"

    async def evaluate(self, context: dict) -> ExpertAssessment

@dataclass
class ExpertAssessment:
    expert_name: str
    confidence_adjustment: float       # -0.15 to +0.15
    rationale: str                     # Human-readable explanation
    risk_flags: list[str]              # Warning flags
    supporting_evidence: list[str]     # What data supports this assessment
    discovery_candidates: list[dict]   # Novel patterns found (Cross-Market only)
    latency_ms: float
    model_used: str
    token_usage: dict                  # {"input": N, "output": N}
```

### Expert Agents

**`ai_ConfluenceSynthesizer`** (Phase 2 — first expert)
- **Input:** Full I1-I7 context for the signal's symbol/timeframe
- **Role:** Meta-reasoning about which confluence factors to trust in current conditions
- **Output:** Confidence adjustment + rationale explaining why certain factors matter more than others
- **Model need:** Reasoning (structured evaluation)

**`ai_SmartMoneyInterpreter`** (Phase 2 — second expert)
- **Input:** I6 SMC events sequence (BOS, CHoCH, FVG, OB, sweeps) for signal's symbol
- **Role:** Reads the sequence of SMC events as an institutional narrative
- **Output:** Narrative interpretation + confidence adjustment based on institutional intent
- **Model need:** Reasoning (pattern sequencing)

**`ai_RegimeStrategist`** (Phase 3)
- **Input:** I4 regime data + HMM state probabilities + BOCPD change points
- **Role:** Forecasts regime duration, transition probability, and what would invalidate
- **Output:** Regime outlook + confidence adjustment based on regime stability
- **Model need:** Reasoning (temporal forecasting)

**`ai_CrossMarketAnalyst`** (Phase 3)
- **Input:** Latest intelligence across all 14 instruments
- **Role:** Detects intermarket patterns (correlations, divergences, rotations)
- **Output:** Cross-market narrative + discovery candidates for novel patterns
- **Model need:** Large context + reasoning (multi-instrument synthesis)
- **Frequency:** Every 5 minutes or on regime change (not per-signal)

**`ai_RiskAssessor`** (Phase 3)
- **Input:** Active signals across all instruments + I4 vol regime + correlation data
- **Role:** Portfolio-level risk evaluation (correlation, sizing, concentration)
- **Output:** Risk flags + sizing recommendation + confidence adjustment
- **Model need:** Math/logic (correlation calculations, exposure analysis)

### Expert Orchestration (LangGraph)

```
Signal generated by I7
    ↓
LangGraph parallel fan-out
    ├── ConfluenceSynthesizer.evaluate(context)
    ├── SmartMoneyInterpreter.evaluate(context)
    ├── RegimeStrategist.evaluate(context)
    ├── (CrossMarketAnalyst — latest cached assessment)
    └── RiskAssessor.evaluate(context)
    ↓
Synthesis node: combine assessments
    - Sum bounded confidence adjustments
    - Merge rationales
    - Collect risk flags
    - Produce final enriched signal
    ↓
Publish enriched signal to env:signals:SYMBOL:TF
```

### AI Discovery Mode

The Cross-Market Analyst runs periodically (not per-signal) and publishes discoveries:

- **Stream:** `env:discovery:MARKET`
- **Schema:** Discovery candidates with symbol, pattern description, confidence, suggested action
- **Lifecycle:** Discovery → tracked → validated/expired → optionally promoted to signal

---

## Signal Distribution

### Internal (Phase 1)

- **Redis Stream:** `env:signals:SYMBOL:TIMEFRAME` — same infrastructure as all other streams
- **SSE Event:** `signal_data` event type pushed to dashboard
- **Dashboard:** New signal panel with setup type, direction, confidence, expert rationales, entry/stop/targets
- **Consumer groups:** Trading app (future) creates its own consumer group on the signals stream

### External API (Phase 4)

- **Endpoint:** WebSocket at `/ws/signals` (or gRPC for high-performance consumers)
- **Auth:** API key or JWT token
- **Subscription filters:** symbol, timeframe, signal_type, min_confidence, setup_plugin
- **Protocol:** JSON messages matching `signal.v1` schema
- **Implementation:** Thin layer reading from the same Redis signals stream

---

## Implementation Phases

### Phase 1: I7 Foundation
- `signal.v1` schema definition and stream publishing
- 5 setup plugins: TrendFollowing, MeanReversion, LiquiditySweepReclaim, MultiTimeframeAlignment, SqueezeExpansion
- Signal dashboard panel (SSE `signal_data` event)
- Unit tests for each plugin (target: 30+ tests)
- Integration test: full pipeline I1→I7 signal generation

### Phase 2: AI Layer Foundation
- LLM abstraction layer (Ollama + OpenRouter interface)
- ExpertPlugin protocol definition
- Confluence Synthesizer expert (first, most bounded, easiest to validate)
- Smart Money Interpreter expert
- LangGraph orchestration: parallel evaluation → synthesis
- Signal enrichment: base signal + AI enhancement → published signal
- Unit + integration tests for AI layer

### Phase 3: Expanded Intelligence
- Phase 2 I7 setups: OrderBlockRetest, FVGMitigationEntry, ExhaustionReversal, VWAPReclaim
- Regime Strategist expert
- Cross-Market Analyst expert + discovery mode
- Risk Assessor expert
- Phase 3 I7 setups: RegimeTransition, Breakout, TimeframeDivergence, MomentumIgnition, VolatilityContraction

### Phase 4: External Distribution
- WebSocket signal API with auth + subscription management
- Signal performance tracking (was the entry hit? was target reached?)
- Historical signal database (TimescaleDB)
- Signal analytics dashboard

---

## Dependencies & Prerequisites

### Already Available (from I1-I6)
- Plugin protocol (PatternPlugin) — I7 setups follow same pattern
- Redis Streams infrastructure — signals are just another stream
- SSE distribution — dashboard already receives stream events
- DAG execution engine — handles plugin dependencies
- All I1-I6 intelligence outputs that I7 setups consume

### New Infrastructure Needed
- Ollama installed locally with selected models
- `src/intelligence/trading/` directory (new)
- `src/intelligence/ai/` directory (new)
- LLM client with structured output parsing
- Expert panel LangGraph workflow
- Signal dashboard panel component

### Configuration Additions
- `config/signal_generation.json` — setup thresholds, regime mappings
- `config/ai_experts.json` — model assignments, frequency limits, confidence bounds
- `config/signal_api.json` — WebSocket settings (Phase 4)

---

## Risk Considerations

1. **Signal quality vs quantity:** Phase 1 should start with conservative thresholds (fewer, higher-conviction signals). Tuning comes after observing live signal flow.
2. **AI hallucination:** Bounded confidence adjustments (±0.15) ensure AI can never dominate the signal. Deterministic I7 is always the backbone.
3. **Ollama latency:** Local models may add 1-5 seconds per expert evaluation. Acceptable for per-signal enrichment, but experts should not block signal publishing — publish base signal immediately, then publish enriched version.
4. **Model drift:** As Ollama models are updated, expert behavior may change. Version-pin models in config and test after updates.
5. **Cost at scale:** With 14 instruments × 6 timeframes, aggressive expert frequency could generate many LLM calls. The `max_frequency` config per expert prevents runaway costs.

---

## Success Criteria

- Phase 1: I7 generates signals visible on dashboard, reproducible, backtestable
- Phase 2: AI experts measurably improve signal quality (tracked via confidence adjustment accuracy)
- Phase 3: Cross-market discovery finds patterns not captured by rule-based plugins
- Phase 4: External trading app successfully subscribes and receives signals over WebSocket

---

## References

- [Intelligence Tiers](../concepts/intelligence-tiers.md)
- [Stream Schemas](../architecture/stream-schemas.md)
- [Plugin Registry & DAG Execution](../architecture/plugin-registry-and-dag-execution.md)
- [Future Indicators Backlog](future-indicators-backlog.md)
- [ICT Smart Money Trading Setups](https://tradingfinder.com/education/forex/trade-continuations-using-order-blocks/)
- [Institutional VWAP Usage](https://medium.com/@steady-turtle-trading/how-professional-traders-really-use-vwap-its-not-what-you-think-cff7bfd9ecd0)
- [Liquidity Sweep Strategies](https://internationaltradinginstitute.com/blog/liquidity-sweeps-entry-exit-strategies/)
- [Systematic Trading Strategies (QuantInsti)](https://www.quantinsti.com/articles/systematic-trading/)
- [Gamma Exposure & Futures](https://menthorq.com/guide/gamma-levels-for-futures-trading/)
