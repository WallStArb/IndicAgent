# Agent Orchestration Patterns & Specialist Intelligence

**Version:** 1.0
**Status:** draft
**Priority:** low
**Milestone:** future (v2.0+ / post-MLAgent)
**Last Updated:** 2026-03-15
**Tags:** agents, llm, orchestration, intelligence, specialist, moa, adversarial, pgvector, semantic-memory

---

## Context

Once MLAgent is live and the learning loop is established, the natural next evolution is a multi-agent intelligence network — specialized agents collaborating on each signal rather than a single LLM doing everything. This doc captures the orchestration patterns and specialist agent concepts worth building toward.

None of this is near-term. It builds on top of MLAgent (v1.9+) and requires the semantic memory infrastructure to be in place first.

---

## Orchestration Patterns

### Mixture-of-Agents (MoA)

The current I8 pattern is sequential (single LLM call per signal). MoA runs multiple smaller "proposer" models in parallel, then a larger "aggregator" synthesizes their outputs.

```
Proposers (parallel, smaller/cheaper models):
  Pattern Agent → Context Agent → Risk Agent → Momentum Agent
        ↓ (all outputs collected)
Aggregator (larger model): unified output with weighted factors + uncertainty bands
        ↓
Critic Gate: evaluator reviews; triggers constrained retry if confidence criteria fail
        ↓
Persistence: store proposer outputs, weights, and rationale for auditability
```

**When to use:** Complex signals where multiple independent perspectives add value — high-volatility regimes, conflicting multi-TF signals, regime transition bars.

**Key design rule:** Use smaller/cheaper models for proposers (Ollama phi4-mini, OpenRouter free tier). Reserve the highest-quality model for the aggregator only. A/B test MoA vs single-model on signal outcome data before committing.

---

### Adversarial Framework (Red Team)

For high-stakes signals (CIS ≥ 0.80, large position sizing context), run a structured bull/bear debate:

- **Bull Advocate:** finds every reason the setup is valid; surfaces supporting evidence
- **Bear Advocate:** finds every reason to reject or wait; surfaces invalidation conditions
- **Neutral Analyst:** evaluates both objectively; outputs a calibrated verdict with explicit uncertainty

**Why it matters:** Reduces confirmation bias in high-confidence setups. The system currently scores signals but doesn't actively challenge them. Red team adversarial adds explicit bias reduction and surfaces black-swan scenarios the primary analysis misses.

**Implementation note:** This is a natural evolution of the Counterfactual Insight Generator (see `ai-07-i8-intelligence-extensions.md`) — the counterfactual is the "bear case" half of this pattern.

---

### Dynamic Leadership

Different intelligence domains should lead depending on market conditions:

| Condition | Leading Agent | Reason |
|-----------|--------------|--------|
| High volatility (GARCH σ > 2) | Volatility agent | Vol regime dominates all other signals |
| Strong trending market (HMM trending_bullish/bearish) | Momentum agent | Trend continuation edge |
| Range-bound (HMM ranging, BOCPD no changepoint) | Mean reversion agent | S/R levels dominate |
| Regime transition | Regime explainer | Context change is the signal |

Current system: all tiers run equally regardless of regime. Dynamic leadership adds regime-aware weighting at the orchestration level — above the CIS plugin weights.

---

## Semantic Memory (pgvector Insight Store)

Enable agents to retrieve similar past market conditions and their outcomes.

### `insight.v1` Schema

```json
{
  "type": "insight.v1",
  "schema_version": "1.0.0",
  "symbol": "ES",
  "timeframe": "15m",
  "intelligence_tier": "I8",
  "insight_type": "pattern_explanation",
  "summary": "Bullish MACD divergence with volume confirmation at VWAP support",
  "evidence_sources": ["I5_macd_divergence", "I2_volume_composite", "I3_vwap"],
  "regime_at_time": "trending_bullish",
  "outcome": "target_1",
  "pnl_r": 1.8
}
```

### Storage and Retrieval

- pgvector table (extend `indicagent` DB) — embed `summary` field; index by symbol, timeframe, regime
- **Embedding policy:** hash-based cache; re-embed only on schema or model change
- **Query pattern:** semantic similarity + filters (symbol, TF, regime) — "what happened the last 5 times ES had MACD divergence in trending_bullish regime?"
- **Agents cache evidence hashes** to avoid duplicate LLM embedding calls

### What This Enables

- Market Memory Agent retrieves historically similar setups and their outcomes
- Counterfactual Generator can pull historical invalidation conditions for similar patterns
- Regime Explainer can reference past regime transitions and how they resolved

### Retention

| Stream type | Retention |
|-------------|-----------|
| features / composite / patterns | 7–14 days |
| insight.v1 documents | 30–90 days (these are the memory) |

---

## High-Value Specialist Agents

In priority order based on signal value and implementation feasibility:

### Tier 1 — Build After MLAgent is live

| Agent | What it does | Why it's different from what exists |
|-------|-------------|--------------------------------------|
| **Fractal Multi-TF Pattern Matcher** | Detects when the same pattern archetype fires across 3+ timeframes simultaneously (1m→5m→15m→1h alignment) | Current system runs independent TF analysis. This adds meta-pattern recognition across the TF stack — high-confidence setup hierarchies |
| **Session Transition Intelligence** | Forecasts US opening direction based on Asian/European session handoff, overnight flow, and session-boundary effects | Current system has no cross-timezone lead-lag model. Predictable, proven edge in global equities |
| **Behavioral Sentiment Capture** | Infers emotional state (fear, greed, panic, euphoria) from price/volume microstructure without external data | Pure endogenous sentiment extraction from price action. Complements I8 narrative without requiring NLP/news feeds |
| **Agent Performance Auditor** | Continuously grades agent outputs against actual outcomes; dynamically adjusts agent influence per regime/setup | MLAgent rescores signals post-facto. This rescores the agents themselves in real-time — second-order adaptive system |

### Tier 2 — Future (v2.0+)

| Agent | What it does |
|-------|-------------|
| **Volatility Persistence Forecaster** | Models vol clustering as Markov chain; forecasts vol expansion/contraction 3–7 days ahead; predicts "quiet becomes explosive" |
| **Cross-Asset Correlation Breakdown Detector** | Detects when normally-correlated assets temporarily decouple (ES/NQ spread, bond/equity flip); treats breakdown as high-alpha event |
| **Institutional Footprint Tracker (Multi-TF)** | Follows institutional order signatures across days/weeks; identifies levels where smart money defends positions. Distinct from CIS — behavioural pattern matching |
| **Pattern Interaction Network** | Models how competing patterns interact and which typically wins — improves precision when multiple valid signals conflict simultaneously |
| **Adaptive Meta-Optimizer** | Learns which agent combinations work best in which market conditions; adjusts orchestration rules dynamically. Second-order learning over the agent system itself |

---

## Metrics to Track (when agents are live)

- Cross-agent reuse rate (cache hit rate on semantic memory)
- Cost per insight (token usage per signal)
- Calibration error (ECE/MCE) per agent — confidence bands should match realized outcomes
- Retrieval precision@k for semantic memory queries
- Prediction accuracy by regime type per agent

---

## Implementation Philosophy

1. **Specialized expertise over generalism** — each agent deep in one domain, not shallow across all
2. **Deterministic production decisions** — LLMs only in discovery and explanation roles; scoring is always algorithmic
3. **Transparent reasoning** — every agent explains its analysis; the reasoning chain is as important as the output
4. **Shadow mode first** — no agent affects live signal selection without p < 0.05 validation
5. **Build on MLAgent** — semantic memory and agent orchestration only make sense once the learning loop is closed
