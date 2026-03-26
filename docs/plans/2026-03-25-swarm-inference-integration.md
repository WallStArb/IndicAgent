# Plan: Swarm Intelligence Integration (I8+)

## Objective
Integrate the I8 AI/ML Swarm to act as an asynchronous, predictive "Alpha Layer" that modulates signal confidence in real-time.

## Design
- **I8 Bus:** `intelligence.i8.alpha` (Inference output) + `intelligence.i8.swarm` (Reasoning).
- **Asynchronous Modulator:** The `PredictiveAlphaAgent` (I8) does not compute within the bar-close hot-path. It subscribes to the `I1-I6` feature topics, computes its Alpha Multipliers, and publishes them.
- **Dynamic Gating:** The `SignalGeneratorAgent` (I7) subscribes to `intelligence.i8.alpha` to adjust its confidence thresholds in real-time.

## Implementation Steps
1. **Schema:** Define `AlphaMultiplier` schema.
2. **Producer/Consumer:** Implement the swarm feedback loop across the Kafka bus.
3. **Resilience:** If Swarm/AlphaAgent data is stale (using `freshness` timestamps), the `SignalGeneratorAgent` defaults to `1.0` multiplier (Neutral).

## Verification
- **Alpha Decay Test:** Verify that confidence multipliers converge to 1.0 when the Swarm agent is disconnected.
- **Latency/Throughput:** Measure the propagation delay of an `AlphaMultiplier` injection.
