# Granular Redpanda Stream Topology

**Version:** 1.0
**Status:** draft
**Priority:** low
**Milestone:** future (trigger-driven — build when a real consumer needs it)
**Last Updated:** 2026-03-15
**Tags:** redpanda, streaming, architecture, intelligence, topic-design

---

## Current State

`market_analysis_service` publishes one `IntelligenceEvent` per bar to the `intelligence` topic. That event carries the full tier payload — I2 composite signals, I3 market structure, I4 regime/volatility, I5 patterns, I6 SMC/confluence — as nested JSONB. Every downstream consumer gets the full blob regardless of which tier it actually needs.

```
market_analysis_service → intelligence topic (full IntelligenceEvent per bar)
                              └── feature_writer consumes all
                              └── signal_generator consumes all
                              └── ai_narrative consumes all
```

## The Idea

Publish each intelligence tier to its own topic in addition to (or instead of) the monolithic event:

```
intelligence           — full IntelligenceEvent (current, kept for feature_writer)
intelligence.regime    — I4 regime/volatility state only (HMM, GARCH, BOCPD, Kalman)
intelligence.patterns  — I5 pattern detections only (chart patterns, divergence, squeeze)
intelligence.smc       — I6 SMC/confluence only (BOS/CHoCH, FVG, order blocks, killzones)
intelligence.composite — I2 composite event signals only (MACD/RSI/Stoch/ADX events)
```

Consumers subscribe to only what they need. A regime-only ML model doesn't pay the parsing cost of the full event. A cross-asset correlation service subscribes to `intelligence.regime` for all 60 instruments without pulling pattern or SMC noise.

## When This Becomes Worth Building

This isn't worth adding complexity until at least one real consumer justifies it. Concrete triggers:

1. **MLAgent feature pipeline** — the training data agent wants to subscribe to regime state across all 60 instruments in real time without processing full events. At 60 symbols × 6 TFs × full IntelligenceEvent, selective subscription matters.

2. **Cross-asset regime aggregator** — a service that tracks HMM regime across ES/NQ/RTY/GC/CL simultaneously to detect macro regime shifts would benefit from a lightweight `intelligence.regime` feed rather than deserializing full events.

3. **Real-time risk service (AegisAgent)** — a risk overlay that monitors volatility regime needs I4 data at sub-second latency. Separate topic means it never parses pattern or confluence data it doesn't use.

4. **QualAgent bridge** — qualitative signals want to combine with I4 regime for quantamental scoring. Regime topic makes this a clean subscription.

## Trade-offs

| Consideration | Impact |
|--------------|--------|
| Topic sprawl | +4–5 topics on top of current ~10 |
| Publish overhead | `market_analysis_service` publishes to N topics per bar instead of 1 |
| Consumer simplicity for full-event needs | Consumers needing all tiers now join across topics or still use monolithic `intelligence` |
| Replay correctness | Each topic can be replayed independently — ordering is per-partition, so multi-topic consumers need care on replay |
| Schema drift | Tier schemas can evolve independently without touching the full event |

## Implementation Notes

- The monolithic `intelligence` topic stays — `feature_writer` needs the full event for the `intelligence_features` hypertable write. Tier topics are additive, not replacements.
- `market_analysis_service` already assembles tier-specific output objects before assembling the full `IntelligenceEvent`. Separate publishes would extract those sub-objects with minimal refactoring.
- Partition key stays `SYMBOL:TF` — consistent routing across all topics.
- `src/core/stream_keys.py` would get `topic_intelligence_regime`, `topic_intelligence_patterns`, `topic_intelligence_smc`, `topic_intelligence_composite` helpers.

## Open Questions

- Do tier topics carry the same `ts`/`symbol`/`tf` envelope as the full event, or are they bare payloads? (Envelope is safer — makes consumers self-contained.)
- Should tier topics be opt-in at the service level (env flag) so they don't add publish overhead in dev/test?
- If MLAgent is the primary consumer, could it just read `intelligence_features` from TimescaleDB for training and skip real-time subscription entirely? (Likely yes for batch training — real-time inference is the only case that needs the stream.)
