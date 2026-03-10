# Future Vision — IndicAgent AI Agent Network

> Long-term strategic direction for Phases 6+. Concepts prioritized by value and feasibility.
> Source: `docs/plans/ai-agents-innovative-concepts-and-ideas-2025-08-11.md`

---

## Vision

Transform IndicAgent into an **AI-powered market intelligence system** through specialized agents that provide institutional-grade insights — each with deep domain expertise, working collaboratively via the intelligence bus.

**Guiding principle:** Intelligence-first, not complexity-first. Every agent must be able to explain its reasoning in plain English. Agents enhance human judgment, not replace it.

---

## Near-Term POCs (Phase 6+, High Value / Low Risk)

### 1. Pattern Insight Narratives (I8 extension)
Convert detected patterns into concise human-readable intelligence with rationale and confidence.
- Explain *why* a pattern matters now, in context (not just "RSI divergence detected")
- Summarize key contributing factors + confidence
- Provide invalidation levels and next-step guidance
- Consumes IntelligenceEvent; publishes `insight.v1` to `{env}:insight:{symbol}:{tf}`

### 2. Confluence Evaluator and Ranker (I6/I8)
Score and rank multi-signal setups; surface the strongest evidence.
- Aggregate multiple signals into a single weighted confluence score
- Highlight strongest supporting evidence AND disagreements
- Calibrate confidence using historical outcome accuracy
- Reduces false positives; improves signal prioritization

### 3. Counterfactual Insight Generator (I8)
"What would need to be true to validate or invalidate this setup?"
- Specify required metric deltas (RSI increase, volume threshold, etc.)
- Suggest monitoring triggers (levels, slopes, confirmations)
- Turns analysis into actionable monitoring and risk control

### 4. Regime Change Explainer / Daily Brief
Summarize market regime changes, drivers, and practical implications.
- Explain recent regime shifts and likely persistence
- Connect symbol-level context to market-level narrative
- Provides daily digest for decision context

### 5. Anomaly Triage Assistant (Operations)
Explain pipeline anomalies and recommend next actions.
- Identify likely root causes from observability signals
- Reduce time-to-diagnosis for on-call issues
- Consumes metrics; emits ops-focused insights

---

## Agent Orchestration Patterns

### Mixture-of-Agents (MoA) — recommended for complex signals
```
Proposers (parallel, smaller models):
  Pattern Agent → Context Agent → Risk Agent → Sentiment Agent
        ↓
Aggregator (larger model): unified output with weighted factors + uncertainty
        ↓
Critic Gate: evaluator reviews; triggers constrained retry if criteria fail
        ↓
Persistence: store proposer outputs, weights, rationale for auditability
```
- Use smaller models for proposers, reserve higher-quality model for aggregator
- A/B compare MoA vs single-model; calibrate weights on outcomes

### Sequential Analysis (current I8 pattern)
Pattern Agent → Context Agent → Risk Agent → Confluence Agent → Research overlay

### Adversarial Framework (for high-stakes signals)
- Bull Advocate Agent finds reasons for bullish analysis
- Bear Advocate Agent finds reasons for bearish analysis
- Neutral Analyst evaluates both objectively
- Reduces blind spots and groupthink

### Dynamic Leadership
- Volatility agent leads during high-volatility periods
- Momentum agent leads in trending markets
- Mean reversion agent leads in range-bound markets

---

## Interagent Learning & Memory Architecture

### Shared Evidence Bus
```
{env}:features:{symbol}:{tf}     (I1)
{env}:composite:{symbol}:{tf}    (I2-I7)
{env}:patterns:{symbol}:{tf}     (I5-I7)
{env}:regime:{scope}             (I4, MARKET or SYMBOL:TF)
{env}:insight:{symbol}:{tf}      (I8 narratives, counterfactuals, briefs)
```

### Semantic Memory (pgvector)
Store `insight.v1` documents in pgvector table for cross-agent retrieval.
- Embedding policy: hash-based cache; re-embed on schema/model change only
- Query by semantic similarity + filters (symbol, timeframe, tier)
- Agents cache evidence hashes to avoid duplicate LLM calls

### insight.v1 contract
```json
{
  "type": "insight.v1",
  "schema_version": "1.0.0",
  "symbol": "ES", "timeframe": "15m",
  "intelligence_tier": "I8",
  "insight_type": "pattern_explanation",
  "summary": "Bullish MACD divergence with volume confirmation",
  "evidence_sources": ["I5_macd_divergence", "I2_volume_composite"],
  "compute_plan_id": "dag_exec_12345"
}
```

### Governance
- Write ACL: only designated producers publish to each stream type
- Retention: features/composite/patterns 7-14 days; insight 30-90 days
- Versioning: bump `schema_version` on breaking changes; dual-read during migrations

---

## High-Value Specialist Agents (Phase 7+)

| Agent | Core capability | Priority |
|-------|----------------|----------|
| **Market Memory** | Institutional memory — track which patterns work in which regimes historically | High |
| **Confidence Calibration** | Post-hoc Platt/Isotonic calibration on all predictive outputs; monitors ECE/MCE drift | High |
| **Micro-Regime Nowcaster** | Short-horizon (3-10 bars) regime probabilities + expected persistence | High |
| **Time-to-Event Forecaster** | Probabilistic time-to-target/stop forecasts with confidence bands | Medium |
| **Volatility Regime Prophet** | Predict vol regime transitions; adjusts all other agents accordingly | Medium |
| **Institutional Footprint Tracker** | Track smart money positioning across multiple TFs; stealth accumulation detection | Medium |
| **Cross-Asset Lead/Lag Nowcast** | Near-term ES move conditioned on ZN/VIX leadership | Medium |
| **Early-Warning Rare-Event Detector** | Tail-risk nowcasts (gap risk, vol burst) tuned for low false positives | Medium |
| **Agent Performance Auditor** | Real-time accuracy tracking; dynamic weight adjustment across agent network | Low (requires data) |

---

## Implementation Philosophy

1. **Specialized expertise over generalism** — each agent is deep in one domain, not shallow across all
2. **Transparent reasoning** — every agent explains its analysis; reasoning as important as conclusion
3. **Actionable, not academic** — clear confidence levels, real-time applicability, risk-first
4. **Continuous learning** — agents improve from actual trade outcomes, not just backtest data
5. **Collaborative intelligence** — the network exceeds the sum of its parts through synthesis

---

## Metrics to Track (when agents are live)
- Cross-agent reuse rate (cache hit rate)
- Cost per insight (token usage)
- Calibration error (ECE/MCE) per agent
- Retrieval precision@k for semantic memory
- Prediction accuracy by regime type
