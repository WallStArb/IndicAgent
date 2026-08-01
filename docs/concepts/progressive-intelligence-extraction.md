# Progressive Intelligence Extraction

**Version:** 1.0
**Status:** stale (v2.x, see banner)
**Last Updated:** 2026-05-30
**Tags:** intelligence-tiers, abstraction-layers, feature-extraction, signal-pipeline

> Raw market data contains no signal — it must be transformed through sequential layers of increasing abstraction before patterns emerge.

> **Staleness note (2026-08-01):** This doc describes the eight-tier I1-I8 `IntelligenceEvent`
> pipeline as the live abstraction ladder. That v2.x tier system has no live consumer as of
> 2026-07-02 per CLAUDE.md. Not yet rewritten for v3.0 -- tracked for a future doc pass, not
> fixed here.

## The Problem It Solves

Price and volume data are statistically noisy. A single OHLCV bar tells you almost nothing about whether to trade. The naive approach — "if RSI < 30, buy" — treats a single indicator as a decision. This produces a false positive rate that makes the rule unusable in production. The gap between "data" and "actionable intelligence" cannot be crossed in one step.

## The Principle

Each intelligence tier consumes the outputs of previous tiers and produces a richer abstraction. No tier can skip its predecessors because each layer's outputs are prerequisites for the next:

- Mathematical features (tier 1) are necessary inputs for composite events (tier 2)
- Composite events are necessary inputs for market structure (tier 3)
- Structure is necessary input for regime classification (tier 4)
- Regime shapes what patterns are meaningful (tier 5)
- Patterns feed confluence scoring (tier 6)
- Confluence enables principled signal generation (tier 7)
- Signals provide the context for AI narrative (tier 8)

The abstraction level increases at each tier. Tier 1 answers "what is RSI?" Tier 7 answers "is there a high-confidence trading setup now?" Tier 8 answers "what does this mean in market context?" These are genuinely different questions that require genuinely different computation.

## How IndicAgent Applies It

Eight tiers produce a typed `IntelligenceEvent` carrier that accumulates outputs across the pipeline:

| Tier | Name | What it produces |
|------|------|-----------------|
| I1 | Technical Indicators | Raw mathematical values: RSI, MACD, ATR, OBV, OFI, CVD |
| I2 | Composite Events | Discrete event flags: crossovers, threshold crosses, bars-since counts |
| I3 | Market Structure | Swing patterns, support/resistance levels, BOS/CHoCH detection |
| I4 | Regime Classification | Volatility regime, trend regime, HMM state, GARCH forecast, BOCPD changepoints |
| I5 | Pattern Detection | Chart patterns, RSI divergence, Bollinger squeeze, multi-TF volatility |
| I6 | Confluence Synthesis | SMC zones (OB/FVG/BOS), cross-TF confluence, CIS bucket scores |
| I7 | Trading Signals | Setup detection, signal scoring, CIS gating, shadow governance |
| I8 | AI Narrative | LLM-powered market narrative, swarm overlay, eAI agents (v2.8) |

The `IntelligenceEvent` (defined in `src/intelligence/schemas.py`) is the carrier — it accumulates outputs from each tier and is passed forward. Every I7 signal is emitted with the full I1-I7 feature context that produced it.

**Execution:** All I1-I7 tiers run inside `IntelligencePipeline` as a unified in-process pipeline. This eliminates inter-service Kafka latency for the tight coupling between tiers. I8 (AI Narrative) runs as a separate service for latency isolation — it is non-blocking and does not gate signal generation.

## Invariants

- Every I7 signal must have consumed I1-I6 outputs — no tier may bypass its prerequisites.
- Every tier output is typed in `IntelligenceEvent` — no untyped dict passing between tiers.
- I8 (AI Narrative) must never block or delay I7 signal publication. Narrative is commentary, not gating.
- The canonical tier lists live in `src/intelligence/register_plugins.py` `TIER_I1`..`TIER_I7` — no tier membership defined elsewhere.

## Recipe

When designing a progressive extraction pipeline for any domain:

1. **Map the abstraction ladder first.** What is the equivalent of "raw data," "events," "structure," "regime," "patterns," "signals" in your domain? Each level should answer a qualitatively different question.
2. **Make prerequisites explicit.** If tier N uses tier N-1 outputs, enforce this in the DAG — do not rely on execution order being correct by convention.
3. **Define a carrier type.** A typed object that accumulates tier outputs as it flows forward makes dependencies visible and prevents silent data gaps.
4. **Separate blocking from non-blocking tiers.** Fast tiers (I1-I7) run synchronously; slow tiers (I8/LLM) run out-of-band. Never let a slow tier block a fast one.
5. **Keep tier boundaries clean.** An I5 plugin should not need to read I6 outputs — if it does, the tier assignment is wrong. Cross-tier dependencies should flow in one direction only.

## See Also

- Implementation: `docs/intelligence/intelligence-foundation.md` — full tier responsibilities, plugin counts
- Typing: `src/intelligence/schemas.py` — `IntelligenceEvent` carrier definition
- Plugin registration: `src/intelligence/register_plugins.py` — canonical `TIER_I1`..`TIER_I7` lists
- Related concept: `docs/concepts/dag-execution.md` — how tier ordering is enforced via DAG
